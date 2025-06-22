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

# --- Configuration ---
# Using 6 nodes: 1 bootstrap + 5 peers
NUM_PEERS = 5
# Name for the Docker image and network
IMAGE_NAME = "p2p-node"
NETWORK_NAME = "p2p-test-network"
# Path to the Go application's Dockerfile
DOCKERFILE_PATH = "./go-p2p"
# Ports used by the p2p node
API_PORT = 8000
P2P_PORT = 4001
# Timeouts for network setup and message propagation
NETWORK_FORMATION_TIME_S = 10
PROPAGATION_TIME_S = 5
# Output file for the latency plot
PLOT_FILE = "latency_distribution.png"

# --- Script Setup ---
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
        logging.info(f"Building Docker image: {IMAGE_NAME}")
        image = build_image(client)

        logging.info(f"Creating Docker network: {NETWORK_NAME}")
        network = client.networks.create(NETWORK_NAME, driver="bridge")

        logging.info("Starting bootstrap node...")

        # TODO: scale number of bootstrap nodes to number of total peers
        bootstrap_node = start_node(client, image, network, "bootstrap-node", None)
        containers.append(bootstrap_node)

        logging.info("Retrieving bootstrap multiaddress...")
        bootstrap_multiaddr = get_bootstrap_multiaddr(bootstrap_node)
        logging.info(f"Bootstrap address: {bootstrap_multiaddr}")

        logging.info(f"Starting {NUM_PEERS} peer nodes...")
        for i in range(NUM_PEERS):
            peer_node = start_node(
                client,
                image,
                network,
                f"peer-node-{i}",
                bootstrap_multiaddr,
            )
            containers.append(peer_node)

        logging.info("Waiting for network to form..." f"({NETWORK_FORMATION_TIME_S}s)")
        time.sleep(NETWORK_FORMATION_TIME_S)

        broadcasting_node = random.choice([c for c in containers if "peer" in c.name])
        logging.info(f"Triggering broadcast from {broadcasting_node.name}")
        trigger_broadcast(broadcasting_node)

        logging.info("Waiting for message propagation..." f"({PROPAGATION_TIME_S}s)")
        time.sleep(PROPAGATION_TIME_S)

        logging.info("Collecting logs for analysis...")
        latencies_ms = analyze_logs(containers)

        if latencies_ms is not None and not latencies_ms.empty:
            logging.info("Generating performance report...")
            generate_report(latencies_ms)
        else:
            logging.warning("No message data found. Skipping report.")

    except Exception as e:
        logging.error(f"An error occurred: {e}")
        if hasattr(e, "explanation"):
            logging.error(f"Explanation: {e.explanation}")
    finally:
        logging.info("Cleaning up resources...")
        cleanup(containers, network)
        logging.info("Cleanup complete.")


def build_image(client: docker.DockerClient):
    """Builds the Docker image from the go-p2p Dockerfile."""
    try:
        image, _ = client.images.build(path=DOCKERFILE_PATH, tag=IMAGE_NAME, rm=True)
        return image
    except docker.errors.BuildError as e:
        logging.error("Image build failed!")
        for line in e.build_log:
            if "stream" in line:
                logging.error(line["stream"].strip())
        raise


def start_node(
    client: docker.DockerClient,
    image: docker.models.images.Image,
    network: docker.models.networks.Network,
    name: str,
    bootstrap_addr: str | None,
):
    """Starts a single p2p node container."""
    command = [
        f"-hi=0.0.0.0",
        f"-ap={API_PORT}",
        f"-hp={P2P_PORT}",
    ]
    if bootstrap_addr:
        command.append(f"-bp={bootstrap_addr}")

    container = client.containers.run(
        image=image.id,
        command=command,
        name=name,
        network=network.name,
        detach=True,
        auto_remove=True,
        ports={f"{API_PORT}/tcp": None},
    )
    return container


