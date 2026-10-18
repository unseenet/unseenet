# Gateways to other networks

A gateway connects Unseenet to another network, so groups from there can be
read and answered here, and an Unseenet group can, if its owner wants it,
be read and answered from there. The software lives in its own repository,
[unseenet/gateway](https://github.com/unseenet/gateway), and the rules every
gateway follows are [UN-RFC 0023](spec/un-rfc-0023.md), with one profile per
network.

!!! warning "Pre-alpha, lab only"
    The gateways run against a lab setup. Export to Usenet is not
    implemented yet, and nothing is connected to real Usenet peers.

## Groups from another network

Groups from another network live under a top-level hierarchy named after
that network, so you can always see where a group comes from:

| Network | In Unseenet | Profile | State |
|---------|-------------|---------|-------|
| Usenet | `usenet.*`, e.g. `usenet.comp.misc` | [UN-RFC 0024](spec/un-rfc-0024.md) | import, in the lab |
| Nostr groups (NIP-29) | `nostr.*` | [UN-RFC 0026](spec/un-rfc-0026.md) | import, export and portals, in the lab |
| FidoNet | `fido.*` | - | planned |
| Matrix | `matrix.*` | - | planned ([#116](https://github.com/unseenet/unseenet/issues/116)) |

Each gatewayed group is an ordinary **moderated** group whose moderator is
the gateway, so nodes and clients carry it without knowing anything about
gateways. Every imported post is signed by the gateway and says where it
came from: the network, its ID there, its date and its author there
(`Origin-*` headers). From Nostr the original signed event comes along too,
so a reader can check that the gateway did not change it.

When you answer a gatewayed post from Unseenet, your answer goes to the
gateway as a submission, and the gateway sends it on to the other network
under the gateway's name.

## Unseenet groups on another network: portals

A **portal** goes the other way: an Unseenet group, say `dk.snak`, gets a
counterpart on another network where people can read and write without
Unseenet software. For Nostr that is a NIP-29 group on a relay such as the
project's own `wss://nostr.unseenet.org`.

A portal publishes what Unseenet authors wrote outside Tor, where it may be
kept for years. That is a different promise, so:

- **Only the group's owner can open a portal**, by listing it in the group's
  settings, and a gateway stops when it is removed.
- **You are told.** Before your first post in a group with a portal, the
  client says that it will also be published on the other network, outside
  Tor.
- **Only open groups.** Closed groups, private messages and encrypted posts
  are never published.

## What a gateway never does

A gateway never learns or records who wrote an Unseenet post or where it
came from - the same promise every node makes. It can stop a key; it cannot
identify a person ([UN-RFC 0023](spec/un-rfc-0023.md) section 6.2).

## Running a gateway or writing an adapter

A gateway is a shared core with one **adapter** per network. Usenet and
Nostr are the reference adapters; one for another network can be written
by anyone, in its own package, without changing the gateway. Setup and the
adapter contract are in the
[gateway's README](https://github.com/unseenet/gateway#writing-an-adapter).
A new network also needs a profile UN-RFC and its hierarchy reserved in the
root list ([UN-RFC 0018](spec/un-rfc-0018.md)).
