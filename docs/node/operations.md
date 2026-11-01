# Operations

## Updating

A node installed with `install-node.sh` updates itself
([UN-RFC 0062](../spec/un-rfc-0062.md) section 6.1). Four times a day the timer
`unseenet-update@unseenet-node.timer` looks for the newest stable release and:

- takes it only when the project key has signed its checksums, and installs
  only packages whose hashes the release names;
- never goes to an older version;
- waits a random time of up to 48 hours after it first sees the release, so a
  faulty release reaches a few nodes before it reaches all;
- copies the node's environment first, restarts the node, and checks that it
  stays up and answers within 10 minutes. If it does not, it puts the copy
  back, restarts again, and never tries that version again.

| What | Command |
|---|---|
| What it did | `/home/unseenet/unseenet/.venv/bin/unseenet-service-update status --service unseenet-node` |
| Its log | `journalctl -u unseenet-update@unseenet-node` |
| Update now, without the delay | `sudo /home/unseenet/unseenet/.venv/bin/unseenet-service-update run --service unseenet-node --check tcp:127.0.0.1:1119 --now` |
| Turn it off | `sudo /home/unseenet/unseenet/.venv/bin/unseenet-service-update off --service unseenet-node` |

Turned off, it still looks, and writes a warning in its log when a newer
release has been out for 30 days. To update by hand then:

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

**One team inbox for all your nodes.** Better still with several nodes, or
with several people answering: one replicated **team inbox** (UN-RFC 0047)
that every node names in `contact`. Its owner key can stay offline; the
people who answer read it with a team key each, in their everyday client:
```bash
unseenet --vault operator.vault group-create operator --type inbox       # not --local
unseenet --vault operator.vault team add operator@<fp> <their key> --name "Example (operator)"
unseenet team invitations          # the reader, in their own client
unseenet team accept <message-id>
unseenet team reply operator@<fp> <message-id> "We are looking at it"
```
Answers go out as the team's name, never as the person who wrote them.

**Several nodes.** Run several nodes and you have a local inbox on each, with
the same group ID: create it on each node (`node-add` each, then
`group-create ... --local` once per node, or post the same manifest to all),
and name it in each node's `[operator]`. Add all your nodes to the operator
vault: the client reads the inbox on every node that carries it and shows it
as one, each message once, with the node it came to. No node learns about the
others. Replies go to the sender, as from any inbox.

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
restored.) The network's own groups cannot be dropped; every node carries them
([UN-RFC 0055](../spec/un-rfc-0055.md) section 4).

If the group is **yours** - created by an identity you have - remove it
from the whole network instead, with `unseenet group-remove` or in the
client (see [Leaving and removing groups](https://unseenet.org/client/#leaving-and-removing-groups)).

The command works while the node is running.

## Getting your node listed

Clients offer the nodes in the project's list of known nodes
([UN-RFC 0010](../spec/un-rfc-0010.md)) to new users. To be listed, fill in
the form
**[Add my node](https://github.com/unseenet/unseenet/issues/new?template=add-node.yml)**
on GitHub. You need:

- the node's **onion address** and **node key** - both are printed when
  the node starts (`journalctl -u unseenet-node | grep -E "reachable|Node key"`);
- optionally your **operator key**, as in `[operator]`;
- a short **description** for users.

A check runs at once: it connects to your node over Tor, compares the node
key the node reports with the one in the form, and comments the result on
the issue. Fix what it finds by editing the issue; it checks again.

Because a node key is public, the check also asks you to **prove that you
run the node**: it posts a challenge, which you sign on the node:

```bash
sudo bash -c 'set -a; . /etc/unseenet-node.env; cd /home/unseenet && \
  sudo -E -u unseenet unseenet/.venv/bin/unseenet-node --data node-data --sign "unseenet-node-claim ..."'
```

Paste the `ed25519:...` line it prints as a comment on the issue. Only the node's
passphrase can make that signature. When a maintainer accepts the request,
your node is added to `src/unseenet/nodes.json`, the new list is posted to
`unseenet.nodes`, and clients pick it up the next time they connect.

Being listed does not peer your node with anyone: to share groups with
other nodes, [peer](peering.md) with them yourself. A listed node that
peered with nobody would show its users only its own posts, so the
project requires that a listed node is **connected**
([UN-RFC 0021](../spec/un-rfc-0021.md)):

- **Posts get out and in.** [Peer](peering.md) with at least one listed
  node, and make sure it lists your node key too. The project's own
  nodes peer with anyone who asks to be listed - say so in the request.
- **It carries the groups.** Your node must carry every group that most
  listed nodes carry, except groups you leave out openly with
  [`excludes`](configuration.md#excludes-groups-you-leave-out). The
  project's groups (`unseenet*`) cannot be left out.
- **It holds everyone's inbox and profile.** Inboxes, profiles and
  pictures are *key-bound groups*: there is one or more per person, so
  nodes do not list them, and compare them with each other instead
  ([UN-RFC 0040](../spec/un-rfc-0040.md)). Your node must run a version
  that can (it then advertises `UNSEENET-RECONCILE`), and may lack at
  most 0.1% of the key-bound groups of the listed node that has the most,
  or 100, whichever is more. A node that peers with listed nodes does this
  by itself: it compares with each peer once a day and fetches what it lacks.

When the other checks pass, the request check posts a small **canary**
post to your node and one to a listed node, and waits up to an hour for
each to show up on the other side.

Listed nodes are checked **every day**: reached over Tor, and checked with
a new canary for each node, read on all the others the next day. A canary
counts as having got out when more than half of the listed nodes have it.
The check also compares your node's key-bound groups with those of the
listed node that has the most; a group counts as missing only if it was
missing the day before too, so a node a little behind is not judged.
If your node is not reachable, not connected or misses groups for 3 days,
you get a note on your request saying what is wrong; after 10 days it is
taken off the list. Ask again when it is fixed.

(A pull request that edits `src/unseenet/nodes.json` works too; the daily
check applies all the same.)

Being listed means more users and more responsibility - read
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

### Keep the machine quiet

If you run your node to keep its location hidden, don't run anything on
the same machine that announces the machine to the world. The onion
service hides the node's address, but a public service beside it can
undo that: if its uptime, hardware or address can be seen, someone can
compare it with when the node is reachable.

Avoid on the node's machine:

- a Tor relay (it is listed publicly in the consensus with its uptime)
- volunteer computing such as BOINC or Folding@home (projects publish
  host lists with hardware and when each host was last seen, and the
  account is tied to an email address)
- public web servers, status pages, dynamic DNS or monitoring that
  reports to a public dashboard

This holds over Tor too: hiding the IP address does not hide a public
record of when the machine is online. Run such things on a different
machine. If your node is a public backbone node whose operator is
known, this does not matter.

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
