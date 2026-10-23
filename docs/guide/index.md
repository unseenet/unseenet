# How it works

This section explains Unseenet from end to end, in ordinary prose, with
the technical words introduced as they are needed. This page is the whole
idea on one page; each part links to a chapter that goes deeper. It sits
between [Why Unseenet](../why.md), written for people who have never heard
of Tor, and the [UN-RFC series](../spec/index.md), written for people who
build nodes and clients.

!!! note "The specification decides"
    These pages are not normative. They simplify on purpose, and they may
    lag behind a change. When they and a UN-RFC disagree, the UN-RFC is
    right - and these pages have a bug. Every chapter ends with the
    UN-RFCs it covers.

## Unseenet on one page

**Why.** Most conversation online now happens in places with an owner who
can decide who may speak, remove what was said, sort what you see and
hand over who said what. Unseenet offers the same ways of talking -
discussion, chat, feeds, pages, private posts - with nobody in that
position. → [Why it matters](why.md)

**Everything is an article in a group.** A post, a chat line, a page and a
private post are all short signed texts in a group. Nodes store them and
pass them to each other, the way Usenet servers did - with no route
recorded and a random delay, so nobody can tell where a post was written.
→ [A post's journey](journey.md)

**You are a key.** There are no accounts. Your client makes a key pair,
keeps it in an encrypted vault, and signs everything you write with it, so
nobody can post in your name. Names such as `@yourname` are optional
labels on top. New keys ripen for a while before they post cheaply, which
keeps spam out without asking anyone for a phone number. → [Identity](identity.md)

**Groups have owners, the network does not.** Each group has an owner who
chooses who may write (open, moderated, channel, closed, inbox) and how it
is shown (threads, chat, feed, pages). Owners, moderators, node operators
and hierarchy maintainers each have a little power, and nobody has all
of it. → [Groups](groups.md)

**Nodes are onion services.** Anyone can run one, on a Raspberry Pi or a
free VM, with no public address. Nodes peer with nodes their operators
choose, check everything they receive, and forget posts after the group's
retention period. → [The node](node.md)

**One core, many clients.** The terminal client, the graphical client, the
browser version and the command line all use the same core, which holds
the keys, talks Tor and checks every signature itself.
→ [The clients](clients.md)

**Tor hides who talks to whom.** Every connection goes through Tor, so no
node learns where its users are, and nobody watching your connection sees
what you read or write. → [Tor and Tails](../tor.md)

## Still to come

- *Out into the world* - web entrances, gateways to Usenet, Matrix and
  Nostr, and portals.
- *The threat model in plain words* - what is hidden from whom, and what
  Unseenet does not protect against.
- *Build your own* - which UN-RFCs to read, in which order, to write a
  node or a client.

Some of what these pages describe is still being built. Where that is so,
they say which release brings it.
