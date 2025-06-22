### How?

Retrieving logs from libp2p nodes which can be implementend in any
language.

The suite will deploy multiple nodes using Docker containers.

Because we're using the Docker network, the libp2p nodes must use
`0.0.0.0` as the listen address IP.

1. Create docker network
2. Deploy bootstrap node(s) specifying container names which will
   be used as DNS names on the docker network (`--name bootstrap1`).
3. Deploy `n` other nodes using bootstrap nodes addresses which
   is basically the DNS names but we need the p2p address generated
   on runtime (unless we generate them before running the bootstrap nodes)
