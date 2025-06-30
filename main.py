import docker
import json
import logging
import os
import random
import sys
import time

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
DOCKERFILE_PATH = "./go-p2p"
P2P_PORT = 4001
BOOTSTRAP_API_PORT = 8000
BOOTSTRAP_METRICS_PORT = 5001

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)

def main():
    """
    Main function to orchestrate the P2P network analysis.
    It builds, deploys, tests, and cleans up the network.
    """
    client = docker.from_env()
    network = None
    containers = []

    try:
        # 1. Create Docker network
        network = create_network(client)
        
        # 2. Build image based on dockerfile path
        image = build_image(client)

        # 3. Deploy bootstrap peer and retrieve its peer ID
        logging.info("Deploying bootstrap peer...")
        bootstrap_container = deploy_peer(
            client=client,
            image=image,
            network=network,
            metrics_port=BOOTSTRAP_METRICS_PORT,
            api_port=BOOTSTRAP_API_PORT,
        )
        containers.append(bootstrap_container)

        bootstrap_peer_id = get_peer_id(bootstrap_container)
        if not bootstrap_peer_id:
            raise RuntimeError("Failed to retrieve bootstrap peer ID.")
        
        logging.info(f"Bootstrap peer deployed with ID: {bootstrap_peer_id}")

        # TODO 4. range over num of peers to test and deploy them passing bootstapper peerID
    except Exception as e:
        logging.error(f"Error occurred: {e}")

    finally:
        logging.info("Cleaning up resources...")
        for container in containers:
            try:
                container.stop()
                container.remove()
                logging.info(f"Stopped and removed container: {container.name}")
            except errors.NotFound:
                logging.warning(f"Container {container.name} not found for cleanup, already removed.")
            except Exception as e:
                logging.error(f"Error cleaning up container {container.name}: {e}")
        
        if network:
            try:
                network.remove()
                logging.info(f"Removed network: {NETWORK_NAME}")
            except errors.NotFound:
                logging.warning(f"Network {NETWORK_NAME} not found for cleanup, already removed.")
            except Exception as e:
                logging.error(f"Error removing network {NETWORK_NAME}: {e}")
    

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
    ]

    # if no bootstrap peer is provided, this node is the bootstrapper.
    if not bootstrap_peer_id:
        container_name = "bootstrap-node"
    else:
        # this is a peer node
        container_name = f"p2p-peer-node-{api_port}"
        bootstrap_addr = (
            f"/dns4/bootstrap-node/tcp/{P2P_PORT}/p2p/{bootstrap_peer_id}"
        )
        command.extend(["-bp", bootstrap_addr])

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
                return lines[0]
        time.sleep(0.5)
    logging.error(f"Timeout: Could not find peer ID for container {container.name} in {timeout}s")
    return None


if __name__ == "__main__":
    main()
