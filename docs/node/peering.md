# Peering

Peering is how nodes share groups. When your node gets a new post, it
pushes it to each peer whose `groups` pattern matches - the same
store-and-forward model Usenet used.

!!! important "Peering is two-way"
    Both operators add each other: you put the other node's address and
    key in your `node.toml`, and they put yours in theirs. A node only
    pushes to the peers in its own list, and only takes posts pushed by
    peers in its own list.

    | Who lists whom | What happens |
    |---|---|
    | Only you list them | Your pushes are refused ("does it list ed25519:...?" in your log). You can still [pull](#catching-up) from them. |
    | Only they list you | The same, the other way round. |
    | Both | Posts flow both ways. |

## Peering and the list of known nodes

The [list of known nodes](operations.md#getting-your-node-listed) is for
**clients**: it is the nodes a new user is offered. Being on it does not
peer your node with anyone, and you do not need to be on it to peer. Any
two operators can peer by swapping addresses and keys as below, whether
their nodes are listed or not.

## Node keys

Every node has a **node key**, created the first time it starts and kept
encrypted next to the onion key. It is printed when the node starts:

```text
Node key: ed25519:k7m2...  (give it to the operators you peer with)
```

or at any time with

```bash
sudo bash -c 'set -a; . /etc/unseenet-node.env; cd /home/unseenet && \
  sudo -E -u unseenet unseenet/.venv/bin/unseenet-node --data node-data --show-key'
```

Clients also show it under **Details** in "Your nodes" (++o++).

A node key is *public*. You give it to the people you peer with, and they
give you theirs. There is no shared secret: nothing in `node.toml` can
leak and let someone else pretend to be your peer, and there is nothing
to rotate ([UN-RFC 0016](../spec/un-rfc-0016.md)).

## Peering two nodes

Say Alice runs `alice-node` at `aaaa...aaaa.onion` and Bob runs
`bob-node` at `bbbb...bbbb.onion`. They swap onion addresses and node
keys.

On **Alice's** node, `/home/unseenet/node.toml`:

```toml
[[peer]]
name = "bob"                       # your own label for the peer
address = "bbbb...bbbb.onion:119"
key = "ed25519:bob's node key"
```

On **Bob's** node:

```toml
[[peer]]
name = "alice"
address = "aaaa...aaaa.onion:119"
key = "ed25519:alice's node key"
```

Then restart both: `sudo systemctl restart unseenet-node`.

When Alice's node connects to Bob's, it checks that Bob's node answers
with the key Alice configured, and proves that it holds Alice's own key by
signing a fresh challenge. Bob's node accepts the posts only if that key
is one of its peers. The signature is bound to Bob's key, so even a peer
Alice feeds cannot replay it somewhere else.

## What happens

1. A post arrives at Alice's node (from a client or another peer).
2. Alice's node queues it for every peer whose `groups` matches, except the
   peer it came from.
3. After a random delay of up to a minute, it connects to Bob's node over
   Tor, authenticates with its node key, and offers the post (`CHECK`). If
   Bob does not have it, it sends it (`TAKETHIS`).
4. Bob's node checks the post like any other and, if accepted, queues it
   for **its** peers.

In groups whose owner chose **fast delivery** (chat groups,
[UN-RFC 0008](../spec/un-rfc-0008.md)), step 3 has no random delay: the
post is offered to peers at once.

Duplicate posts are recognized by their content-derived ID, so a post
never loops, however the nodes are connected.

Peering is configured **per direction**: Alice decides what she sends to
Bob, and Bob decides what he sends to Alice. Each node also decides, via
[`new_groups`](configuration.md#new_groups-which-groups-the-node-carries),
which new groups it takes.

## Several peers

Add one `[[peer]]` section per peer. Each has its own patterns:

```toml
[[peer]]
name = "bob"
address = "bbbb...bbbb.onion:119"
key = "ed25519:bob's node key"

[[peer]]
name = "aarhus"
address = "dddd...dddd.onion:119"
key = "ed25519:aarhus' node key"
groups = "dk.*,unseenet*"     # send only Danish groups and the project groups
pull = "dk.*,unseenet*"       # and catch up only on those
```

Each of them must have a `[[peer]]` for your node too. A post that
arrives from one peer is passed on to the others, so with several peers
your node also links them.

## Choosing what to share

`groups` decides what **you send** to a peer:

```toml
[[peer]]
name = "bob"
address = "bbbb...bbbb.onion:119"
key = "ed25519:..."
groups = "dk.*,unseenet*"     # only Danish groups and the project groups
```

It does not limit what the peer sends you. Your node takes any post a
peer pushes, in any group it carries or that
[`new_groups`](configuration.md#new_groups-which-groups-the-node-carries)
lets in. If you agree to exchange only some groups, both of you set
`groups` accordingly. (A per-peer limit on what you accept is planned,
[#86](https://github.com/unseenet/unseenet/issues/86).)

## Ending a peering, or a lost key

To stop peering, remove the `[[peer]]` section and restart. Posts already
exchanged stay.

If a node's data directory is lost, so is its node key: the new node gets
a new key, and its peers must update `key`. If you think someone has
copied your data directory *and* your passphrase, create a new node key
(stop the node, delete `node-data/node_key.vault`, start it) and send the
new key to your peers.

## Who may push posts to your node

By default (`require_peer_auth = true`) only configured peers that
authenticate can push posts to your node. Clients can always post. Set it
to `false` only for testing.

## Passwords (old way)

Before node keys, peers shared a password:

```toml
[[peer]]
name = "bob-node"                   # must equal bob's own [node] name
address = "bbbb...bbbb.onion:119"
password = "a-long-shared-secret"
```

It still works, but the node logs a warning: a password sits in clear in
both configs, the same secret is used in both directions, and anyone who
learns it can push posts as that peer. If a `[[peer]]` has a `key`, the
password is ignored. To switch, swap node keys, replace `password` with
`key` on both sides, and restart.

## Watching it

```bash
journalctl -u unseenet-node -f
```

Each accepted post is logged on the receiving node:

```text
unseenet.node accepted <35zjfm6chflhw5y7t6vicpf5d4t6mx2n@unseenet> in unseenet@ph5fc5hop5232qsz
```

A peer that cannot be reached, or whose key does not match, is logged as a
warning and retried every 30 seconds. Queued posts are kept in the
database, so nothing is lost if a peer is down for a while.

## Catching up

Pushing delivers new posts as they arrive. To fill the gaps, a node also
**pulls** from its peers ([UN-RFC 0017](../spec/un-rfc-0017.md)): when
it starts, and every hour, it asks each peer which posts it has received
since last time and fetches the ones it has not seen. The first time, it
asks for everything within its own retention, so a **new node gets the
history** of the groups it carries, and a node that was down gets what
it missed.

Each group's *state* - its manifest, and the keys of closed groups - is
always sent first and never expires, so a new node can check the posts
that follow, also in closed groups.

Choose what to pull per peer:

```toml
[[peer]]
name = "bob"
address = "bbbb...bbbb.onion:119"
key = "ed25519:..."
pull = "*"            # the default; "" pulls nothing, "dk.*" only dk.*
```

Pulling only reads, like any client, so it also works from a node that
does not list you as a peer. A small personal node can carry groups
from public nodes this way without asking anyone. To get your own
users' posts out, you still need a peer that lists your node key.

```toml
[[peer]]                 # read-only: pull from a public node, push nothing
name = "public"
address = "cccc...cccc.onion:119"
key = "ed25519:..."      # optional; checks you reached the right node
groups = ""
```

The journal shows each pull that found something:

```text
unseenet.pulling pulled 42 from bob: 41 accepted, rejected: 1 date
```
