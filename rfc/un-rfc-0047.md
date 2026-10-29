```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0047                                              October 2026
Category: Standards Track
Status: Draft
Implemented: unseenet 0.6.0
Updates: 0009, 0011

                     Unseenet: Team Inboxes
```

# Abstract

An inbox (UN-RFC 0009) can be read only by its owner's key. This
document lets an owner name up to 16 **readers**: keys that can read
the inbox and reply on its behalf. A message is still one article,
encrypted once and openable by every reader. Readers are **team keys**
made for that one inbox, never their holders' personal keys, so neither
the manifest nor a reply reveals who reads or who answered. The owner's
key is needed only to change the list of readers, so a valuable key can
stay offline while the inbox is read every day. Node operators with
several nodes get one contact inbox for all of them.

# 1. Motivation

Three things go wrong with single-reader inboxes as more people help
run something:

1. **The owner key is used for daily work.** The project's inbox and
   its nodes' operator inboxes are owned by the project key, which
   otherwise only changes the project's groups. Reading a spam report
   should not need it.
2. **One inbox per node.** UN-RFC 0011 section 5 recommends a local
   inbox on each node. An operator with four nodes has four mailboxes
   and must connect to each node to read them.
3. **Sharing means sharing a seed.** The only way for two people to read
   one inbox is to hold the same key (as the registrar's claim inbox
   does, UN-RFC 0019). Removing one of them means a new key, a new inbox
   and new addresses everywhere.

Forwarding cannot fix this. A node cannot read an inbox, so it cannot
forward one; a bot that forwards must hold the key, which only moves the
problem to a server.

# 2. Terms

Owner
: The key that owns the inbox and signs its manifest (UN-RFC 0004).

Team key
: An Ed25519 key made for one team inbox and used for nothing else.

Reader
: A team key listed in the inbox's manifest. Also, loosely, the person
  holding it.

Team inbox
: An inbox whose manifest lists one or more readers.

# 3. Manifest

An inbox manifest (UN-RFC 0009 section 2.1) MAY contain:

| Field       | Type               | Meaning                                              |
|-------------|--------------------|------------------------------------------------------|
| `readers`   | array of key strings | 1 to 16 team keys that read the inbox              |
| `team_name` | string             | Name shown for replies on the inbox's behalf, max 64 characters |

When `readers` is present:

- messages are encrypted to the readers only (section 4). The owner is
  **not** a recipient. An owner who wants to read lists a team key of
  its own, like anybody else.
- a node MUST refuse a manifest with more than 16 readers, a reader
  listed twice, or the owner's key as a reader.
- without `team_name`, clients show the owner's display name (UN-RFC
  0022) for replies.

At most 16 readers keeps the manifest small (16 keys add about 1 KiB,
well inside the 16 KiB of UN-RFC 0040 section 9) and keeps a team inbox
a mailbox. Something more people should read is a group.

A manifest without `readers` is an ordinary inbox, unchanged.

# 4. The Team Box

An ordinary article in a team inbox MUST meet UN-RFC 0009 section 2.3
with two differences: it has `Encrypted: teambox`, and its body is the
b64 encoding (lines of at most 76 characters) of

```
version (1 octet, 0x01) || slots (16 × 80 octets) || ciphertext
```

where the sender's client:

1. reads the inbox's current manifest (UN-RFC 0029 section 6 makes this
   a SHOULD for every inbox; for a team inbox it is a MUST) and takes
   its `readers`;
2. picks a random 32-octet content key `K`;
3. makes one slot per reader: the sealed box (UN-RFC 0003 section 4.1)
   of `K` to that reader's key, 80 octets;
4. fills the remaining slots, up to exactly 16, with random octets, and
   puts all 16 in random order;
5. encrypts the inner article (UN-RFC 0009 section 2.3, unchanged) with
   XChaCha20-Poly1305 under `K` (UN-RFC 0003 section 4.2), with the
   Group ID as associated data.

Slots carry no key IDs. A reader's client tries to open each slot with
its team key, at most 16 attempts, and stops at the first that opens.
Every team box has 16 slots, so an article shows neither how many
readers the inbox has nor which of them can open it.

