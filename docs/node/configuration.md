# Configuration reference

The node reads a TOML file, by default `/home/unseenet/node.toml` when
installed with the script. After changing it:

```bash
sudo systemctl restart unseenet-node
```

**Changing what the node carries.** When you change what decides which
posts the node takes from its peers - `new_groups`, `trusted_owners`,
`excludes`, `profiles`, `avatars`, `sites`, `[blobs]` or a peer's
`accept` - the node notices at the next start. It forgets the posts it
refused under the old setting, catches up with its peers again from the
start of retention, and fetches the files of posts it already holds if
it now carries them. The start says so in one line. Nothing is needed by
hand; what the node already has is not fetched twice.

## Example

```toml
[node]
name = "mynode"
min_pow = 18
min_ripe = 0
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
| `min_pow` | `18` | Minimum [postage](https://unseenet.org/guide/journey/#3-paying-the-postage) in bits for posts this node accepts. Each extra bit doubles the cost. Group owners can require more for their groups. |
| `min_ripe` | `0` | The lowest [key ripening](../spec/un-rfc-0025.md) level (0-4) this node accepts, or `"-"` for none. A new key reaches level 0 after a few minutes of computing on its owner's machine, so throwaway keys cost something. Riper keys pay less postage. Needs `chiavdf` (installed with Unseenet on Linux, Windows and Apple Silicon). |
| `retention_days` | `90` | How long posts are kept. A group's own retention is used if it is shorter. Expired posts are removed once an hour. |
| `max_size` | `65536` | Largest post in bytes. Must be between 32768 and 65536. |
| `new_groups` | `"accept"` | Which **new** groups this node carries, see below. |
| `excludes` | `""` | Groups this node does not carry by choice, as a [wildmat](#wildmats), see below. |
| `trusted_owners` | `[]` | Owner keys (`"ed25519:..."`) whose new groups are accepted when `new_groups = "trusted"`. |
| `pull_interval` | `3600` | Seconds between [catch-up pulls](peering.md#catching-up) from each peer. |
| `honour_blocks` | `false` | Refuse posts by identities that a hierarchy's maintainer has blocked (see [below](#honour_blocks-maintainers-blocks)). |
| `profiles` | `"accept"` | Carry identities' public profiles (`profile@...`), see [below](#profiles-and-pictures). `"refuse"` to leave them out. |
| `avatars` | `"refuse"` | Carry identities' pictures (`avatar@...`). Off until you turn it on. |
| `sites` | `"refuse"` | Carry sites: channels shown as pages, kept until their owner changes them ([UN-RFC 0035](../spec/un-rfc-0035.md)). Off until you turn it on. |
| `require_peer_auth` | `true` | Only configured peers that authenticate can push posts to this node. Clients can always post. Set `false` only for testing. |

### Profiles and pictures

An identity can publish a short public profile - a few lines about
itself, the languages it writes, links to other accounts - and a small
picture ([UN-RFC 0022](../spec/un-rfc-0022.md)). Each lives in a tiny
group of its own that follows from the identity's key: `profile@<fp>`
and `avatar@<fp>`. They hold one signed manifest each and no posts.

- **Profiles** are text, at most 8 KiB. Nodes carry them by default,
  also when `new_groups` is `trusted` or `manual`, since they are not
  groups anybody joins. Set `profiles = "refuse"` to leave them out.
- **Pictures** are images (at most 8 KiB, 128 × 128 pixels). No node
  should carry images it has not chosen to, so `avatars` is `"refuse"`
  until you set it to `"accept"`.

Both expire two years after their owner's client last renewed them, and
the node then removes them by itself
([UN-RFC 0029](../spec/un-rfc-0029.md)). Your node information says
what you chose.

### `honour_blocks`: maintainers' blocks

A hierarchy's maintainer (for example whoever runs `dk.*`) can block an
identity in its whole hierarchy, with a public reason
([UN-RFC 0018](../spec/un-rfc-0018.md) section 5.4) - say someone who
posts threats in group after group. With `honour_blocks = true` your node
refuses new posts by blocked identities in the groups under that
hierarchy. Readers' clients hide those posts anyway (they can choose to
see them); this setting decides whether your node carries them at all.

It is off by default: whose blocks you follow is your decision as an
operator. The node reads the blocks from the lists it carries (the
project's root list and the maintainers' lists) and says in its node
information whether it honours them.

### `new_groups`: which groups the node carries

| Value | Behaviour |
|-------|-----------|
| `accept` | Every new group is carried. Good for small private networks among friends. |
| `trusted` | Only groups whose owner key is in `trusted_owners`. Good for a public node where you want to know who creates groups. |
| `manual` | No new groups are accepted. (A tool to add groups by hand is not written yet.) |

This only affects **new** groups. Groups the node already carries keep
working, and posts in them are checked against the group's own rules.

### `excludes`: groups you leave out

```toml
[node]
excludes = "alt.binaries.*,!alt.binaries.test*"
```

Posts and new groups matching `excludes` are refused, from clients and
peers alike. The node tells clients what it leaves out (users see it
under **About this node**), together with every group you have
[dropped](operations.md#dropping-a-group).

A listed node must carry what most listed nodes carry, *except* what it
excludes ([UN-RFC 0021](../spec/un-rfc-0021.md)). `excludes` is how you
stay listed and still leave out something you will not or may not carry
where your node runs. The project's own groups (`unseenet*`) cannot be
excluded by a listed node.

## `[limits]`

```toml
[limits]
max_clients = "auto"      # or a number
```

**`max_clients`**: how many client connections the node keeps open at
once. Through Tor every client looks the same, so a node cannot limit
per visitor; this is a ceiling, so that a misbehaving web entrance or a
script cannot open more than the machine can carry. `"auto"` (the default)
is what memory and open files allow - about 50 KB of memory and two open
files per connection - which is tens of thousands on a small VM. When the
node is full, a new client gets `400 too many connections, try another
node` and tries elsewhere; peers that authenticate are never refused and
do not count. The monitor shows the limit and how many were turned away.
The systemd unit and the Docker Compose file raise the open-files limit
to 65536 for this.

## `[blobs]`

Pictures and small files in posts ([UN-RFC 0027](../spec/un-rfc-0027.md)).
Off unless `enabled = true`; the installer asks
([why](install.md#pictures-and-files)).

```toml
[blobs]
enabled = true
max_size = 1048576          # largest file, 1-4 MiB
retention_days = 30         # files go after this, the post stays
encrypted = false           # also files of closed groups and private posts
groups = "*"                # which groups, a wildmat
daily_per_key = 33554432    # 32 MiB per author key per day
daily_per_group = 268435456 # 256 MiB per group per day
# refusal_keys = ["ed25519:..."]   # follow refusal lists by these keys
# refusal_groups = "*"
```

A file goes when no post on the node references it any more (expired,
withdrawn, edited), or after `retention_days`, except files of pinned
posts. Over a daily limit, your own users get `441 quota`; posts from
peers come in without their files.

**Refusing a file.** `unseenet-node --data ~/node-data --refuse-blob
blob1:... --reason "..."` deletes it, and the node never takes, fetches
or serves it again; the post that references it stays, and readers see
that the file is not available. A running node follows at once.

**Refusal lists.** With `refusal_keys`, the node also refuses the files
named in refusal lists (`application/x-unseenet-blob-refusals`) posted by
those keys in groups matching `refusal_groups`. Nobody can make your node
follow a list; none is followed by default.

The monitor shows how many files the node keeps, how much they take,
today's uploads and how many are refused.

## `[operator]`

Who runs the node and how to reach them ([UN-RFC 0011](../spec/un-rfc-0011.md)).
Clients show it when the user presses ++o++. All keys are optional.

| Key | Meaning |
|-----|---------|
| `key` | Your identity key (`ed25519:...`) as operator |
| `contact` | Group ID of your contact inbox, see [Operations](operations.md#operator-contact) |
| `description` | A few words about the node |
| `logging` | What the node logs (shown to users) |
| `notify` | A command run when the contact inbox gets new messages - see below |

```toml
[operator]
key = "ed25519:det5dxev..."
contact = "operator@ph5fc5hop5232qsz"
description = "Andreas' test node in Denmark"
notify = "/usr/local/bin/tell-me"
```

**Knowing when someone writes.** The node cannot read your contact inbox - that
is the point of it - but it counts the messages. `unseenet-monitor` shows how
many there are and how many are new (++c++ marks them seen once you have read
them in your client), and `unseenet-node status` warns about new ones. With
`notify`, the node runs your command each time new messages arrive: without a
shell, with `UNSEENET_CONTACT_NEW`, `UNSEENET_CONTACT_MESSAGES` and
`UNSEENET_NODE` in its environment and nothing of the messages themselves - so
you can send it on to ntfy, Home Assistant, e-mail or whatever you use:

```sh
#!/bin/sh
curl -s -d "$UNSEENET_CONTACT_NEW new on $UNSEENET_NODE" https://ntfy.sh/your-topic
```

## `[[peer]]`

One section per peer. See [Peering](peering.md).

| Key | Required | Meaning |
|-----|----------|---------|
| `name` | yes | Your label for the peer, used in the logs. (With a password: must equal the `name` in the peer's own `[node]` section.) |
| `address` | yes | The peer's onion address with port, `xyz.onion:119`. (`host:port` works for local testing.) |
| `key` | yes, for new peerings | The peer's node key, `ed25519:...` ([UN-RFC 0016](../spec/un-rfc-0016.md)). Used to accept the peer logging in to you, and to check that you reached the right node. |
| `groups` | no, `"*"` | Which groups to **send** to this peer, as a wildmat (see below). `""` sends nothing. |
| `pull` | no, `"*"` | Which groups to [catch up on](peering.md#catching-up) from this peer. `""` pulls nothing. |
| `accept` | no, `"*"` | Which groups to **take** from this peer, pushed or pulled. Posts in other groups are refused. See [Choosing what to share](peering.md#choosing-what-to-share). |
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
