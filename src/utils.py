import docker
import logging
import socket

from contextlib import closing
from docker import errors
from docker.models.images import Image
from docker.models.networks import Network


def create_network(
        client: docker.DockerClient,
        name: str) -> Network:
    """Creates a Docker network."""
    # In case of a previous failed run, remove the old network.
    try:
        existing_network = client.networks.get(name)
        logging.info(f"Removing existing network: {name}")
        existing_network.remove()
    except errors.NotFound:
        pass

    logging.info(f"Creating Docker network: {name}")
    return client.networks.create(name, driver="bridge")


def build_image(
        client: docker.DockerClient,
        dockerfile_path: str,
        img_name: str
        ) -> Image:
    """Builds the Docker image from the go-p2p Dockerfile."""
    logging.info(f"Building Docker image: {img_name} from {dockerfile_path}")
    image, _ = client.images.build(
        path=dockerfile_path,
        tag=img_name,
        rm=True
    )
    logging.info(f"Successfully built image: {image.id}")
    return image


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
