import docker
import json
import logging
import os
import random
import socket
import sys
import time

from contextlib import closing
from dataclasses import dataclass

import pandas as pd
import requests
import seaborn as sns
import matplotlib.pyplot as plt

from docker import errors
from docker.models.containers import Container
from docker.models.images import Image
from docker.models.networks import Network


IMAGE_NAME = "go-p2p-node"
NETWORK_NAME = "p2p-test-network"
BOOTSTRAP_NAME = "bootstrap-node"
DOCKERFILE_PATH = "./go-p2p"
P2P_PORT = 4001
NUM_PEERS = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)

@dataclass
class NodeInfo:
    """Holds information about a running node container."""
    container: Container
    api_port: int
    metrics_port: int


def main():
    """
    Main function to orchestrate the P2P network analysis.
    It builds, deploys, tests, and cleans up the network.
    """
    client = docker.from_env()
    network = None
    nodes: list[NodeInfo] = []

    try:
        # 1. Create Docker network
        network = create_network(client)
        
        # 2. Build image based on dockerfile path
        image = build_image(client)

        # Find free ports for all nodes (bootstrap + )
        total_nodes = NUM_PEERS + 1
        logging.info(f"Finding {total_nodes * 2} free ports for API and metrics...")
        api_ports = get_free_ports(total_nodes)
        metrics_ports = get_free_ports(total_nodes)

        # 3. Deploy bootstrap peer and retrieve its peer ID
        logging.info("Deploying bootstrap peer...")
        bootstrap_api_port = api_ports[0]
        bootstrap_metrics_port = metrics_ports[0]

        bootstrap_container = deploy_peer(
            client=client,
            image=image,
            network=network,
            metrics_port=bootstrap_metrics_port,
            api_port=bootstrap_api_port,
        )
        nodes.append(NodeInfo(
            container=bootstrap_container,
            api_port=bootstrap_api_port,
            metrics_port=bootstrap_metrics_port
        ))

        bootstrap_peer_id = get_peer_id(bootstrap_container)
        if not bootstrap_peer_id:
            raise RuntimeError("Failed to retrieve bootstrap peer ID.")
        
        logging.info(f"Bootstrap peer deployed with ID: {bootstrap_peer_id}")

        # 4. Deploy peer nodes
        for i in range(NUM_PEERS):
            # Use i+1 because index 0 is for the bootstrap node
            api_port = api_ports[i + 1]
            metrics_port = metrics_ports[i + 1]
            logging.info(f"Deploying peer node {i+1}/{NUM_PEERS}...")
            peer_container = deploy_peer(
                client=client,
                image=image,
                network=network,
                metrics_port=metrics_port,
                api_port=api_port,
                bootstrap_peer_id=bootstrap_peer_id,
            )
            nodes.append(NodeInfo(
                container=peer_container,
                api_port=api_port,
                metrics_port=metrics_port
            ))
        
        logging.info(f"Successfully deployed {len(nodes)} nodes in total.")
        time.sleep(100)

    except Exception as e:
        logging.error(f"An error occurred during orchestration: {e}", exc_info=True)

    finally:
        logging.info("Cleaning up resources...")
        for node in nodes:
            try:
                node.container.stop()
                node.container.remove()
                logging.info(f"Stopped and removed container: {node.container.name}")
            except errors.NotFound:
                logging.warning(f"Container {node.container.name} not found for cleanup, already removed.")
            except Exception as e:
                logging.error(f"Error cleaning up container {node.container.name}: {e}")
        
        if network:
            try:
                network.remove()
                logging.info(f"Removed network: {NETWORK_NAME}")
            except errors.NotFound:
                logging.warning(f"Network {NETWORK_NAME} not found for cleanup, already removed.")
            except Exception as e:
                logging.error(f"Error removing network {NETWORK_NAME}: {e}")


def get_free_ports(count: int) -> list[int]:
    """Finds a specified number of free TCP ports on the host."""
    ports = []
    for _ in range(count):
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.bind(("", 0))
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            ports.append(s.getsockname()[1])
    if ports.__len__() != count:
        raise ValueError(f"Failed to find {count} free ports")
    return ports


def create_network(client: docker.DockerClient) -> Network:
    """Creates a Docker network."""
    # In case of a previous failed run, remove the old network.
    try:
        existing_network = client.networks.get(NETWORK_NAME)
        logging.info(f"Removing existing network: {NETWORK_NAME}")
        existing_network.remove()
    except errors.NotFound:
        pass

    logging.info(f"Creating Docker network: {NETWORK_NAME}")
    return client.networks.create(NETWORK_NAME, driver="bridge")


def build_image(client: docker.DockerClient) -> Image:
    """Builds the Docker image from the go-p2p Dockerfile."""
    logging.info(f"Building Docker image: {IMAGE_NAME} from {DOCKERFILE_PATH}")
    image, _ = client.images.build(
        path=DOCKERFILE_PATH,
        tag=IMAGE_NAME,
        rm=True
    )
    logging.info(f"Successfully built image: {image.id}")
    return image


def deploy_peer(
    client: docker.DockerClient,
    image: Image,
    network: Network,
    metrics_port: int,
    api_port: int,
    bootstrap_peer_id: str | None = None,
) -> Container:
    """
    Deploys a single P2P node as a Docker container.

    If 'bootstrap_peer_id' is None, it deploys a bootstrap node.
    Otherwise, it deploys a peer node that connects to the bootstrap node.
    """
    command = [
        "-ap", str(api_port),
        "-mp", str(metrics_port),
        "-hi", "0.0.0.0",
    ]

    # if no bootstrap peer is provided, this node is the bootstrapper.
    if not bootstrap_peer_id:
        container_name = BOOTSTRAP_NAME
    else:
        # this is a peer node
        container_name = f"p2p-peer-node-{api_port}"
        bootstrap_addr = (
            f"/dns4/{BOOTSTRAP_NAME}/tcp/{P2P_PORT}/p2p/{bootstrap_peer_id}/"
        )
        command.extend(["-bp", bootstrap_addr])

    # Check for and remove an existing container with the same name.
    try:
        existing_container = client.containers.get(container_name)
        logging.warning(f"Removing existing container: {container_name}")
        existing_container.remove(force=True)
    except errors.NotFound:
        pass  # This is the expected case.

    # Map the container ports to the same ports on the host.
    ports = {
        f"{api_port}/tcp": api_port,
        f"{metrics_port}/tcp": metrics_port,
    }

    logging.info(f"Deploying container '{container_name}' with command: {' '.join(command)}")

    container = client.containers.run(
        image=image,
        command=command,
        name=container_name,
        network=network.name,
        ports=ports,
        detach=True
    )

    logging.info(f"Container {container.name} started with ID: {container.short_id}")
    return container

def get_peer_id(container: Container, timeout: int = 10) -> str | None:
    """
    Retrieves the peer ID from the container's logs.
    The Go application is expected to print the peer ID on the first line.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        logs = container.logs().decode("utf-8")
        if logs:
            lines = logs.strip().split("\n")
            if lines and lines[0].startswith("12D"):
                return lines[0].strip()
        time.sleep(0.5)
    logging.error(f"Timeout: Could not find peer ID for container {container.name} in {timeout}s")
    return None


if __name__ == "__main__":
    main()
