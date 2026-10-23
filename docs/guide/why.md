# Why it matters

Before the technology, the reason for it. This chapter is about privacy,
about freedom, and about why it is worth having the ways of talking we
already know - discussion groups, chat, feeds, personal pages - without
anyone in charge of them.

## Where our conversations went

Thirty years ago a lot of the internet's conversation happened on Usenet
and on bulletin board systems. Nobody owned Usenet. Thousands of servers,
run by universities, companies and enthusiasts, passed posts between each
other, and you read them from whichever server you had access to.

Today the same conversations happen in a handful of places, and each of
them gave us something real:

- **Forums and Reddit** kept threaded discussion alive.
- **Discord and Matrix** made group chat easy.
- **Facebook, X and Mastodon** made the feed - one person posts, everyone
  else comments underneath - the way most people read online.
- **Personal web pages and blogs** gave people a place to say who they are.

But almost all of them came with an owner. Even the decentralised ones
still have servers at known addresses, run by someone who can be found,
and accounts that belong to one of those servers.

## What an owner can do

Whoever owns the place where people talk can, in some combination:

- **decide who may speak** - close an account, and with it every group the
  person was in, everywhere at once;
- **remove what was said**, or quietly make it harder to find;
- **decide what you see**, by sorting the feed for whatever keeps you
  scrolling, rather than in the order things were written;
- **read along**, and keep a record of who talked to whom, when and from
  where;
- **demand to know who you are** - an email address, a phone number, an ID;
- **hand all of that over** when a court, a government or a buyer of the
  company asks for it - or lose it in a leak;
- **close the whole thing down**, or be pressured into doing so.

Most owners use these powers reasonably most of the time. The problem is
not that every owner is bad. The problem is that the power exists at all,
in one place, where it can be used, abused, bought, demanded or stolen.

## Privacy is not about having something to hide

"I have nothing to hide" is true for most people about most things. But
privacy is not mainly about secrets. It is about being able to think out
loud, ask a stupid question, join a group about an illness, a belief or a
union, or disagree with your employer or your government - without that
becoming a permanent record that someone else controls.

What gives people away is rarely the content of one post. It is the
pattern: who talks to whom, how often, from where and at what time. That
pattern says more than most messages do, and it is exactly what a
platform collects as a side effect of running.

People behave differently when they know they are watched. The ones who
lose most are those who most need to be heard: whistleblowers, journalists
and their sources, minorities, people in countries where criticising
those in power is punished - and, sooner or later, ordinary people whose
circumstances change.

## Why freedom needs alternatives without control

Freedom of speech has always depended on there being more than one
printing press. When most conversation runs through a few companies, a
few decisions - theirs, or those forced on them - decide what can be said
and heard.

An alternative without an owner is not about being lawless. The law still
applies to what people say and do. It is about there being **no single
switch**: nobody who can turn the network off, nobody who can make a
person disappear from all of it, nobody who can be ordered to hand over a
list of who said what - because no such switch or list exists.

Usenet showed for decades that a network of independent servers can carry
the world's conversation. Unseenet takes that model and adds what has been
learned since: signatures, so nobody can post in your name; encryption, so
private things stay private; and Tor, so nobody can tell who is talking or
where the servers are.

## The shapes you know, without the owner

Unseenet does not ask anyone to learn a new way of talking. It offers the
familiar ones:

| You know it from | On Unseenet | Available |
|------------------|-------------|-----------|
| Usenet, forums, Reddit | **Discussion groups**: threads, one post at a time, reply by quoting | now |
| Discord, Matrix, IRC | **Chat groups**: quick lines that keep the conversation going | now |
| Facebook, X, Mastodon | **Feeds** and a **timeline** of the people and feeds you follow | from 0.5.0 |
| Personal pages, blogs, wikis | **Sites**: small sets of Markdown pages, with pictures | from 0.5.0 |
| Direct messages, e-mail | **Private chats and private posts**, end-to-end encrypted | now |
| A contact form, "write to the admin" | **Inboxes**: anyone may write, only the owner reads | now |

What is missing compared with the platforms is the owner: nobody holds
your account, nobody reads along, nobody sorts what you see, and nobody
can switch it off.

## One foundation for all of it

These look like different things, but underneath they are the same thing,
which is one of the most important ideas in Unseenet.

Everything is an **article**: a short text with some headers, signed by
the key of whoever wrote it, in a **group**. Nodes store articles and pass
them to each other. That is all a node really does - and it does it the
same way whatever the article is:

