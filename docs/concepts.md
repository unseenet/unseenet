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
`Andreas~2byg`, so you can tell two people with the same name apart.

You can have as many identities as you like. Using a separate identity
per closed group means your posts in different groups cannot be linked.

## Names for identities

A key is hard to remember, so an identity can also have a **name**
([UN-RFC 0019](spec/un-rfc-0019.md)). A client shows the first of these
that applies:

| Shown as | What it is |
|----------|------------|
| your own name for them | A **petname** you gave the key yourself. It never leaves your computer, and it always wins. |
| `@lorensen.dk` | A **domain name**, proven by a DNS record on the domain. Only the domain's owner can get it. |
| `sonia@lorensen`, `andlo@lorensen.dk` | A **name under a name**: given by whoever holds `@lorensen`, or by the domain `lorensen.dk` in DNS - like an e-mail address. |
| `@lorensen` | A **registered name**, given out first come, first served by a registrar. Names that are Internet top-level domains, like `microsoft` or `dk`, cannot be registered. |
| `Andreas~2byg` | Everyone else: the display name they chose, and the first characters of the fingerprint. |

A registrar gives out names as signed certificates that the identity
sends along with its posts, so the client can check a name without asking
anybody. Names are optional: an identity without one can do everything
an identity with one can, and a name links everything its identity
posts, so do not give one to an identity you keep apart.

You claim a name in the client with `@` (see [Using the client](client.md#names)).

## Signed posts

Every post is signed by its author. Nodes check the signature and reject
anything that does not match. Nobody - not even a node operator - can
change a post or post in someone else's name.

## Groups

Group names look like `dk.snak@ab3k5x7qwe2rtz4m`: a readable name and the
**fingerprint of the owner's key**. Anyone can create a group called
`dk.snak`, but only one person owns `dk.snak@ab3k5x7qwe2rtz4m`. The client
shows a short form, `dk.snak@ab3k`.

### Hierarchies

The first part of a group name is its **hierarchy**, as on Usenet:
`dk.snak` is in `dk`. Because anyone can create a group with any name, a
hierarchy can have a **maintainer** who says which group each name in it
means ([UN-RFC 0018](spec/un-rfc-0018.md)): the project's maintainer
says that `unseenet.announce` is `unseenet.announce@ph5f`, and the client
then shows other groups by that name with their fingerprint and a
warning.

| Hierarchy | Who decides the names |
|-----------|-----------------------|
| `unseenet` | The project |
| `alt`, `test` | Nobody: anyone can create anything |
| `dk`, `de`, `se`, ... (country codes) | Nobody, until a community there asks for a maintainer |
| `comp`, `sci`, `rec`, ... (the Usenet Big 8) | Held back for communities that want to revive them |
| anything else | Nobody, until someone asks for it |

A maintainer cannot post in, change or remove a group; it only says
which group a name means. A new hierarchy is requested with the
[hierarchy request form](https://github.com/unseenet/unseenet/issues/new?template=hierarchy-request.yml),
or by writing to the project's inbox on Unseenet.

### Manifests

A group's settings live in a signed **manifest** that only the owner can
change. The owner chooses the group's type when creating it:

| Type | Who can read | Who can post | Encrypted |
|------|--------------|--------------|-----------|
| **Open** | anyone | anyone | no |
| **Moderated** | anyone | moderators, or with a moderator's approval | no |
| **Channel** | anyone | the owner and chosen posters; readers may comment if the owner allows it | no |
| **Closed** | members only | members only | yes, end to end |
| **Inbox** | the owner only | anyone | yes, sealed to the owner |

A channel's owner can open it for **comments** (UN-RFC 0030): then anyone
may reply to a post, but only the owner and posters start new threads -
like a news site or a blog with comments. The owner can also close
comments on a thread a number of days after it was posted.

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

## Rules and chat groups

A group's settings - signed by its owner - can also carry its **rules**
(the charter), a hint that it is a **chat** rather than a discussion, and
**fast delivery**: nodes then forward its messages without the random
delay that otherwise hides where a message entered the network.
See [UN-RFC 0008](spec/un-rfc-0008.md) and [UN-RFC 0014](spec/un-rfc-0014.md).

Some groups are not for people at all: they carry lists and certificates
that clients read in the background, such as the list of known nodes and
the names of identities. They are **data groups** (`¤` in the client),
and the client leaves them out when you browse for groups to join.

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
| **Hierarchy maintainer** | Which group a name in its hierarchy means - not what is in the group |
| **Reader** | What they see: which groups they follow (filters to hide people are planned) |

A group owner cannot force a node to carry a group. A node operator
cannot read closed groups, change posts or forge them.
