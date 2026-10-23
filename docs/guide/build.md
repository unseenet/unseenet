# Build your own

Unseenet is meant to be like the old internet standards: written down, so
that anyone can build a node, a client or a gateway that works with
everybody else's, in any language, without asking the project. This last
chapter is a map for doing that: which UN-RFCs to read, in which order,
for what you want to build.

## How the specification works

The protocol is specified in the **UN-RFC series**, numbered documents in
the tradition of the RFCs that once defined Usenet. They are the authority:
an implementation that follows them can join the network, and where the
project's own code and a UN-RFC disagree, the code has the bug.

Every UN-RFC is still a **Draft** while Unseenet is pre-alpha, so details
can change, and there is no promise of compatibility before 1.0. A change is
proposed the same way for everyone: an issue that describes the problem,
then a pull request with a new draft, as [UN-RFC 0000](../spec/un-rfc-0000.md)
describes. The specification is under CC BY 4.0 and the code under the
Apache License 2.0.

## Everyone starts here

1. [0000 Process](../spec/un-rfc-0000.md) - how the series works, and the
   full index.
2. [0001 Architecture](../spec/un-rfc-0001.md) - the parts and how they fit.
3. [0002 Article format](../spec/un-rfc-0002.md) - what an article is, how its
   Message-ID is computed, and the validation every node and client runs.
4. [0003 Identities and crypto](../spec/un-rfc-0003.md) - keys, fingerprints,
   signatures and encryption, by name.
5. [0004 Groups](../spec/un-rfc-0004.md) - Group IDs, manifests, the types,
   bans and withdrawing posts.

With those five you understand what everything else builds on.

## A client that reads

The smallest useful client connects to a node over Tor, reads groups and
checks everything itself. It needs:

- [0005 ONNTP](../spec/un-rfc-0005.md) - NNTP over an onion service: the
  commands a client uses.
- [0010 Known nodes](../spec/un-rfc-0010.md) - finding a node to start with.
- [0008 Chat](../spec/un-rfc-0008.md) and [0028 Chats and posts](../spec/un-rfc-0028.md) -
  views, data groups, and the two kinds of message.
- [0018 Hierarchies](../spec/un-rfc-0018.md) and [0019 Names](../spec/un-rfc-0019.md) -
  showing groups and people safely, with petnames.
- [0031 Markdown and emoji](../spec/un-rfc-0031.md) - rendering posts as a
  safe tree, never as HTML.

The one rule not to skip: **check every signature, manifest and withdrawal
yourself**, as section 4 of 0004 says. A client that trusts its node can be
fooled by it.

## A client that writes

To post, a client also needs:

- [0006 Postage](../spec/un-rfc-0006.md) and [0025 Key ripening](../spec/un-rfc-0025.md) -
  the proof-of-work on every article, and the ripening that sets its
  price.
- [0007 Data at rest](../spec/un-rfc-0007.md) - the vault, and writing nothing
  to the host.
- [0009 Inboxes](../spec/un-rfc-0009.md) - private posts and contacting
  operators.
- [0029 Key-bound groups](../spec/un-rfc-0029.md) - the groups that belong to
  a key, and renewing them.
- Then, as you add features: [0022 Profiles](../spec/un-rfc-0022.md),
  [0027 Attachments](../spec/un-rfc-0027.md),
  [0030 Comments in channels](../spec/un-rfc-0030.md),
  [0032 Mention notices](../spec/un-rfc-0032.md),
  [0033 Pins](../spec/un-rfc-0033.md),
  [0034 Feeds](../spec/un-rfc-0034.md),
  [0035 Pages and sites](../spec/un-rfc-0035.md),
  [0042 Editing posts](../spec/un-rfc-0042.md),
  [0044 Your state in the network](../spec/un-rfc-0044.md).

### Or build on the core

You do not have to implement all of that. A program in Python can use the
project's client core, `Session`, which already does keys, the vault, Tor,
postage, ripening and every check; a front end in any other language can
talk to the same core through the [local client API](../spec/un-rfc-0046.md)
on `127.0.0.1`. Either way your client behaves like the others from the
first day. See [Write a client](../developers/index.md).

## A node

A node needs the client's reading list from 0002 to 0006, the ripening
check of 0025, and:

- [0016 Peer keys](../spec/un-rfc-0016.md) - how nodes prove who they are.
- [0017 Catch-up by pull](../spec/un-rfc-0017.md) - group state, and getting
  what was missed.
- [0012 Retention](../spec/un-rfc-0012.md) - how long posts travel and are
  kept.
- [0013 Removing groups](../spec/un-rfc-0013.md) - `rmgroup`, local drops and
  tombstones.
- [0011 Node information](../spec/un-rfc-0011.md) and
  [0021 Listed nodes must be connected](../spec/un-rfc-0021.md) - what a node
  tells others, and what it takes to be listed.
- [0040](../spec/un-rfc-0040.md) and [0041](../spec/un-rfc-0041.md) - key-bound
  groups and manifests at the scale of millions.
- [0027](../spec/un-rfc-0027.md) and [0035](../spec/un-rfc-0035.md), if it
  carries files and sites.

## A gateway or an entrance

- A **gateway** follows [0023 Gateways](../spec/un-rfc-0023.md), one network
  profile - [0024 Usenet](../spec/un-rfc-0024.md),
  [0026 Nostr](../spec/un-rfc-0026.md) or [0037 Matrix](../spec/un-rfc-0037.md),
  or a new one you write - and [0038](../spec/un-rfc-0038.md) for working
  alongside other gateways. The project's gateway has a shared core and one
  adapter per network, and a new adapter is the easiest way in.
- A **web entrance** follows [0043 Web entrances](../spec/un-rfc-0043.md).

## Testing against the network

- The project's test nodes and the group `unseenet.test` are there to be
  posted in by new software. Test nodes may be reset.
- The project's own code is the reference: when your implementation and
  it disagree, check the UN-RFC - and if the UN-RFC is unclear, that is
  worth an issue.
- A classic newsreader such as tin can read a node's open groups over Tor,
  which is a quick way to see what a node serves.

When something you build works, say so in the group `unseenet` - every
independent implementation makes the network stronger, and shows that the
specification says what it means.