`Sender-Signature` binds the group and the outer key as in UN-RFC 0009,
so a team box cannot be lifted into another inbox.

# 5. Nodes

UN-RFC 0009 section 2.4 is extended: in an inbox whose current manifest
has `readers`, a node MUST reject an ordinary article unless it has
`Encrypted: teambox` and a body whose decoded length is at least
`1 + 16 × 80 + 40` octets (`441 permission`, a reason of UN-RFC 0005 section 4). In an inbox without
`readers` it MUST reject `teambox` the same way.

This makes an outdated client fail at once instead of sealing a message
to an owner who no longer reads.

# 6. Adding a Reader

The owner's client:

1. makes a new team key;
2. posts a new manifest with the team key added to `readers`;
3. sends the team key to the future reader's personal inbox (UN-RFC
   0009 section 2.2) as a private post (UN-RFC 0028) with `Sender-Key`
   set to the owner and these inner headers:

   | Header       | Value                                          |
   |--------------|------------------------------------------------|
   | `Team-Inbox` | The team inbox's Group ID                      |
   | `Team-Key`   | The team key's 32-octet seed, b64              |

   The body is text for people, and SHOULD contain a `#group` reference
   to the team inbox, for example:

   > You have been added as a reader of #inbox@ph5fc5hop5232qsz
   > (Unseenet). Open it to accept.

4. forgets the seed. The owner's client MUST NOT keep a team key it made
   for somebody else.

The reader's client, on such a post:

- MUST check that `Sender-Key` is the owner of `Team-Inbox`, and that
  the public key of `Team-Key` is in its current `readers`. Otherwise it
  shows the post as an ordinary private post and ignores the headers.
- shows the invitation with the `#group` reference. Opening it offers
  to subscribe, as for any `#group` reference (UN-RFC 0032 section 5),
  and says what accepting means: "You will read this inbox and can reply
  as *team name*. The owner can remove you at any time."
- on accept, stores the team key in the vault (UN-RFC 0007) next to
  the identity that received it, and subscribes to the team inbox.

Declining needs no message. The owner sees no difference between a
reader who declined and one who never reads, and removes the key when
it wants to.

# 7. Reading

A reader's client shows each team inbox as a mailbox of its own,
labelled with `team_name`, next to the user's personal inbox and never
mixed into it. Read and unread state is each reader's own; readers do
not see what the others have read or answered (section 12).

# 8. Replying on the Inbox's Behalf

A reader replies as UN-RFC 0009 section 2.5 says, with these inner
headers:

| Header        | Value                                              |
|---------------|----------------------------------------------------|
| `Sender-Key`  | The team key                                       |
| `Sender-Team` | The team inbox's Group ID                          |
| `Reply-Inbox` | The team inbox, unless the reader wants otherwise  |

`Sender-Signature` is made with the team key as usual.

The receiver's client, when a message has `Sender-Team`:

- reads that inbox's current manifest and checks that `Sender-Key` is in
  its `readers`;
- if it is, shows the sender as `team_name` (or the owner's display
  name), marked as verified and as written on the inbox's behalf, for
  example "Unseenet (operator)". It MUST NOT show the team key as a
  person, nor look up a profile or name for it;
- if it is not, shows the message as from an unverified key that is not
  (or no longer) a reader of that inbox. A client MAY instead show the
  result it stored when the message first arrived.

A team key is for the team inbox only. Clients MUST NOT use it to post
in groups, create groups, claim names, or make a personal inbox,
profile or ripening chain for it. Replies to it go to `Reply-Inbox`.

# 9. Removing and Replacing Readers

The owner removes a reader by posting a manifest without its key. From
then on, senders' clients leave it out of new team boxes, and receivers'
clients no longer verify its replies. Nothing tells the removed reader;
its client sees the manifest and SHOULD say that it is no longer a
reader and offer to delete the key.

A removed reader can still open messages sent before its removal, if it
kept them or they are still on the nodes. Owners SHOULD keep the team
inbox's `retention_days` short (UN-RFC 0009 recommends 30).

