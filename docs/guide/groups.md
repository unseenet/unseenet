# Groups

Everything on Unseenet happens in a group: a discussion, a chat, a feed,
a site, even your inbox. This chapter is about what a group is, who
decides what in it, and how one group can look like Usenet while another
looks like Facebook - on exactly the same technique underneath.

<!-- unseenet:diagram groups -->

## What a group is

A group is a name, an owner and a set of articles.

Its full name, the **Group ID**, looks like `dk.snak@ab3k5x7qwe2rtz4m`:
the readable name, then the fingerprint of the key that created it.
Anyone may create a group called `dk.snak`, but only one key created
this one, so two groups can never be mixed up, and nobody can sneak
posts into someone else's group by giving theirs the same name. Clients
show the short form, `dk.snak@ab3k`, or just `dk.snak` when there is no
doubt which one is meant.

The group's settings are in its **manifest**: a signed article that only
the owner can write. It says what kind of group it is, who may post, who
the moderators are, what the rules are and how the group should be
shown. When the owner changes something, they post a new manifest with a
higher number, and every node and client takes the newest one. Because
it is signed, every reader on every node sees the same settings, and no
node can fake them.

Everything else in the group is ordinary articles - posts, chat lines,
pages, comments - each signed by whoever wrote it.

## Names and hierarchies

As on Usenet, the first part of a group name is its **hierarchy**:
`dk.snak` lies in `dk`, `alt.robot.cafe` in `alt`. Hierarchies make
groups easy to find, and they are where a community can look after its
corner of the network.

Most hierarchies are free: anyone may create anything in `alt.*`, and
country hierarchies such as `dk.*` are open to everyone until a
community there asks to look after it. A hierarchy can have a
**maintainer**, who says which group a name means - so that
`unseenet.announce` is the project's own group, and another group by
that name is shown with its fingerprint and a warning. A maintainer can
also block an identity across the hierarchy, on the nodes that choose to
honour such blocks. A maintainer cannot post in, change or remove anyone
else's group.

| Hierarchy | Who decides the names |
|-----------|-----------------------|
| `unseenet` | the project |
| `alt`, `test` | nobody: anyone can create anything |
| `dk`, `de`, `se`, ... (country codes) | nobody, until a community there asks for a maintainer |
| `comp`, `sci`, `rec`, ... (the Usenet "Big 8") | held back for communities that want to revive them |
| `usenet`, `matrix`, `nostr`, ... | held back for groups that come through gateways from other networks |
| anything else | nobody, until someone asks for it |

