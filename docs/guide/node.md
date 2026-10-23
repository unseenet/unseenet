# The node

Nodes are the network. There is no central server behind them, no
company running the "real" one, and no node more important than the
others - only many small servers that store groups and pass articles
between each other, the way Usenet servers always did. This chapter is
about what a node does, how nodes find and trust each other, and what
the person running one can and cannot see.

## What a node is

A node is one program, `unseenet-node`, with Tor beside it. It is small:
half a gigabyte of memory, one CPU core and a few gigabytes of disk are
plenty, so a Raspberry Pi, an old laptop, a free cloud VM or a container
in a homelab will do. On Debian or Ubuntu it is one install command;
there is also a Docker image.

Every node is a Tor **onion service**. That is what makes running one
easy and safe:

- **No public address.** The node needs no public IP, no open port in the
  router, no domain name and no certificate. It connects *out* to Tor,
  and is reached through Tor. It works behind any home router.
- **No location.** Its `.onion` address says nothing about where it
  stands, which country it is in or who runs it. Nobody can look it up.
- **No visitors' addresses.** Clients and other nodes reach it through
  Tor, so the node never learns where they are either.

For the same reason a node should run *nothing* beside it that is visible
on the open internet - no public web server, no Tor relay, no service
that reports when it is up. Anything whose uptime can be watched in
public could be matched with when the hidden node is up, and give away
where it is.

## What a node does all day

- **It accepts posts from clients** and checks every one: signature,
  postage, the group's rules, age. It does not trust anybody, including
  its own users.
- **It passes posts on to its peers** - after a random delay, without
  recording where they came from - and takes theirs.
- **It serves readers**, who ask what is new in the groups they follow.
- **It forgets.** Posts travel and are kept only for the group's
  retention period, 90 days by default, so the node's disk does not grow
  for ever and old traffic never circulates.
- **It keeps each group's state** regardless of age: the current
  manifest, the keys of closed groups, pinned posts, the current pages of
  a site. Without those, nothing newer in the group could be checked.

[A post's journey](journey.md) follows one post through all of this.

## Peering

Two nodes **peer** when their operators agree to exchange posts. Each
gives the other the onion address and the public **node key** of their
own node; nothing secret is exchanged. When the nodes connect, each
proves it holds its node key by signing a fresh challenge from the other,
bound to both keys so it cannot be replayed. Only peers can push posts
into a node.

Peering is set **per direction and per group**: Alice decides which
groups she sends to Bob, and Bob decides what he sends to Alice, with
patterns such as `dk.*, alt.*`. A node with several peers passes a post
on to all of them except the one it came from, and because a post's ID
comes from its content, a post never loops however the nodes are
connected.

A node that was switched off, or is new, **catches up** by asking its
peers what is new and fetching what it missed - first each group's state,
then the posts that depend on it. So a sleeping node loses nothing, and a
new node gets whole groups, not just what arrives after it starts.

## Finding the network

A new client has to start somewhere. It ships with a **node list**: a
small, signed list of nodes, published as posts in a channel. Once
connected, the client reads the newest list from the network itself,
signed by a publisher it trusts. It is a starting point, not a directory:
any node can be used, and anyone can publish a list.

To be on the project's list, a node must really be part of the network.
It must exchange posts with the other listed nodes in both directions,
and carry the groups they carry - except groups it openly says it leaves
out. That is checked from outside with small daily "canary" posts, so a
new user is never sent to a node that is an island.

Each node also publishes **node information**: who operates it, its
policies - which groups it takes, whether it carries files, whether it
honours maintainers' blocks - and an **operator inbox**, where anyone can
write to the operator privately, for example to report a post.

## What the operator decides

Running a node means carrying posts written by other people. The
operator has real choices about that, all of them about their own node
only:

- **Which new groups to take**: every new group (`accept`, fine among
  friends), only groups created by owners the operator trusts
  (`trusted`), or none without asking (`manual`).
- **Which groups to leave out**, and say so publicly.
- **Which groups to send to each peer.**
- **How long to keep posts**, within the group's own retention.
- **How much postage to ask** - more makes spam dearer.
- **Whether to honour maintainers' blocks** across a hierarchy.
- **Whether to carry files and sites** *(from 0.5.0)*. Pictures and
  other small files are stored as separate **blobs** next to the posts
  that use them; sites keep their pages beyond the retention period.
  Both take disk and both mean hosting more of other people's content,
  so both are off unless the operator turns them on. The installer asks.
- **To drop a group** from the node altogether. The node deletes it and
  refuses it from then on. That affects only this node; the same group
  lives on at the others.

What an operator cannot do is just as important: they cannot change a
post, post in someone else's name, read a closed group or a private post,
or remove anything from any node but their own.

## What an operator can and cannot see

| The operator's node sees | It never sees |
|--------------------------|---------------|
| Open, moderated and channel groups in full - they are public | The content of closed groups and private posts |
| For closed groups: that the group exists, roughly how many members, the sizes and times of posts | Group secrets, or the key of whoever wrote to an inbox |
| Which groups a connected client reads | The client's IP address, or who the client is |
| Which peer a post came from | Whether that peer is where the post was written |

A node logs as little as it can, and never which client read what. An
operator should keep it that way.

## Keeping a node safe

What a node holds is mostly public anyway, but its keys and its location
are worth protecting:

- **Encrypt the disk**, and unlock it by hand at boot, so a machine
  seized while it is off reveals nothing.
- **Keep the onion key encrypted**, and hand it to Tor only while the
  node runs, so Tor never writes it to its own directory.
- **Keep the clock right** - posts are checked against their date.
- **Run nothing public beside it**, as above.
- **Back up the node key and the onion key.** Without them, peers and the
  node list no longer recognise the node.

A node seized while running gives away what it carries - which is the
public groups, and the encrypted rest. It never holds anyone's private
key or closed group secret, because nodes never get them.

## Archives

An ordinary node forgets posts after the retention period. An **archive
node** may keep them much longer and serve them to readers, and owners
and authors can ask archives not to keep their posts. Archives are
specified but not built yet.

**Details:**
[UN-RFC 0005](../spec/un-rfc-0005.md) (ONNTP, feeds, the random delay),
[0007](../spec/un-rfc-0007.md) (data at rest),
[0010](../spec/un-rfc-0010.md) (node lists),
[0011](../spec/un-rfc-0011.md) (node information),
[0012](../spec/un-rfc-0012.md) (retention and archives),
[0013](../spec/un-rfc-0013.md) (dropping groups),
[0016](../spec/un-rfc-0016.md) (peer keys),
[0017](../spec/un-rfc-0017.md) (catching up, group state),
[0021](../spec/un-rfc-0021.md) (listed nodes must be connected),
[0027](../spec/un-rfc-0027.md) (attachments and blobs),
[0035](../spec/un-rfc-0035.md) (sites).
For running one: [Installation](../node/install.md),
[Peering](../node/peering.md) and
[Your responsibility](../node/responsibility.md).
