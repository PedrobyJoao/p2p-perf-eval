import logging
import time


from mesh import Mesh


IMAGE_NAME = "go-p2p-node"
NETWORK_NAME = "p2p-test-network"
BOOTSTRAP_NAME = "bootstrap-node"
DOCKERFILE_PATH = "./go-p2p"
P2P_PORT = 4001
NUM_PEERS = 5


def main():
    """
    Main function to orchestrate the P2P network analysis.
    It builds, deploys, tests, and cleans up the network.
    """
    try:
        with Mesh(
                image_name=IMAGE_NAME, network_name=NETWORK_NAME,
                num_peers=NUM_PEERS, dockerfile_path=DOCKERFILE_PATH) as mesh:
            logging.info("Mesh is up and running.")
            if mesh.bootstrap_node:
                logging.info(f"Bootstrap API running on port: {mesh.bootstrap_node.api_port}")
            
            logging.info(f"Keeping mesh alive for analysis...")
            time.sleep(100)
            
            logging.info("Analysis complete, shutting down.")
    
    except Exception as e:
        logging.error(f"An error occurred during the mesh lifecycle: {e}", exc_info=True)


if __name__ == "__main__":
    main()
