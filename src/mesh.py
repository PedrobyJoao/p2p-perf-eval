import docker
import logging
import sys
import time

from utils import build_image, create_network, get_free_ports

from dataclasses import dataclass
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


@dataclass
class NodeInfo:
    """Holds information about a running node container."""
    container: Container
    api_port: int
    metrics_port: int

    def cleanup(self):
        try:
            self.container.stop()
            self.container.remove()
            logging.info(f"Stopped and removed container: {self.container.name}")
        except errors.NotFound:
            logging.warning(f"Container {self.container.name} not found for cleanup, already removed.")
        except Exception as e:
            logging.error(f"Error cleaning up container {self.container.name}: {e}")

class Mesh:
    """
    Manages the lifecycle of the entire P2P Docker network.

    - TODO: handle more than 1 bootstrap node
    - TODO: handle different implementations with different ways of setting configs (e.g.: ports)
    """

    def __init__(
            self, image_name: str,
            network_name: str, num_peers: int,
            dockerfile_path: str,
            ):
        self.client = docker.from_env()
        self.image_name = image_name
        self.network_name = network_name
        self.num_peers = num_peers
        self.dockerfile_path = dockerfile_path
        
        self.network: Network | None = None
        self.nodes: list[NodeInfo] = []

    def deploy(self):
        """Builds and deploys the entire mesh of nodes."""
        # 1. Create Docker network
        self.network = create_network(self.client, self.network_name)
        
        # 2. Build image based on dockerfile path
        image = build_image(self.client, self.dockerfile_path, self.image_name)

        # Find free ports for all nodes (bootstrap + peers)
        total_nodes = self.num_peers + 1
        logging.info(f"Finding {total_nodes * 2} free ports for API and metrics...")
        api_ports = get_free_ports(total_nodes)
        metrics_ports = get_free_ports(total_nodes)

        # 3. Deploy bootstrap peer and retrieve its peer ID
        logging.info("Deploying bootstrap peer...")
        bootstrap_api_port = api_ports[0]
        bootstrap_metrics_port = metrics_ports[0]

        bootstrap_container = deploy_peer(
            client=self.client,
            image=image,
            network=self.network,
            metrics_port=bootstrap_metrics_port,
            api_port=bootstrap_api_port,
        )
        self.nodes.append(NodeInfo(
            container=bootstrap_container,
            api_port=bootstrap_api_port,
            metrics_port=bootstrap_metrics_port
        ))

        bootstrap_peer_id = get_peer_id(bootstrap_container)
        if not bootstrap_peer_id:
            raise RuntimeError("Failed to retrieve bootstrap peer ID.")
        
        logging.info(f"Bootstrap peer deployed with ID: {bootstrap_peer_id}")

        # 4. Deploy peer nodes
        for i in range(self.num_peers):
            # Use i+1 because index 0 is for the bootstrap node
            api_port = api_ports[i + 1]
            metrics_port = metrics_ports[i + 1]
            logging.info(f"Deploying peer node {i+1}/{self.num_peers}...")
            peer_container = deploy_peer(
                client=self.client,
                image=image,
                network=self.network,
                metrics_port=metrics_port,
                api_port=api_port,
                bootstrap_peer_id=bootstrap_peer_id,
            )
            self.nodes.append(NodeInfo(
                container=peer_container,
                api_port=api_port,
                metrics_port=metrics_port
            ))
        
        logging.info(f"Successfully deployed {len(self.nodes)} nodes in total.")

    def cleanup(self):
        """Stops and removes all containers and the network."""
        logging.info("Cleaning up P2P mesh resources...")
        for node in self.nodes:
            node.cleanup()
        
        if self.network:
            try:
                self.network.remove()
                logging.info(f"Removed network: {self.network_name}")
            except errors.NotFound:
                logging.warning(f"Network {self.network_name} not found for cleanup, already removed.")
            except Exception as e:
                logging.error(f"Error removing network {self.network_name}: {e}")

    @property
    def bootstrap_node(self) -> NodeInfo | None:
        """Returns the bootstrap node info, if it exists."""
        return self.nodes[0] if self.nodes else None

    @property
    def peer_nodes(self) -> list[NodeInfo]:
        """Returns a list of all non-bootstrap peer nodes."""
        return self.nodes[1:] if len(self.nodes) > 1 else []

    def __enter__(self):
        self.deploy()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()


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
