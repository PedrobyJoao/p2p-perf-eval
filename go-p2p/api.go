package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"time"

	"github.com/google/uuid"
	pubsub "github.com/libp2p/go-libp2p-pubsub"
)

// broadcastMessage defines the message payload.
type broadcastMessage struct {
	MsgID string `json:"msg_id"`
}

// broadcastHandler creates an http.HandlerFunc that publishes a message
// to a gossipsub topic when invoked.
func broadcastHandler(topic *pubsub.Topic) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
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

		logJSON(logMessage{
			Event:       "message_broadcast",
			MsgID:       msgID,
			TimestampNs: time.Now().UnixNano(),
		})

		if err := topic.Publish(context.Background(), msgBytes); err != nil {
			log.Printf("Failed to publish message: %v", err)
		}

		fmt.Fprintf(w, "Broadcast message with ID: %s\n", msgID)
	}
}

// startAPIServer initializes and runs the HTTP server in a goroutine.
func startAPIServer(listenAddr string, topic *pubsub.Topic) {
	mux := http.NewServeMux()
	mux.HandleFunc("/broadcast", broadcastHandler(topic))

	go func() {
		if err := http.ListenAndServe(listenAddr, mux); err != nil {
			log.Fatalf(
				`{"event": "http_server_failed", "error": "%v"}`,
				err,
			)
		}
	}()
}
