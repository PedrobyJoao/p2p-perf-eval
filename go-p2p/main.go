package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/libp2p/go-libp2p"
	dht "github.com/libp2p/go-libp2p-kad-dht"
	pubsub "github.com/libp2p/go-libp2p-pubsub"
	"github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/peer"
	"github.com/libp2p/go-libp2p/core/routing"
	"github.com/multiformats/go-multiaddr"
)

// The topic name for gossipsub.
const topicName = "/test/1"

// logMessage defines the structured log format.
type logMessage struct {
	Event       string `json:"event"`
	MsgID       string `json:"msg_id"`
	Sender      string `json:"sender,omitempty"`
	TimestampNs int64  `json:"timestamp_ns"`
}

func main() {
	// Disable standard log prefixes to keep JSON output clean.
	log.SetFlags(0)
	log.SetOutput(os.Stdout)

	// Define variables to hold flag values.
	var hostIP, bootstrapPeer string
	var hostPort, apiPort int

	// Command-line flags for network configuration.
	//
	// Example usage:
	// To run the first (bootstrap) node:
	// go run . -ap 8000
	//
	// To run a peer node connecting to the bootstrap node:
	// go run . -ap 8001 -bp <bootstrap-node-multiaddress>

	// host-ip / hi
	flag.StringVar(&hostIP, "host-ip", "127.0.0.1", "IP address for the libp2p host")
	flag.StringVar(&hostIP, "hi", "127.0.0.1", "IP address for the libp2p host (shorthand)")

	// host-port / hp
	flag.IntVar(&hostPort, "host-port", 9999, "TCP port for the libp2p host (0 for random)")
	flag.IntVar(&hostPort, "hp", 9999, "TCP port for the libp2p host (shorthand)")

	// api-port / ap
	flag.IntVar(&apiPort, "api-port", 8000, "Port for the HTTP API server")
	flag.IntVar(&apiPort, "ap", 8000, "Port for the HTTP API server (shorthand)")

	// bootstrap-peer / bp
	flag.StringVar(&bootstrapPeer, "bootstrap-peer", "", "Multiaddress of a bootstrap peer")
	flag.StringVar(&bootstrapPeer, "bp", "", "Multiaddress of a bootstrap peer (shorthand)")

	flag.Parse()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Construct the listen address for the libp2p host.
	listenAddr := fmt.Sprintf("/ip4/%s/tcp/%d", hostIP, hostPort)

	var idht *dht.IpfsDHT
	var err error
	h, err := libp2p.New(
		libp2p.ListenAddrStrings(listenAddr),
		libp2p.Routing(func(h host.Host) (routing.PeerRouting, error) {
			idht, err = dht.New(ctx, h)
			return idht, err
		}),
	)
	if err != nil {
		log.Fatalf("Failed to create host: %v", err)
	}
	defer h.Close()

	// The first line of output is the Peer ID for the orchestrator.
	fmt.Println(h.ID())
	fmt.Println(h.Addrs())

	ps, err := pubsub.NewGossipSub(ctx, h)
	if err != nil {
		log.Fatalf("Failed to create pubsub: %v", err)
	}

	// Subscribe to the topic.
	topic, err := ps.Join(topicName)
	if err != nil {
		log.Fatalf("Failed to join topic: %v", err)
	}
	sub, err := topic.Subscribe()
	if err != nil {
		log.Fatalf("Failed to subscribe to topic: %v", err)
	}

	// Start a background goroutine to handle incoming messages.
	go handleMessages(ctx, sub, h.ID())

	// If a bootstrap peer is provided, connect to it.
	if bootstrapPeer != "" {
		connectToPeer(ctx, h, bootstrapPeer)
	}

	// Start an HTTP server to trigger message broadcasts.
	apiListenAddr := fmt.Sprintf(":%d", apiPort)
	startAPIServer(apiListenAddr, topic)

	// Wait for a termination signal.
	sigCh := make(chan os.Signal, 1)
	signal.Notify(
		sigCh,
		syscall.SIGINT,
		syscall.SIGTERM,
	)
	<-sigCh
	logJSON(logMessage{Event: "shutdown"})
}

// handleMessages reads messages from the subscription and logs them.
func handleMessages(ctx context.Context, sub *pubsub.Subscription, selfID peer.ID) {
	for {
		msg, err := sub.Next(ctx)
		if err != nil {
			return // Context cancellation will trigger an error.
		}

		// Don't log messages we sent ourselves.
		if msg.GetFrom() == selfID {
			continue
		}

		var bMsg broadcastMessage
		if err := json.Unmarshal(msg.Data, &bMsg); err != nil {
			continue // Ignore malformed messages.
		}

		logJSON(logMessage{
			Event:       "message_received",
			MsgID:       bMsg.MsgID,
			Sender:      msg.GetFrom().String(),
			TimestampNs: time.Now().UnixNano(),
		})
	}
}

// connectToPeer connects the host to a given bootstrap peer.
func connectToPeer(ctx context.Context, h host.Host, peerAddr string) {
	addr, err := multiaddr.NewMultiaddr(peerAddr)
	if err != nil {
		log.Printf("Invalid bootstrap address: %v", err)
		return
	}
	peerInfo, err := peer.AddrInfoFromP2pAddr(addr)
	if err != nil {
		log.Printf("Failed to get peer info: %v", err)
		return
	}

	if err := h.Connect(ctx, *peerInfo); err != nil {
		log.Printf("Bootstrap connection failed: %v", err)
	}
}

// logJSON marshals the log message to JSON and prints it.
func logJSON(msg logMessage) {
	b, err := json.Marshal(msg)
	if err != nil {
		log.Printf("Failed to marshal log message: %v", err)
		return
	}
	fmt.Println(string(b))
}
