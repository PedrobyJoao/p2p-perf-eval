import chronos
import stew/results

import libp2p
import libp2p/protocols/pubsub/rpc/messages

type
  Metric = object
    name: string
    value: float

  MetricList = object
    hostname: string
    metrics: seq[Metric]

{.push raises: [].}

proc encode(m: Metric): ProtoBuffer =
  result = initProtoBuffer()
  result.write(1, m.name)
  result.write(2, m.value)
  result.finish()

proc decode(_: type Metric, buf: seq[byte]): Result[Metric, ProtoError] =
  var res: Metric
  let pb = initProtoBuffer(buf)
  discard ?pb.getField(1, res.name)
  discard ?pb.getField(2, res.value)
  ok(res)

proc encode(m: MetricList): ProtoBuffer =
  result = initProtoBuffer()
  for metric in m.metrics:
    result.write(1, metric.encode())
  result.write(2, m.hostname)
  result.finish()

proc decode(_: type MetricList, buf: seq[byte]): Result[MetricList, ProtoError] =
  var
    res: MetricList
    metrics: seq[seq[byte]]
  let pb = initProtoBuffer(buf)
  discard ?pb.getRepeatedField(1, metrics)

  for metric in metrics:
    res.metrics &= ?Metric.decode(metric)
  ?pb.getRequiredField(2, res.hostname)
  ok(res)

## This is exactly like the previous structure, except that we added
## a `hostname` to distinguish where the metric is coming from.
##
## Now we'll create a small GossipSub network to broadcast the metrics,
## and collect them on one of the node.

type Node = tuple[switch: Switch, gossip: GossipSub, hostname: string]

proc oneNode(node: Node, rng: ref HmacDrbgContext) {.async.} =
  # This procedure will handle one of the node of the network
  node.gossip.addValidator(
    ["metrics"],
    proc(topic: string, message: Message): Future[ValidationResult] {.async.} =
      let decoded = MetricList.decode(message.data)
      if decoded.isErr:
        return ValidationResult.Reject
      return ValidationResult.Accept,
  )
  # This "validator" will attach to the `metrics` topic and make sure
  # that every message in this topic is valid. This allows us to stop
  # propagation of invalid messages quickly in the network, and punish
  # peers sending them.

  # `John` will be responsible to log the metrics, the rest of the nodes
  # will just forward them in the network
  if node.hostname == "John":
    node.gossip.subscribe(
      "metrics",
      proc(topic: string, data: seq[byte]) {.async.} =
      let m = MetricList.decode(data).expect("metric can be decoded")
      echo m
    ,
    )
  else:
    node.gossip.subscribe("metrics", nil)

  # Create random metrics 10 times and broadcast them
  for _ in 0 ..< 10:
    await sleepAsync(500.milliseconds)
    var metricList = MetricList(hostname: node.hostname)
    let metricCount = rng[].generate(uint32) mod 4
    for i in 0 ..< metricCount + 1:
      metricList.metrics.add(
        Metric(name: "metric_" & $i, value: float(rng[].generate(uint16)) / 1000.0)
      )

    discard await node.gossip.publish("metrics", encode(metricList).buffer)
  await node.switch.stop()

## For our main procedure, we'll create a few nodes, and connect them together.
## Note that they are not all interconnected, but GossipSub will take care of
## broadcasting to the full network nonetheless.
proc main() {.async.} =
  let rng = newRng()
  var nodes: seq[Node]

  for hostname in ["John", "Walter", "David", "Thuy", "Amy"]:
    let
      switch = newStandardSwitch(rng = rng)
      gossip = GossipSub.init(switch = switch, triggerSelf = true)
    switch.mount(gossip)
    await switch.start()

    nodes.add((switch, gossip, hostname))

  for index, node in nodes:
    # Connect to a few neighbors
    for otherNodeIdx in index - 1 .. index + 2:
      if otherNodeIdx notin 0 ..< nodes.len or otherNodeIdx == index:
        continue
      let otherNode = nodes[otherNodeIdx]
      await node.switch.connect(
        otherNode.switch.peerInfo.peerId, otherNode.switch.peerInfo.addrs
      )

  var allFuts: seq[Future[void]]
  for node in nodes:
    allFuts.add(oneNode(node, rng))

  await allFutures(allFuts)

waitFor(main())
