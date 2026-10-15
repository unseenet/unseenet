# Concepts

A short tour of the ideas behind Unseenet. The precise rules are in the
[specification](spec/index.md).

## Nodes and replication

A **node** is a server that stores posts and passes them on to other nodes
it **peers** with. When a node gets a new post, it offers it to its peers,
which offer it to theirs, until every node that carries the group has it.
This is how Usenet worked.

Every post has an ID that is a hash of its content, so a node can tell
immediately whether it has seen a post before. Unlike Usenet, Unseenet
does not record the route a post took (there is no `Path` header): the
route would reveal where a post entered the network. Nodes also wait a
random time before passing a post on, for the same reason.

## Identities

Your identity is an **Ed25519 key pair**. The public key, written like
`ed25519:det5dxev...`, *is* your identity. The display name you choose is
only a label; anyone can choose any name. The client shows the first
characters of the key's **fingerprint** next to names, e.g.
`Andreas (2byg)`, so you can tell two people with the same name apart.

You can have as many identities as you like. Using a separate identity
per closed group means your posts in different groups cannot be linked.

## Signed posts

Every post is signed by its author. Nodes check the signature and reject
anything that does not match. Nobody - not even a node operator - can
change a post or post in someone else's name.

## Groups

Group names look like `dk.snak@ab3k5x7qwe2rtz4m`: a readable name and the
**fingerprint of the owner's key**. Anyone can create a group called
`dk.snak`, but only one person owns `dk.snak@ab3k5x7qwe2rtz4m`. The client
shows a short form, `dk.snak@ab3k`.

A group's settings live in a signed **manifest** that only the owner can
change. The owner chooses the group's type when creating it:

| Type | Who can read | Who can post | Encrypted |
|------|--------------|--------------|-----------|
| **Open** | anyone | anyone | no |
| **Moderated** | anyone | moderators, or with a moderator's approval | no |
| **Channel** | anyone | the owner and chosen posters | no |
| **Closed** | members only | members only | yes, end to end |
| **Inbox** | the owner only | anyone | yes, sealed to the owner |

A group can also be **local**: it then exists on one node only and is
never replicated. That is used for things like the contact inbox of a
node's operator.

## Closed groups

A closed group has a secret key shared by its members. Posts are
encrypted with it before they leave your computer. The owner hands the
key to new members in **sealed envelopes** that only the recipient can
open.

Nodes still need to keep non-members from flooding the group with
garbage - without being able to read anything. The trick: from the group
secret a second key, the **member key**, is derived. Members sign their
posts with it, and nodes can check that signature without learning the
secret.

When a member is removed, the owner starts a new **epoch** with a new
secret. Removed members keep what they already received - no system can
take that back - but cannot read anything new.

## Inboxes and private messages

An inbox is the opposite of a closed group: anyone can write, only the
owner can read. Each message is sealed to the owner's key, so nodes see
neither the content nor - because the outer message is signed with a key
used only once - who sent it. Inside, the sender can sign with their real
key so the owner knows who wrote.

Every identity has a personal inbox called `inbox@<fingerprint>`, so
knowing someone's key is enough to write to them. Inboxes are also how
you contact a node's operator, and how posts reach the moderators of a
moderated group.

## How long posts travel

A post only travels between nodes while it is younger than the group's
and the node's retention period (90 days by default). After that, nodes
refuse it, so old posts never circulate, however long the network runs.
Archive nodes that keep history longer are being specified in
[UN-RFC 0012](spec/un-rfc-0012.md).

## Postage

Creating identities is free, so posting is priced instead: every post
carries a small **proof-of-work**, roughly a second of CPU time for a
normal computer. A person does not notice; a spammer sending millions of
posts does. Nodes and group owners can raise the price.

## Who decides what

Unseenet splits control between three parties, so that nobody rules alone:

| Party | Decides |
|-------|---------|
| **Group owner** | Group type, who may post, who may read a closed group, moderators |
| **Node operator** | Which groups and peers the node carries, how long posts are kept, minimum postage |
| **Reader** | What they see: which groups they follow (filters to hide people are planned) |

A group owner cannot force a node to carry a group. A node operator
cannot read closed groups, change posts or forge them.
