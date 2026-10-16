# Operations

## Updating

```bash
sudo -u unseenet bash -c 'cd ~/unseenet && git pull && .venv/bin/pip install -q -e .'
sudo systemctl restart unseenet-node
```

The onion address does not change on restart or update.

## Operator contact

Give your users a private way to reach you. You need an identity of your
own - your normal one, or a separate "operator" identity - in a client
vault on your own computer.

1. Create a **local inbox** called `operator` on your node, with the
   identity you want to receive messages with. With the command line client:
   ```bash
   unseenet --vault operator.vault id-new operator --display "Node operator"
   unseenet --vault operator.vault node-add <your-node>.onion
   unseenet --vault operator.vault group-create operator --type inbox --local
   unseenet --vault operator.vault whoami          # shows your key
   ```
   `--local` keeps it on this node: messages to you are never replicated.
2. Add an `[operator]` section to `node.toml` with your key and the
   group ID it printed (see [Configuration](configuration.md#operator)),
   and restart the node.
3. Read your messages with `unseenet-tui --vault operator.vault`.

Only your identity can read the messages. The node stores them encrypted,
so not even someone who seizes the node can read them.

## Dropping a group

To stop carrying a group on your node - whoever owns it:

```bash
sudo -u unseenet /home/unseenet/unseenet/.venv/bin/unseenet-node \
  --data /home/unseenet/node-data --drop-group spam.stuff@ab3k5x7qwe2rtz4m
```

The group and its posts are deleted, and the node refuses the group from
then on, also if peers send it again. Your peers are not told: it is your
node's decision only. To allow it again, use `--undrop-group` with the same
group ID. (A group removed by its **owner** is gone for good and cannot be
restored.)

The command works while the node is running.

## Getting your node listed

Clients offer the nodes in the project's list of known nodes
([UN-RFC 0010](../spec/un-rfc-0010.md)) to new users. To be listed, open a
pull request that adds your node to
[`src/unseenet/nodes.json`](https://github.com/andlo/unseenet/blob/main/src/unseenet/nodes.json):

```json
{
  "name": "mynode",
  "address": "xyz...xyz.onion",
  "node_key": "ed25519:...",
  "operator": "ed25519:...",
  "description": "A few words: where, who, what you carry"
}
```

`node_key` is printed when your node starts; `operator` is your own key,
as in `[operator]`. When the pull request is merged, the list is posted to
`unseenet.nodes` automatically, and clients pick it up the next time they
connect. Being listed means more users and more responsibility - read
[Your responsibility](responsibility.md) first.

## Backup

To move or restore a node with the **same onion address**, you need:

- `/home/unseenet/node-data/onion_key.vault` - the onion key, encrypted, and
- the passphrase in `/etc/unseenet-node.env`.

Keep them separately. Without both, a restored node gets a new address
and its peers must be told.

The posts themselves (`articles.sqlite`) are replicated across the
network, so losing them is less serious; a fresh node gets new posts from
its peers.

## Security

### Encrypt the disk

The node's data directory should be on an encrypted disk (e.g. LUKS),
unlocked by you at boot. Then a powered-off machine that is stolen or
seized reveals nothing.

!!! warning "The passphrase file"
    The installer stores the onion key passphrase in `/etc/unseenet-node.env`
    so the node can start unattended. That protects the key if only the data
    directory is copied, but not if the whole disk is. Disk encryption is
    what closes that gap. Alternatively, remove the file and enter the
    passphrase when the node starts.

### What a node can and cannot see

| The node sees | The node never sees |
|---------------|---------------------|
| Open, moderated and channel groups in full | The content of closed groups |
| For closed groups: group ID, number of members, sizes and times of posts, author keys | Group secrets or member keys |
| Which groups a client reads | A client's IP address (Tor hides it) |

### Keep the clock right

Nodes reject posts dated more than an hour in the future. Make sure the
machine's clock is synchronized (NTP; Proxmox containers use the host's
clock).

### Exposure

The node listens on `127.0.0.1:1119` only; Tor forwards onion traffic to
it. Do not change `--listen` to a public interface.

## Resources

- **RAM**: about 300 MB at peak during start (unlocking the onion key uses
  Argon2id), much less afterwards.
- **Disk**: posts are at most 64 KB and text only. A busy group with a
  thousand posts a day uses a few hundred MB over 90 days.
- **Tor log**: `node-data/tor/tor.log`. It grows slowly; rotate or delete
  it now and then.

## Troubleshooting

**`tor failed to start`** - the last lines of Tor's log are shown in the
error. Also look in `node-data/tor/tor.log`. Common causes: the `tor`
package is missing, or the data directory is not writable by the
`unseenet` user.

**No onion address after several minutes** - Tor cannot reach the
network. Check the machine's internet connection and clock. Some networks
block Tor; Tor bridges are not supported by Unseenet yet.

**Peer unreachable** - shown as a warning in the journal. The peer may be
down, or its address may be wrong. Posts stay queued and are delivered
when it comes back.

**`the node answered with key ..., not the configured ...`** - the `key`
you have for that peer is wrong, or the peer has a new node key. Ask its
operator for the key ("Node key:" in their journal).

**`the peer did not accept our key`** - the peer does not have your node
key in its `[[peer]]` section (or has an old one). Send it your key; see
[Peering](peering.md#node-keys).

**`authentication failed`** (password peering) - the peer's `name` and
`password` do not match on both sides.

**A post is rejected** - the client shows why: `postage` (too little
proof-of-work), `permission` (not allowed in that group type), `group`
(the node does not carry that group), `date` (clock problem).