To replace a lost or exposed team key, the owner removes it and adds a
new one (section 6) in the same manifest.

The owner key is needed for these changes and, for a key-bound inbox,
to renew it before it expires (UN-RFC 0029), at least every two years.
It is not needed to read or answer.

# 10. Operator Contact (Updates UN-RFC 0011 Section 5)

Section 5 of UN-RFC 0011 is extended:

- An operator with **more than one node** SHOULD use one replicated
  team inbox instead of a local inbox per node, and name it in
  `contact` on all of them. Messages then reach the operator whichever
  node the writer uses, and the operator reads them from any node.
- `operator` names the owner of the contact inbox, which MAY be a key
  that stays offline; the people answering are its readers.
- A single operator with one node MAY keep the local inbox of section 5.

A replicated contact inbox spreads its articles to every node that
carries it, where a local one stays on one node. The articles are
encrypted either way; what spreads is that the inbox received something
of a certain size at a certain time.

Example: the project's nodes all name one team inbox owned by the
project key, with `team_name` "Unseenet (operator)", and the maintainer
reads it with a team key in his everyday client.

# 11. Security and Privacy Considerations

- **What the manifest shows:** that the inbox is a team inbox, how many
  readers it has, and their team keys. Not who holds them: a team key
  is new, used for nothing else, and has no name, profile or inbox.
- **What an article shows:** the same as for any inbox (UN-RFC 0009
  section 6). Every team box has 16 slots, so not even the number of
  readers.
- **Replies are linkable to each other.** Two replies from the same team
  key show the receiver that the same reader wrote both, though not
  who. See section 12.
- **The owner is trusted.** It chooses the readers, so it can add a key
  of its own and read everything, and it knew each team key when it
  made it. A team inbox is for people who trust its owner; it does not
  protect readers from the owner.
- **Readers are trusted.** Any reader can answer as the team. A reader
  who misbehaves is removed (section 9).
- **The invitation carries a secret.** It is sealed to the reader's
  personal key like any private post. A reader's client MUST delete the
  invitation's `Team-Key` from the message store once the key is in the
  vault.
- **No forward secrecy**, as for every inbox: whoever gets a team key
  can open every stored message sent while it was a reader.
- **Timing:** as in UN-RFC 0009 section 6, an observer of several nodes
  may link a message to a quick reply. Readers' clients MAY delay
  replies.

# 12. Open Issues

- **Shared state.** Readers cannot see what another reader has read,
  answered or dealt with. A small shared "handled" marker, encrypted to
  the readers, would avoid two people answering the same report.
- **Unlinkable replies.** A reader could hold several team keys for one
  inbox, at the cost of manifest space.
- **Posting publicly on a team's behalf**, e.g. operator notices in a
  group, is not covered.
- **Moving other inboxes to team inboxes:** `submissions` of moderated
  groups (UN-RFC 0009 section 3), the registrar's claim inbox (UN-RFC
  0019) instead of a shared seed, and issuers' `contact` (UN-RFC 0045).

# 13. Rationale

- **Not forwarding.** A node cannot read an inbox, and a forwarding bot
  must hold the key, so the key ends up on a server anyway.
- **Not a shared seed.** One key for everybody cannot be taken from one
  person; removing anyone means replacing it for all.
- **Not personal keys as readers.** The manifest is public. Listing a
  personal key would tell the world who reads a node's contact inbox,
  and so who runs the node.
- **One article, not one per reader** (as UN-RFC 0009 section 3 does
  for moderators): a single article costs one postage and one copy on
  every node, and does not show the number of readers.
- **Sixteen slots, always.** Padding costs about 1.2 KiB per message and
  hides the team's size. Sixteen is enough for a mailbox; more is a
  group.

# 14. Changes to Other Documents

- UN-RFC 0009 section 2.1: an inbox manifest MAY have `readers` and
  `team_name` (section 3).
- UN-RFC 0009 section 2.4: nodes accept `Encrypted: teambox` in team
  inboxes and only there (section 5).
- UN-RFC 0011 section 5: operators with several nodes SHOULD use one
  team inbox (section 10).

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
