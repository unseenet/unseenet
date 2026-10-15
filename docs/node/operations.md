# Operations

## Updating

```bash
sudo -u unseenet bash -c 'cd ~/unseenet && git pull && .venv/bin/pip install -q -e .'
sudo systemctl restart unseenet-node
```

The onion address does not change on restart or update.

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

**`authentication failed`** - the peer's `name` and `password` do not
match on both sides. See [Peering](peering.md#peering-two-nodes).

**A post is rejected** - the client shows why: `postage` (too little
proof-of-work), `permission` (not allowed in that group type), `group`
(the node does not carry that group), `date` (clock problem).