- A **post** is an article with a subject, shown in a thread.
- A **chat line** is an article without a subject. In a chat group nodes
  pass it on at once instead of after a random delay, so it arrives in
  seconds.
- A **feed** is an ordinary thread tree, shown with the post on top and
  the comments underneath.
- A **page** is an article with a path such as `index`; a newer version
  replaces the old one, and nodes keep the current one for as long as the
  site exists.
- A **private post** is an article sealed to one person's key and put in
  their inbox.

Because of this, every way of talking gets the same protections at once.
A chat line is signed just like a post. A page is replicated across nodes
just like a discussion, so it stays readable when its author's computer is
off. A private post travels over Tor just like everything else. And a
client that does not know a newer way of showing a group still shows its
articles as threads, so nothing is lost - only the layout.

## What "nobody controls it" means, precisely

"Nobody controls it" is easy to say and easy to oversell. Control is split
between several parties, so that nobody rules alone:

| Party | Decides |
|-------|---------|
| **Group owner** | the group's type, who may post, who may read a closed group, the moderators, the rules |
| **Node operator** | which groups and peers their node carries, how long it keeps posts, how much postage it asks |
| **Hierarchy maintainer** | which group a name in its hierarchy means, and blocks of identities across it |
| **Reader** | what they see: which groups and feeds they follow |

In detail:

- **The author** can withdraw or edit their own post. Withdrawing is best
  effort: nodes delete it and stop passing it on, but people who already
  read it, and software that ignores the rules, may keep it.
- **A group's owner and moderators** can withdraw posts and ban people *in
  that group*. They decide the group's rules, and they have no power
  anywhere else.
- **A node operator** decides which groups their own node carries, and can
  delete anything from it. That affects only that node; the same posts
  live on at the others.
- **A hierarchy maintainer**, such as whoever looks after `dk.*`, can block
  an identity across the hierarchy - for example someone who posts threats
  in group after group. The block works only on nodes whose operators have
  chosen to honour it, and clients say plainly that something was hidden,
  by whom and why.
- **Nobody** can remove a post from the whole network, change a word of
  someone else's post, post in someone else's name, or read a closed group
  or a private post they were not given.
- **Nobody** sorts what you see. Groups show what was written in the order
  it was written, and the timeline is the feeds you chose to follow, newest
  first - never ranked by what other people clicked on. Ranking would need
  data about readers that Unseenet does not collect.

Posts do not last for ever. A group keeps them for a period its owner sets
(90 days by default) and then the network forgets them. That is not a
decision anybody makes about a particular post; it is how the network
keeps from filling up.

## Anonymous, if you want to be

You need no account, no e-mail and no phone number. Your identity is a key
that your own client makes, and you can have as many as you like - one
for each closed group, if you want them kept apart. Names such as
`@yourname` are optional, and a name links everything its identity
writes, so only give one to an identity you want to be recognised by.

Everything travels over Tor, and every node is an onion service, so your
node does not learn where you are, and nobody watching your connection
sees what you read or write.

What Unseenet cannot do is protect you from yourself. What you write,
how you write it and who you tell can still give you away, and Tor cannot
hide anyone from an adversary able to watch the whole internet at once.

## The price

The protection that shields a whistleblower also shields people with bad
intentions, and a network without accounts cannot check anyone's age or
identity. Unseenet's answer is the one described above - owners,
moderators, operators and maintainers, each with limited power, and
readers who choose what they follow - not a central authority. We think a
free place to talk is worth that price, as Tor and encrypted messaging are.
[About Unseenet](../why.md) says more about it.

!!! warning "Where it stands"
    Unseenet is pre-alpha, and the code has not had an independent security
    review. Try it, pick it apart and tell us what you find, but do not
    rely on it yet to protect anyone whose safety depends on it.

**Details:**
[UN-RFC 0004](../spec/un-rfc-0004.md) (groups, withdrawing posts),
[0005](../spec/un-rfc-0005.md) (forwarding over onion services),
[0008](../spec/un-rfc-0008.md) (chat),
[0009](../spec/un-rfc-0009.md) (inboxes),
[0012](../spec/un-rfc-0012.md) (retention),
[0018](../spec/un-rfc-0018.md) (hierarchies and blocks),
[0028](../spec/un-rfc-0028.md) (chats and posts),
[0034](../spec/un-rfc-0034.md) (feeds and the timeline),
[0035](../spec/un-rfc-0035.md) (pages and sites),
[0042](../spec/un-rfc-0042.md) (editing posts).