A new hierarchy is asked for with the
[hierarchy request form](https://github.com/unseenet/unseenet/issues/new?template=hierarchy-request.yml),
or by writing to the project's inbox on Unseenet.

## Who may write: the type

The owner chooses the group's **type** when creating it. The type
decides who may read and who may write:

| Type | Read | Write | Like |
|------|------|-------|------|
| **Open** | anyone | anyone | a Usenet group, a forum, a Facebook group |
| **Moderated** | anyone | moderators, or with their approval | a moderated newsgroup |
| **Channel** | anyone | the owner and chosen posters - and, if the owner opens it, anyone may comment | a news site, a blog, an announcement list |
| **Closed** | members | members | a private group chat or forum |
| **Inbox** | the owner | anyone | a mailbox |

The nodes enforce this. A post from someone who may not write in a
group is refused by every node, not just hidden by a polite client.

## How it looks: the view

Separately from the type, the owner says how the group should be
**shown**:

| View | Shown as |
|------|----------|
| **threads** | a thread tree, read one post at a time, replies quoting what they answer |
| **chat** | a running conversation, newest at the bottom |
| **feed** | posts newest first, with the comments under each *(from 0.5.0)* |
| **pages** | a small site of Markdown pages *(channels only, from 0.5.0)* |
| **data** | not shown to people at all - lists and certificates clients read in the background |

The view is a hint, not a rule: a reader may switch a feed to threads or
a chat to threads, and a client that does not know a view shows threads.
Nodes do not care about the view at all - to a node, a feed and a
discussion are the same articles.

Putting a type and a view together gives the shapes people know:

| What you want | Type | View |
|---------------|------|------|
| A Usenet-style discussion | open | threads |
| A Discord-style chat | open, or closed | chat |
| A Facebook group | open | feed |
| A news site or blog with comments | channel, comments open | feed |
| A personal feed, like Mastodon or X | your own channel, `feed@<fingerprint>` | feed |
| A personal home page | your own channel, `site@<fingerprint>` | pages |
| Announcements nobody replies to | channel | threads |

### Chats and posts

Inside a group, every message is one of two **kinds**: a **chat** line,
with no subject, written to keep a conversation going; or a **post**,
with a subject, meant to be read on its own and answered with a quote.
The owner decides which kinds a group takes - chat only, posts only, or
both - and the client only offers what the group takes. So in a
discussion group you cannot accidentally fire off chat lines, and in a
chat group you are not asked for a subject.

Chat groups can also ask nodes to pass messages on at once, without the
random delay that otherwise hides where a post entered the network.
That is what makes chat feel like chat, and it is a real trade-off: the
client shows when a group has made it.

### Reactions

Under any post, comment or chat line, a reader can leave a **reaction**:
one emoji, such as 👍, instead of writing "+1". A reaction is a tiny
signed message of its own, so it costs a little postage and travels like
everything else, but clients never show it as a comment - only as a
count under what it answers. Each key has at most one reaction on a
post; choosing another emoji changes it, choosing the same one takes it
back.

The owner decides which emoji a group takes, or none, or any. Feeds and
chats take 👍 👎 ❤️ 😂 😮 😢 unless the owner says otherwise; discussion
groups take none unless the owner turns them on. Nodes refuse reactions
the group does not take.

Two things are worth knowing. Reactions are **public**: anyone can see
which key reacted to what, as with a comment. And they are **only
counted, never used**: no client sorts or hides posts by how many
reactions they have, so a bought pile of likes buys nothing but a
number. *(From 0.5.0.)*

## Closed groups

A closed group is encrypted end to end. Its members share a secret key,
and every post is encrypted with it on the writer's own computer before
it leaves. Nodes carry the posts but see only scrambled data.

That raises a puzzle: if nodes cannot read anything, how do they stop
outsiders flooding the group with garbage? The answer is a second key,
the **member key**, derived from the group secret. Members sign their
posts with it as well, and nodes can check that signature without
learning the secret.

The owner hands the secret to new members sealed to their own keys.
When someone is removed, the owner starts a new **epoch** with a new
secret. The removed member keeps what they already had - no system can
take back what someone has read - but cannot read anything new.

## Inboxes

An inbox is the opposite of a closed group: anyone can write, only the
owner can read. Every identity has a personal one, `inbox@<fingerprint>`,
so knowing someone's key is enough to write to them privately. Each
message is sealed to the owner's key, and the outside of it is signed
with a key used only once, so nodes see neither what it says nor who
sent it. Inside, the sender signs with their real key, so the owner knows
who wrote.

Inboxes are also how you reach a node's operator, and how posts reach the
moderators of a moderated group.

A group can also be **local**: it then exists on one node only and is
never passed on - used for things like a node operator's contact inbox.

## Rules, pins and how long things last

- **Rules.** The owner can write the group's purpose and rules - its
  charter - into the manifest. Every client shows them before a reader
  first posts, and because they are signed, they are the same for
  everyone.
- **Retention.** Posts are kept for a period the owner suggests, 90 days
  by default, and a node may keep them shorter. After that the network
  forgets them.
- **Pins.** The owner and moderators can pin a few posts - a welcome
  message, a FAQ - which then stay beyond the retention period and show
  at the top, in the threads view and in the chat view. *(From 0.5.0.)*

## Moderation

Moderation on Unseenet is local by design. Each group is looked after by
its own owner and moderators, who can:

- **withdraw** any post in the group - nodes delete it and stop passing
  it on, as best they can;
- **ban** identities from posting in the group;
- for a moderated group, **approve** posts before they appear;
- for a channel, **open or close comments**, and close them on a thread
  some days after it was posted.

Their power stops at the edge of their group. Above them, a hierarchy
maintainer can block an identity across a hierarchy on nodes that honour
it, and a node operator decides what their own node carries. And every
reader decides which groups they follow at all. The chapter
[Why it matters](why.md#what-nobody-controls-it-means-precisely) has the
whole picture.

## A group's life

- **Creating** a group is publishing its first manifest. Nodes may ask
  more postage for it than for an ordinary post, so that nobody fills
  the network with empty groups.
- **Handing it over.** An owner can offer the group to another key, which
  accepts by signing the offer. The Group ID stays the same, so links and
  subscriptions keep working; the fingerprint in it names the founder,
  not the current owner. *(Specified, not built yet.)*
- **Removing** it. The owner can remove a group from the whole network
  with a signed `rmgroup`. Nodes delete it and keep a **tombstone**, so
  that it cannot come back through replication. A node operator can also
  drop a group from their own node only.
- **Groups that belong to a key** - your inbox, your profile, your feed
  and site - live as long as the key is used: the client renews them
  while it runs, and they disappear by themselves at most two years after
  it stops.

**Details:**
[UN-RFC 0004](../spec/un-rfc-0004.md) (groups, manifests, types, bans, withdrawing),
[0008](../spec/un-rfc-0008.md) (chat, views, data groups),
[0009](../spec/un-rfc-0009.md) (inboxes),
[0013](../spec/un-rfc-0013.md) (removing groups),
[0014](../spec/un-rfc-0014.md) (rules),
[0015](../spec/un-rfc-0015.md) (handing over),
[0018](../spec/un-rfc-0018.md) (hierarchies),
[0028](../spec/un-rfc-0028.md) (chats and posts),
[0029](../spec/un-rfc-0029.md) (key-bound groups),
[0030](../spec/un-rfc-0030.md) (comments in channels),
[0033](../spec/un-rfc-0033.md) (pins),
[0034](../spec/un-rfc-0034.md) (feeds),
[0035](../spec/un-rfc-0035.md) (pages and sites),
[0048](../spec/un-rfc-0048.md) (reactions).
