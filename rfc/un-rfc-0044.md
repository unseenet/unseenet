```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0044                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0000, 0004, 0007, 0009, 0029, 0040

               Unseenet: Your State in the Network
```

# Abstract

A person's Unseenet is more than their keys: the groups they follow,
what they have read, their contacts and settings, and the private posts
they sent. Today all of that lives in the vault file on one stick, so it
does not follow them to the web client, to a second stick or to a
phone, and it is lost with the stick. This document moves it into the
network. Each identity gets one more key-bound group, `state@<fp>`,
whose manifest carries the identity's **state**, encrypted so that only
the holder of the key can read it; nodes keep only the newest version.
Private posts get a second key envelope, so the sender can read what
they sent from any client. The vault keeps the keys, and a local copy
of the rest for when there is no network.

# 1. Motivation

UN-RFC 0007 puts all client state in one vault. That was right for a
client that lives on one stick. It is wrong for a person who uses the
terminal client at home, the graphical client at work and a web client
(UN-RFC 0043) on a phone: each has its own subscriptions and read marks,
and a private post sent from one cannot be read from the others, since
it is sealed to the recipient.

Only the keys need to be carried. Everything else can be fetched from
the network by whoever holds them, the same way a profile is
(UN-RFC 0022).

# 2. What Goes Where

| What                                   | Where                                         |
|----------------------------------------|-----------------------------------------------|
| Identity keys, group secrets           | The vault only. Never in the network.         |
| Subscriptions, contacts, ignored keys, signature, client settings | The state (section 4) |
| What you have read                     | The state, coarsely (section 4.3)             |
| Copies of private posts you sent       | The network: a second envelope (section 6); the state lists where they are |
| Cached articles                        | The vault's cache, as today; never in the state |

Group secrets of closed groups stay in the vault: the state is
protected by one key, and a closed group's secret is worth more than
the knowledge that someone follows it.

# 3. The State Group

The group named `state` owned by an identity is its **state group**:

```
state@<fingerprint of the identity's key>
```

It is a key-bound group (UN-RFC 0029): it lives at most two years and
the owner's client renews it. Only the owner writes to it. It has no
articles: the state is the manifest itself, so nodes keep exactly one
copy, the newest (UN-RFC 0004 section 3, highest `serial`).

The manifest's data, besides the fields every key-bound manifest has:

```json
{"v": 1, "name": "state", "type": "state", "serial": 57,
 "expires": "2028-10-20T00:00:00Z",
 "state": "<b64 of nonce || XChaCha20-Poly1305 ciphertext>"}
```

`type` `state` is added to the group types of UN-RFC 0004. A node
accepts only a manifest from the key the fingerprint names, and no
articles in the group.

# 4. The State

## 4.1 Encryption

The state is encrypted with XChaCha20-Poly1305 (UN-RFC 0003 section
4.2) under

```
state_key = H(DS("UNSEENET-STATE-1") || seed)
```

where `seed` is the identity's 32-octet Ed25519 seed. The associated
data is the Group ID. Only the holder of the seed can read or write the
state; nodes and everyone else see a blob of fixed size (section 5).

## 4.2 Contents

The plaintext is canonical JSON (UN-RFC 0004):

```json
{"v": 1, "updated": "2026-10-20T20:10:00Z",
 "subscribed": {"unseenet.test@ph5fc5hop5232qsz": "2026-10-16T21:00:00Z"},
 "unsubscribed": {"alt.old@abcd...": "2026-10-19T08:00:00Z"},
 "following": {"<fingerprint>": {"key": "ed25519:...", "name": "andreas@lorensen",
               "feeds": ["feed@..."], "skip": [], "at": "..."}},
 "unfollowed": {"<fingerprint>": "..."},
 "starter": 2,
 "contacts": {"ed25519:...": {"name": "Sonia", "at": "2026-10-18T19:00:00Z"}},
 "ignored": {"ed25519:...": {"label": "", "at": "..."}},
 "hidden": {"ed25519:...": "..."},
 "closed_chats": {"ed25519:...": {"since": "2026-10-24T21:00:00Z", "at": "..."}},
 "settings": {"signature": "...", "markdown": true, "notices": {"send": true, "take": true},
              "private_min_ripe": 0, "hide_bots": false, "show_blocked": false,
              "clients": {"tui": {"theme": "nord"}, "gui": {"theme": "dark"}},
              "at": "..."},
 "read": {"unseenet.test@ph5fc5hop5232qsz": {"to": "2026-10-20T19:00:00Z",
          "also": ["<abc@unseenet>"]}},
 "sent": [{"msgid": "<def@unseenet>", "inbox": "inbox@...", "at": "..."}]}
```

