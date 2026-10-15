# Peering

Peering is how nodes share groups. When your node gets a new post, it
pushes it to each peer whose `groups` pattern matches - the same
store-and-forward model Usenet used.

## Peering two nodes

Say Alice runs `alice-node` at `aaaa...aaaa.onion` and Bob runs
`bob-node` at `bbbb...bbbb.onion`. They agree on a shared password.

On **Alice's** node, `/home/unseenet/node.toml`:

```toml
[node]
name = "alice-node"

[[peer]]
name = "bob-node"
address = "bbbb...bbbb.onion:119"
password = "a-long-shared-secret"
```

On **Bob's** node:

```toml
[node]
name = "bob-node"

[[peer]]
name = "alice-node"
address = "aaaa...aaaa.onion:119"
password = "a-long-shared-secret"
```

Then restart both: `sudo systemctl restart unseenet-node`.

!!! important "Names must match"
    When Alice's node logs in to Bob's, it uses its own `[node] name`
    (`alice-node`) and the password. Bob's node looks for a peer **with
    that name** and checks the password. If the names do not match, the
    login fails.

## What happens

1. A post arrives at Alice's node (from a client or another peer).
2. Alice's node queues it for every peer whose `groups` matches, except the
   peer it came from.
3. After a random delay of up to a minute, it connects to Bob's node over
   Tor and offers the post (`CHECK`). If Bob does not have it, it sends it
   (`TAKETHIS`).
4. Bob's node checks the post like any other and, if accepted, queues it
   for **its** peers.

Duplicate posts are recognized by their content-derived ID, so a post
never loops, however the nodes are connected.

Peering is configured **per direction**: Alice decides what she sends to
Bob, and Bob decides what he sends to Alice. Each node also decides, via
[`new_groups`](configuration.md#new_groups-which-groups-the-node-carries),
which new groups it takes.

## Choosing what to share

```toml
[[peer]]
name = "bob-node"
address = "bbbb...bbbb.onion:119"
groups = "dk.*,unseenet*"     # only Danish groups and the project groups
```

## Without a password

If `password` is left out, the node pushes to the peer without logging
in. The receiving node accepts that unless it has
`require_peer_auth = true`. That is fine for testing; for anything else,
use a password, so that only your peers can push posts into your node and
the receiving node knows which peer a post came from.

## Watching it

```bash
journalctl -u unseenet-node -f
```

Each accepted post is logged on the receiving node:

```text
unseenet.node accepted <35zjfm6chflhw5y7t6vicpf5d4t6mx2n@unseenet> in unseenet@ph5fc5hop5232qsz
```

A peer that cannot be reached is logged as a warning and retried every
30 seconds. Queued posts are kept in the database, so nothing is lost if
a peer is down for a while.

!!! note "Catching up"
    Today, nodes only *push* new posts. A node that was offline gets what
    its peers queued for it, but it does not yet *pull* older posts it
    never saw. Pull-based catch-up (`NEWNEWS`) is planned.
