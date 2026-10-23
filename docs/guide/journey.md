# A post's journey

The quickest way to understand Unseenet is to follow one post from the
moment it is written until somebody else reads it. Maja writes a post in
the discussion group `dk.snak`; Jonas, who follows the group, reads it a
little later from another node.

<!-- unseenet:diagram journey -->

## 1. Writing

Maja's client - the terminal client, the graphical client or any other -
has her **vault** open: an encrypted file holding her keys, her groups and
what she has read. One of the keys is the identity she posts with.

She writes a **post** rather than a chat line: it has a subject and will
have its own place in a thread. If `dk.snak` were a chat group, her client
would offer a chat line instead, and if she were not allowed to write
there, the client would not offer to write at all.

## 2. Sealing it

When she presses send, her client turns the text into an **article**: a
few headers and the text, much like a Usenet post or an e-mail.

```
Newsgroups: dk.snak@ab3k5x7qwe2rtz4m
Date: Thu, 15 Oct 2026 19:50:00 +0000
From: Maja
Subject: Hej fra Unseenet
Author-Key: ed25519:...
Signature: ed25519:...
Proof-Of-Work: sha256; bits=20; nonce=Hk9r2w
Message-ID: <q3x7ku2m5a4e6rj2wl9zpn4c8y3h2t5v@unseenet>

Det virker!
```

Three things happen here:

- **It is signed.** The client signs the article with Maja's key. Anyone
  can check the signature against `Author-Key`, but only Maja's key can
  make it - so nobody can post in her name, and nobody can change a word
  on the way without the signature failing.
- **It gets its name from its content.** The `Message-ID` is calculated
  from the signed content, so the same post always has the same ID. Every
  node can tell at once whether it has seen it before.
- **The group is named with its owner.** `dk.snak@ab3k5x7qwe2rtz4m` is the
  readable name plus the fingerprint of the owner's key. Anyone can create
  a group called `dk.snak`; only one person owns this one.

If `dk.snak` were a **closed group**, the client would encrypt the text
with the group's secret before signing, and the nodes would carry only
scrambled data. If Maja were writing privately to Jonas, the client would
seal the article to Jonas's key and put it in his inbox, signed on the
outside with a key used only once, so that no node could tell who sent it.

## 3. Paying the postage

Before the post leaves, Maja's computer spends about a second solving a
small puzzle: it searches for a number (the `nonce`) that makes a hash of
the article start with a certain number of zero bits. That is the
**proof-of-work**, Unseenet's postage stamp. Maja hardly notices it.
Someone trying to send a million posts would need a million seconds.

There are no accounts and no central moderation to keep spam out - the
cost of posting does it, together with keys that must first have
**ripened** for a while before they may post cheaply.

## 4. Over Tor to her node

Maja's client connects to the node she uses. Every node is a Tor
**onion service**: it has an address ending in `.onion`, but no location.
The connection runs through about six Tor relays, three chosen by each
side, so Maja's node does not learn where she is, and Maja does not learn
where the node is. Her internet provider sees only that she uses Tor.

The client hands the post over with the same command a newsreader used on
Usenet, `POST`. Unseenet speaks a strict profile of NNTP, the old Usenet
protocol.

## 5. The node checks it

Maja's node does not trust her, or anyone. Before it accepts the post it
checks:

- that the signature is valid and the `Message-ID` matches the content;
- that the postage is enough for this node and this group;
- that the group's **manifest** - its signed settings - allows Maja to
  post, and allows posts rather than only chat lines;
- that the post is not too old, not withdrawn, and not seen before.

If anything is wrong the node says why, and Maja's client tells her.
Otherwise the node stores the post.

## 6. Passing it on

Now the post spreads, the way Usenet posts always did. Maja's node offers
it to the nodes it **peers** with; they check it exactly as hers did,
store it, and offer it to their peers, until every node that carries
`dk.snak` has it. Because of the `Message-ID`, nobody takes the same post
twice.

Two things are different from Usenet, and both are there to hide where
the post came from:

- **No route is recorded.** Usenet posts carried a `Path` header listing
  every server they had passed through - which pointed straight back to
  where they entered the network. Unseenet has no such header.
- **Nodes wait before passing it on**, a random time of up to a minute,
  separately for each peer. So a node that receives the post cannot tell
  whether the node it came from wrote it down a moment ago or got it from
  somewhere else.

Chat groups make the opposite trade: their lines are passed on at once,
so a conversation can flow, at the price of making the point of entry a
little easier to guess. The group's owner chooses this, and clients show
it.

A node that was switched off catches up when it comes back, by asking its
peers what is new - so nothing is lost while a node sleeps.

## 7. Jonas reads it

Jonas's client connects to his own node, over Tor, and asks what is new in
`dk.snak`. It gets Maja's post - and checks the signature again itself.
A client never trusts a node to do that for it: a node that misbehaved
could otherwise slip in forged posts or hide real ones.

The client puts the post in its place in the thread and shows who wrote
it: `Maja~2byg`, the name she chose and the start of her key's fingerprint
- or `@maja`, if she has claimed a name. Jonas reads it, and replies by
quoting her. His reply makes the same journey back.

## 8. Afterwards

- **Maja can edit the post.** The new version names the old one, nodes
  withdraw the old one, and clients show the new one in its place.
- **Maja can withdraw it**, and so can the group's owner and moderators.
  Nodes delete it and stop passing it on. It is best effort: anyone who
  already read it, or software that ignores the rules, may still have it.
- **After the group's retention period** - 90 days by default - nodes
  forget it and refuse it if it is offered again.

## Who learned what

| Who | Knows | Does not know |
|-----|-------|---------------|
| Maja's internet provider | that Maja uses Tor | what she reads or writes, or where |
| Maja's node | that an article signed by Maja's key arrived over Tor | where Maja is, or who she is unless she says so |
| The other nodes | which peer they got the post from | whether that peer is where it was written |
| Jonas | what Maja's key wrote, and her name if she gave one | where she is, or which node she uses |
| Everyone | that the post is unchanged and really from that key | - |

**Details:**
[UN-RFC 0002](../spec/un-rfc-0002.md) (article format and validation),
[0003](../spec/un-rfc-0003.md) (identities),
[0004](../spec/un-rfc-0004.md) (groups and manifests),
[0005](../spec/un-rfc-0005.md) (ONNTP, peering and the random delay),
[0006](../spec/un-rfc-0006.md) (postage),
[0008](../spec/un-rfc-0008.md) (chat),
[0009](../spec/un-rfc-0009.md) (inboxes),
[0017](../spec/un-rfc-0017.md) (catching up),
[0025](../spec/un-rfc-0025.md) (key ripening),
[0028](../spec/un-rfc-0028.md) (chats and posts),
[0042](../spec/un-rfc-0042.md) (editing).