- `following` / `unfollowed`: the people followed (UN-RFC 0034 section
  6.1), by fingerprint, with the feeds followed because of them and the
  ones the user stopped following; who you follow stays private this way
  too, since only you can read the state.
- `starter`: the version of the starter groups this identity has taken,
  so a new client does not follow again a starter group the user left.
- `hidden`: keys whose profiles the user hides (UN-RFC 0022).
- `closed_chats`: chats with a person the user closed, so they leave the
  list of chats on every device (UN-RFC 0028 section 6.2). `since` is when
  it was closed. A closed chat opens again by itself as soon as there is
  a chat line from or to that person dated after `since`, so no new
  message is ever hidden; dates are rounded to 10 minutes (UN-RFC 0009),
  so a line in the same 10 minutes as the closing may wait for the next.
  The messages stay; closing only takes the chat off the list. Opening it
  again on purpose writes it as removed.
- `settings`: the user's settings that are not about one device - the
  signature, Markdown, mention notices (UN-RFC 0032), the ripening level
  private senders need (UN-RFC 0025 section 3.5), hiding bots, showing
  blocked posts - and `clients`, each kind of client's own settings by its
  name, such as its theme, which mean nothing to another kind.

Every entry carries the time it last changed (`at`), so that two
clients can merge (section 7). A contact, an ignored key, a hidden
profile or a closed chat that is removed stays as `{"removed": true, "at": ...}`, so the
removal reaches the other clients too; a group or person no longer
followed moves to `unsubscribed` or `unfollowed`.

## 4.3 Read Marks, Coarsely

Article numbers belong to one node (UN-RFC 0005), so read marks are by
date and Message-ID: `to` means "everything in this group dated up to
here is read", and `also` lists articles after `to` that are read
anyway, at most 64 per group. A client moves `to` forward when it can
and drops the `also` entries it covers.

This loses detail that only matters within a day or so, and keeps the
state small enough for section 5.

## 4.4 What the State Does Not Hold

Bodies of posts, drafts, cached articles, group secrets, passphrases,
and anything about other people beyond their key and the name you gave
them. Drafts stay on the device: they change often and would push the
state past its size (section 5).

# 5. Size and Padding

The plaintext is padded with spaces after the JSON to the smallest of
4, 8 or 16 KiB that holds it. A state larger than 16 KiB MUST NOT be
written; the client drops the oldest `sent` entries, then the oldest
`also` entries, then read marks of groups it no longer follows, until it
fits.

UN-RFC 0040 section 9 gets the limit for `state@`: 24 KiB for the whole
manifest article.

Fixed sizes keep nodes from learning how many groups or contacts
someone has from the length.

# 6. Copies of Sent Private Posts

## 6.1 A Second Envelope

The body of an inbox article (UN-RFC 0009 section 2.3) changes from one
sealed box of the inner article to:

```
envelope-1 || envelope-2 || ciphertext
```

- `ciphertext` is the inner article encrypted with XChaCha20-Poly1305
  under a random 32-octet `content_key` (nonce first, associated data
  the Group ID);
- `envelope-1` is a sealed box of `content_key` to the inbox owner;
- `envelope-2` is a sealed box of `content_key` to the sender's own key
  - or, when the sender does not keep a copy, a sealed box of random
  octets to a random key.

Both envelopes have the same length. Every inbox article has exactly
two, so nobody can tell from an article whether its sender kept a copy,
or whether it has a sender at all; sealed boxes say nothing about whom
they are for. The header `Encrypted: sealedbox2` marks the new form;
UN-RFC 0009 section 2.3 gives its exact layout.

Older nodes take only `sealedbox`, and older clients read only that, so
the new form is used only where both ends can (UN-RFC 0009 section 2.3):
the recipient's inbox manifest says `"sealedbox2": true`, and the
sender's node lists `UNSEENET-SEALEDBOX2`. Otherwise the sender writes
`sealedbox`, as before, and keeps its copy in the vault only.

## 6.2 Finding Them Again

The sender's client adds `{"msgid", "inbox", "at"}` to the state's
`sent` list. Any of the sender's clients can then fetch the article
from that inbox and open `envelope-2`. The copy lives as long as the
recipient's inbox keeps the article (UN-RFC 0012); a client SHOULD also
keep its own copy in the vault, as today.

## 6.3 Chats

Chat lines in private conversations (UN-RFC 0028) are inbox articles
too and get the same second envelope.

# 7. Updating and Merging

## 7.1 How Often

Every update is a manifest that every node replicates. At the scale of
old Usenet (UN-RFC 0040) that matters more than anything else here, so:

- A client MUST NOT write the state more than once an hour, and SHOULD
  write it at most a few times a day: when subscriptions, contacts or
  settings change (after a quiet minute), and when it closes. Read marks
  alone are not a reason to write.
