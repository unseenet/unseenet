# Configuration reference

The node reads a TOML file, by default `/home/unseenet/node.toml` when
installed with the script. After changing it:

```bash
sudo systemctl restart unseenet-node
```

## Example

```toml
[node]
name = "mynode"
min_pow = 18
retention_days = 90
new_groups = "accept"
trusted_owners = []
require_peer_auth = true

[[peer]]
name = "friend"
address = "abcdef...xyz.onion:119"
key = "ed25519:..."
groups = "*"
```

## `[node]`

| Key | Default | Meaning |
|-----|---------|---------|
| `name` | `"unseenet"` (the installer uses the hostname) | The node's name, shown to clients. With old password peering it is also the user name, so it must match the `name` the other side has for you. |
| `min_pow` | `18` | Minimum [postage](../concepts.md#postage) in bits for posts this node accepts. Each extra bit doubles the cost. Group owners can require more for their groups. |
| `retention_days` | `90` | How long posts are kept. A group's own retention is used if it is shorter. Expired posts are removed once an hour. |
| `max_size` | `65536` | Largest post in bytes. Must be between 32768 and 65536. |
| `new_groups` | `"accept"` | Which **new** groups this node carries, see below. |
| `trusted_owners` | `[]` | Owner keys (`"ed25519:..."`) whose new groups are accepted when `new_groups = "trusted"`. |
| `require_peer_auth` | `true` | Only configured peers that authenticate can push posts to this node. Clients can always post. Set `false` only for testing. |

### `new_groups`: which groups the node carries

| Value | Behaviour |
|-------|-----------|
| `accept` | Every new group is carried. Good for small private networks among friends. |
| `trusted` | Only groups whose owner key is in `trusted_owners`. Good for a public node where you want to know who creates groups. |
| `manual` | No new groups are accepted. (A tool to add groups by hand is not written yet.) |

This only affects **new** groups. Groups the node already carries keep
working, and posts in them are checked against the group's own rules.

## `[operator]`

Who runs the node and how to reach them ([UN-RFC 0011](../spec/un-rfc-0011.md)).
Clients show it when the user presses ++o++. All keys are optional.

| Key | Meaning |
|-----|---------|
| `key` | Your identity key (`ed25519:...`) as operator |
| `contact` | Group ID of your contact inbox, see [Operations](operations.md#operator-contact) |
| `description` | A few words about the node |
| `logging` | What the node logs (shown to users) |

```toml
[operator]
key = "ed25519:det5dxev..."
contact = "operator@ph5fc5hop5232qsz"
description = "Andreas' test node in Denmark"
```

## `[[peer]]`

One section per peer. See [Peering](peering.md).

| Key | Required | Meaning |
|-----|----------|---------|
| `name` | yes | Your label for the peer, used in the logs. (With a password: must equal the `name` in the peer's own `[node]` section.) |
| `address` | yes | The peer's onion address with port, `xyz.onion:119`. (`host:port` works for local testing.) |
| `key` | yes, for new peerings | The peer's node key, `ed25519:...` ([UN-RFC 0016](../spec/un-rfc-0016.md)). Used to accept the peer logging in to you, and to check that you reached the right node. |
| `groups` | no, `"*"` | Which groups to **send** to this peer, as a wildmat (see below). |
| `password` | no | Old shared-secret login, ignored when `key` is set. See [Peering](peering.md#passwords-old-way). |

### Wildmats

Group selections use the classic Usenet *wildmat* syntax: comma-separated
patterns with `*` and `?`, where `!` excludes. The last matching pattern
wins.

| Pattern | Sends |
|---------|-------|
| `*` | everything |
| `dk.*,unseenet*` | groups starting with `dk.` or `unseenet` |
| `*,!alt.*` | everything except `alt.*` |

Patterns are matched against the full group ID (`dk.snak@ab3k5x7q...`),
so `dk.snak*` matches every `dk.snak`, whoever owns it. To match one
specific group, use its full ID.