def get_bootstrap_multiaddr(
    bootstrap_node: docker.models.containers.Container,
) -> str:
    """
    Retrieves the full multiaddress of the bootstrap node by
    inspecting its logs and network settings.
    """
    peer_id = None
    for _ in range(10):  # Try for 10 seconds
        logs = bootstrap_node.logs().decode("utf-8")
        for line in logs.split("\n"):
            if "node_initialized" in line:
                try:
                    log_json = json.loads(line)
                    peer_id = log_json.get("peer_id")
                    break
                except json.JSONDecodeError:
                    continue
        if peer_id:
            break
        time.sleep(1)

    if not peer_id:
        raise RuntimeError("Could not find Peer ID in bootstrap node logs.")

    bootstrap_node.reload()
    ip_addr = bootstrap_node.attrs["NetworkSettings"]["Networks"][NETWORK_NAME][
        "IPAddress"
    ]

    return f"/ip4/{ip_addr}/tcp/{P2P_PORT}/p2p/{peer_id}"


def trigger_broadcast(node: docker.models.containers.Container):
    """
    Triggers the message broadcast via the node's HTTP API.
    """
    node.reload()
    host_port = node.attrs["NetworkSettings"]["Ports"][f"{API_PORT}/tcp"][0]["HostPort"]

    url = f"http://localhost:{host_port}/broadcast"
    try:
        response = requests.post(url, timeout=5)
        response.raise_for_status()
        logging.info(f"Broadcast triggered on {node.name}.")
    except requests.RequestException as e:
        logging.error(f"Failed to trigger broadcast on {node.name}: {e}")
        raise


def analyze_logs(
    containers: list[docker.models.containers.Container],
) -> pd.Series | None:
    """
    Collects and parses logs from all containers and
    calculates message propagation latencies.
    """
    all_logs = []
    for container in containers:
        try:
            logs = container.logs().decode("utf-8")
            for line in logs.strip().split("\n"):
                try:
                    log_entry = json.loads(line)
                    log_entry["container_name"] = container.name
                    all_logs.append(log_entry)
                except json.JSONDecodeError:
                    continue
        except docker.errors.NotFound:
            logging.warning(f"Logs for {container.name} not found.")

    if not all_logs:
        return None

    df = pd.DataFrame(all_logs)
    broadcast_df = df[df["event"] == "message_broadcast"]
    if broadcast_df.empty:
        return None

    broadcast_event = broadcast_df.iloc[0]
    msg_id = broadcast_event["msg_id"]
    broadcast_time = broadcast_event["timestamp_ns"]

    received_df = df[
        (df["event"] == "message_received") & (df["msg_id"] == msg_id)
    ].copy()

    if received_df.empty:
        return None

    received_df["latency_ms"] = (
        received_df["timestamp_ns"] - broadcast_time
    ) / 1_000_000

    return received_df[received_df["latency_ms"] >= 0]["latency_ms"]


def generate_report(latencies_ms: pd.Series):
    """
    Calculates statistics and generates a plot from latency
    data.
    """
    stats = {
        "count": latencies_ms.count(),
        "mean (ms)": latencies_ms.mean(),
        "median (ms)": latencies_ms.median(),
        "std dev (ms)": latencies_ms.std(),
        "p95 (ms)": latencies_ms.quantile(0.95),
        "p99 (ms)": latencies_ms.quantile(0.99),
    }

    print("\n--- P2P Network Latency Report ---")
    for key, value in stats.items():
        print(f"{key:<15}: {value:.2f}")
    print("------------------------------------")

    plt.figure(figsize=(10, 6))
    sns.histplot(latencies_ms, kde=True, bins=15)
    plt.title("Message Propagation Latency Distribution")
    plt.xlabel("Latency (ms)")
    plt.ylabel("Number of Nodes")
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.savefig(PLOT_FILE)
    logging.info(f"Latency plot saved to {PLOT_FILE}")
    plt.close()


def cleanup(
    containers: list[docker.models.containers.Container],
    network: docker.models.networks.Network | None,
):
    """Stops and removes all created Docker resources."""
    for container in containers:
        try:
            container.stop(timeout=5)
            logging.info(f"Stopped container: {container.name}")
        except docker.errors.NotFound:
            pass  # Already stopped/removed
        except Exception as e:
            logging.warning(f"Could not stop {container.name}: {e}")

    if network:
        try:
            network.remove()
            logging.info(f"Removed network: {network.name}")
        except Exception as e:
            logging.warning(f"Could not remove network {network.name}: {e}")


if __name__ == "__main__":
    if not os.path.isdir(DOCKERFILE_PATH):
        logging.error(
            f"Directory '{DOCKERFILE_PATH}' not found. "
            "Please run from the repository root."
        )
        sys.exit(1)
    main()