- A node MUST refuse a `state@` manifest that comes less than one hour
  after the one it replaces (by `Date`), with `441 too soon`, and MAY
  apply a higher minimum postage to state groups.

## 7.2 Merging

Before writing, a client fetches the current state and merges it with
its own, so that two clients never undo each other:

- `subscribed` / `unsubscribed`, `contacts`, `ignored`, `settings`:
  per entry, the newer `at` wins; a group is followed if its newest
  entry is in `subscribed`.
- `following` / `unfollowed`, `hidden`, `closed_chats`: per person, the
  newer `at` wins, as for subscriptions.
- `starter`: the higher version.
- `settings`: the newer `at` wins; two of the same age are joined.
- `read`: per group, the later `to`; the union of `also`, trimmed.
- `sent`: the union, by Message-ID.

The merged state gets `serial` one higher than the highest seen.

## 7.3 Starting

When a client starts with an identity, it fetches `state@`, merges it
into its local copy, and only then shows groups. A vault that has never
synced its state gives what it holds the earliest time, not the current
one: it has changed nothing yet, so the network's state wins where they
differ - a new device's defaults never overwrite what was set elsewhere.

A vault with several identities keeps its state with its default
identity; the others keep theirs in the vault only. A vault opened
somewhere new therefore looks the same as everywhere else after one
fetch. Without a network it shows the local copy.

## 7.4 Keeping It Local

An identity can keep its state out of the network, as before this
document: for an identity that should leave no trace of activity at
all, not even an encrypted one. A client MUST offer this as a setting
per identity, on by default (the state goes to the network). With it
off, the client writes no `state@` manifest and keeps everything in the
vault; turning it off removes the identity's state group (UN-RFC 0013),
so the last state written does not linger.

# 8. The Vault

UN-RFC 0007 section 2.1 is unchanged in format. Its meaning narrows:
the vault holds the identity keys and group secrets that must never
leave it, and a local copy of the state and cache, which the network
can restore.

A vault that holds only keys is enough to bring everything back. That
makes small backups possible - a key file on paper or a second stick -
without copying caches.

# 9. Security and Privacy Considerations

- **Who can read it.** Anyone with the identity's seed, and nobody
  else. A seized stick with the vault's passphrase gives the state, as
  it would today.
- **What nodes learn.** That a key has a state group and when it was
  last updated; not its contents or size class beyond the three of
  section 5. To avoid making "has a state" a signal, clients SHOULD
  create the state group for every identity.
- **Timing.** Updates at most hourly and mostly on change or close
  reveal less about when someone reads than per-read updates would.
  Clients MAY delay an update by a random few minutes.
- **One key for both.** The state key is derived from the identity
  seed. Someone who wants their reading habits even further from their
  posting identity uses a separate identity, as UN-RFC 0003 section 2
  already recommends for sensitive groups.
- **Old versions.** Nodes keep only the newest manifest, but an
  archive node (UN-RFC 0012) may have kept older ones. They are
  encrypted with the same key.
- **Sent copies.** The second envelope makes every inbox article
  slightly larger. It does not reveal the sender: sealed boxes are
  anonymous, and every article has two envelopes.

# 10. Rationale

- **Why not the inbox?** Others write to it, it is for messages, and
  its articles expire one by one; the state is one thing that replaces
  itself.
- **Why a manifest and not articles?** Nodes then keep exactly one copy
  per identity, with no history to clean up.
- **Why not every read mark?** Millions of people reading would become
  millions of updates replicated to every node.
- **Why not group secrets?** One stolen seed would then open every
  closed group the person is in, from anywhere, without the vault.
- **Why a second envelope rather than a copy to your own inbox?** A copy
  sent at the same moment would link sender and recipient by timing.

# 11. Open Questions

None. Decided by the maintainer, 24 Oct 2026:

1. Drafts are not in the state (section 4.4).
2. The state can be kept local, per identity (section 7.4).
3. 16 KiB is the largest size (section 5): a key-bound manifest is at
   most 24 KiB (UN-RFC 0040 section 9), so 32 KiB would not fit.

# 12. Changes to Other Documents

- **UN-RFC 0004**: group type `state` (section 3).
- **UN-RFC 0007** section 2.1: the vault's role (section 8).
- **UN-RFC 0009** section 2.3: inbox articles with two envelopes,
  `Encrypted: sealedbox2` (section 6).
- **UN-RFC 0029** section 2: `state@<fp>` is a key-bound group.
- **UN-RFC 0040** section 9: `state@` manifests at most 24 KiB.
- **UN-RFC 0000** section 6: 0044 is added to the index.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
