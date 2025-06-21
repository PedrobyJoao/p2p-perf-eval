package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/google/uuid"
	"github.com/libp2p/go-libp2p"
	pubsub "github.com/libp2p/go-libp2p-pubsub"
	"github.com/libp2p/go-libp2p/core/host"
	"github.com/libp2p/go-libp2p/core/peer"
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

// broadcastMessage defines the message payload.
type broadcastMessage struct {
	MsgID string
}

func main() {
	// Disable standard log prefixes to keep JSON output clean.
	log.SetFlags(0)
	// Note: All output now goes to stdout.
	log.SetOutput(os.Stdout)

	bootstrapPeer := flag.String(
		"bootstrap-peer",
		"",
		"Multiaddress of a bootstrap peer",
	)
	flag.Parse()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Create a new libp2p host.
	// It listens on all available interfaces on a random port.
	h, err := libp2p.New(
		libp2p.ListenAddrStrings("/ip4/0.0.0.0/tcp/0"),
	)
	if err != nil {
		log.Fatalf("Failed to create host: %v", err)
	}
	defer h.Close()

	// Print the host's Peer ID to stdout for the orchestrator.
	fmt.Println(h.ID())

	// Initialize gossipsub.
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
	if *bootstrapPeer != "" {
		connectToPeer(ctx, h, *bootstrapPeer)
	}

	// Start an HTTP server to trigger message broadcasts.
	startBroadcastServer(topic)

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
			// Context cancellation will also trigger an error here.
			return
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

// startBroadcastServer sets up an HTTP endpoint to publish messages.
func startBroadcastServer(topic *pubsub.Topic) {
	http.HandleFunc("/broadcast", func(w http.ResponseWriter, r *http.Request) {
		msgID := uuid.New().String()
		bMsg := broadcastMessage{MsgID: msgID}
		msgBytes, err := json.Marshal(bMsg)
		if err != nil {
			http.Error(
				w,
				"Failed to marshal message",
				http.StatusInternalServerError,
			)
			return
		}

		// Log the broadcast event first.
		logJSON(logMessage{
			Event:       "message_broadcast",
			MsgID:       msgID,
			TimestampNs: time.Now().UnixNano(),
		})

		// Publish the message to the network.
		if err := topic.Publish(context.Background(), msgBytes); err != nil {
			log.Printf("Failed to publish message: %v", err)
		}

		fmt.Fprintf(w, "Broadcast message with ID: %s\n", msgID)
	})

	go func() {
		// Listen on port 8000 inside the container.
		if err := http.ListenAndServe(":8000", nil); err != nil {
			// Use a structured log for the fatal error.
			log.Fatalf(
				`{"event": "http_server_failed", "error": "%v"}`,
				err,
			)
		}
	}()
}

// logJSON marshals the log message to JSON and prints it.
func logJSON(msg logMessage) {
	b, err := json.Marshal(msg)
	if err != nil {
		// This is a fallback for logging issues.
		log.Printf("Failed to marshal log message: %v", err)
		return
	}
	fmt.Println(string(b))
}
