This repo was supposed to be about analysing performance of distributed networks.

But it's really just me playing and learning a few things.

You won't find serious results here.

## How? (Conceptually)

The mesh will be constructed as follows:

1. Create a docker network
2. Deploy a single bootstrap node and retrieve its identifier
3. Deploy all other nodes given the bootstrap node's identifier

Now we have the mesh. Gather logs from daemons, metrics/observability data or whatever.. and do your experiments.

## How? (In practice) see experiments/simple.py

A simple libp2p node under `go-p2p/` without peer discovery.

It uses libp2p's Prometheus metrics.

The goal was to analyse the resource usage of a go-libp2p node given the number of connections.

More specifically, the scenario is a single bootstrap node being connected to `n` peers.
All the other peers connect **only** to the bootstrap node. (again, no peer discovery here)

We then compare the resource usage of the bootstrap node with the resource usage of other peers.

Running the experiment:

```bash
uv sync
uv run experiments/simple.py
```

Results will be stored at `./resource_comparison.png`

## What is left to be a useful tool?

1. Allow arbitrary configuration of daemon port settings.
   This will allow for this engine to be used by any software (given a docker image)
2. Make mesh topology parameterizable.
3. Support for deployment of application monitoring tools

### Testground or Kubernetes or Docker Compose or Shadow?

I didn't use any of these as I tried to keep it simple.

But in large-scale experiments I'd probably use some of these tools.

Some useful readings about:

**How libp2p performs distributed testing:**

- moving away from testground: https://github.com/libp2p/test-plans/issues/103
- libp2p tests with docker-compose: https://github.com/libp2p/test-plans/pull/97

**libp2p: What to test specifically:**

- https://github.com/libp2p/test-plans/blob/marco/perf/perf-dashboard/README.md
- libp2p test plan roadmap: https://github.com/libp2p/test-plans/blob/master/ROADMAP.md

**Misc still interesting**:

- https://github.com/libp2p/test-plans/issues/27
- cool UI to get inspired I guess: https://microsoft.github.io/msquic/
