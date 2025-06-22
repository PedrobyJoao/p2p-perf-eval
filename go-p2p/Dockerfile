# Stage 1: Build the application
# Use a specific Go version for reproducibility.
FROM golang:1.24-alpine AS builder

# Set the working directory inside the container.
WORKDIR /app

# Copy module files and download dependencies first to leverage
# Docker layer caching. If go.mod and go.sum don't change,
# this layer will be reused.
COPY go.mod go.sum ./

RUN go mod download

# Copy the rest of the source code.
COPY . .

# Build the Go application. The -o flag specifies the output
# file name. CGO_ENABLED=0 creates a static binary.
RUN CGO_ENABLED=0 go build -o /app/p2p-node .

# Stage 2: Create the final, minimal image
# Use a minimal base image for a small footprint.
FROM alpine:latest

# Copy the compiled binary from the builder stage.
COPY --from=builder /app/p2p-node /usr/local/bin/p2p-node

# Expose the default port for the HTTP broadcast server.
# This is for documentation; the orchestrator will map ports.
EXPOSE 8000

# Set the entrypoint for the container. The application will run
# when the container starts. Flags can be passed to this
# entrypoint.
ENTRYPOINT ["p2p-node"]

CMD ["-hi=0.0.0.0"]
