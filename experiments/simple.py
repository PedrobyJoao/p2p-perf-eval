import logging
import time
from typing import Dict

import pandas as pd
import requests
import seaborn as sns
import matplotlib.pyplot as plt

from src import const
from src.mesh import Mesh

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def main():
    """
    This experiment compares the resource usage (Memory, Goroutines) of the
    central bootstrap node against the average usage of the peer nodes in a
    star topology network.
    """
    EXPERIMENT_DURATION_S = 60
    POLL_INTERVAL_S = 5
    NUM_PEERS = 100

    with Mesh(
        image_name=const.IMAGE_NAME,
        network_name=const.NETWORK_NAME,
        num_peers=NUM_PEERS, # my pc could handle only 250 nodes
        dockerfile_path=const.DOCKERFILE_PATH,
    ) as mesh:
        logging.info("Mesh deployed. Waiting 10 seconds for network to stabilize...")
        time.sleep(10)

        all_metrics_data = []
        start_time = time.time()

        logging.info(f"Starting resource monitoring for {EXPERIMENT_DURATION_S} seconds...")

        while time.time() - start_time < EXPERIMENT_DURATION_S:
            elapsed_time = round(time.time() - start_time)

            for node in mesh.nodes:
                metrics = get_resource_metrics(node.metrics_port)
                if not metrics:
                    continue

                node_name = node.container.name

                all_metrics_data.append({
                    "time_elapsed_s": elapsed_time,
                    "node_name": node_name,
                    "role": "bootstrap" if node == mesh.bootstrap_node else "peer",
                    "mem_alloc_mb": metrics["go_memstats_alloc_bytes"] / (1024 * 1024),
                    "goroutines": metrics["go_goroutines"],
                })

            time.sleep(POLL_INTERVAL_S)

        if not all_metrics_data:
            logging.error("No metrics were collected. Exiting.")
            return

        # --- Analysis and Visualization ---
        df = pd.DataFrame(all_metrics_data)

        # Separate bootstrap and peer data using .loc for type safety
        bootstrap_df = df.loc[df["role"] == "bootstrap"].set_index("time_elapsed_s")
        peers_df = df.loc[df["role"] == "peer"]

        # Calculate average for peers
        peers_avg_df = peers_df.groupby("time_elapsed_s").mean(numeric_only=True)

        # Combine for plotting
        comparison_df = bootstrap_df.join(peers_avg_df, lsuffix='_bootstrap', rsuffix='_peer')
        print("\n--- Resource Usage Comparison (Bootstrap vs. Average Peer) ---")
        print(comparison_df[[
            'mem_alloc_mb_bootstrap', 'mem_alloc_mb_peer',
            'goroutines_bootstrap', 'goroutines_peer'
        ]].to_string())

        # Create plots
        sns.set_theme(style="darkgrid")
        fig, axes = plt.subplots(2, 1, figsize=(12, 10), sharex=True)
        fig.suptitle(f'Resource Usage with a network of {NUM_PEERS} peers', fontsize=16)

        # Memory Plot
        sns.lineplot(
                data=comparison_df, x=comparison_df.index,
                y='mem_alloc_mb_bootstrap', ax=axes[0],
                label='Bootstrap', marker='o',
                )
        sns.lineplot(
                data=comparison_df, x=comparison_df.index,
                y='mem_alloc_mb_peer', ax=axes[0],
                label='Peer Average', marker='o',
                )
        axes[0].set_title("Allocated Memory")
        axes[0].set_ylabel("Memory (MB)")
        axes[0].legend()

        # Goroutines Plot
        sns.lineplot(data=comparison_df, x=comparison_df.index, y='goroutines_bootstrap', ax=axes[1], label='Bootstrap', marker='o')
        sns.lineplot(data=comparison_df, x=comparison_df.index, y='goroutines_peer', ax=axes[1], label='Peer Average', marker='o')
        axes[1].set_title("Goroutine Count")
        axes[1].set_ylabel("Count")
        axes[1].set_xlabel("Time Elapsed (seconds)")
        axes[1].legend()

        # Use a tuple for the rect parameter
        plt.tight_layout(rect=(0, 0.03, 1, 0.97))
        plot_filename = "resource_comparison.png"
        plt.savefig(plot_filename)
        logging.info(f"Plot saved to {plot_filename}")


def get_resource_metrics(metrics_port: int) -> Dict[str, float] | None:
    """
    Queries a node's plain text metrics endpoint and parses the values.
    """
    # TODO: use queries (I tried and it didn't work for some reason)
    url = f"http://localhost:{metrics_port}/debug/metrics/prometheus"
    metric_names = [
        "go_memstats_alloc_bytes",
        "go_goroutines",
    ]
    results = {}

    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        # The response is plain text, not JSON.
        text_data = response.text
        lines = text_data.splitlines()

        for line in lines:
            # Ignore comments and empty lines
            if line.startswith("#") or not line.strip():
                continue

            for metric_name in metric_names:
                if line.startswith(metric_name):
                    # The format is "metric_name{labels} value" or "metric_name value"
                    parts = line.split()
                    if parts:
                        results[metric_name] = float(parts[-1])
                        break # Move to the next line once a metric is found

        # Ensure all expected metrics were found
        if len(results) == len(metric_names):
            return results
        else:
            logging.warning(f"Incomplete metrics from port {metrics_port}. Found: {list(results.keys())}")
            return None

    except requests.RequestException as e:
        logging.warning(f"Failed to get metrics from port {metrics_port}: {e}")
        return None
    except (ValueError, IndexError) as e:
        logging.error(f"Error parsing metrics text from port {metrics_port}: {e}")
        return None


if __name__ == "__main__":
    main()
