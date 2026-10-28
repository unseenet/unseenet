```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0026                                              October 2026
Category: Standards Track
Status: Draft
Implemented: unseenet-gateway 0.1.0
Updates: 0023

                          Nostr Gateways
```

# Abstract

This document is the network profile (UN-RFC 0023 section 9) for
**Nostr**, limited to relay-based groups (NIP-29). It says how a NIP-29
group maps to `nostr.*`, how threads, comments and chat convert in both
directions, how the original signed event travels along as
`Origin-Proof`, how deletions in the group become cancels, and how the
gateway joins a group before writing in it. It also covers portals
(UN-RFC 0023 section 3.5) to NIP-29 relays. Everything not said here
follows UN-RFC 0023.

# 1. Overview

Nostr is a network of relays that store and pass on *events*: JSON
objects signed by their author's secp256k1 key with a BIP-340 Schnorr
signature (NIP-01). In NIP-29, a group lives on one relay, which is its
authority: the relay signs the group's metadata (`kind:39000`) with its
own key, decides who may write, and enforces moderation. Messages in the
group carry an `h` tag with the group id.

That model is close to Unseenet's: a group with an owner, messages
signed by their authors. Three things make Nostr different from Usenet
(UN-RFC 0024) for a gateway:

- every message is signed, so readers can check imported text against
  its author's own signature (section 4.3);
- deletions are either signed by the author (NIP-09) or decided by the
  relay, which is the group's authority (section 4.5);
- writing needs membership, which the gateway asks for with a join
  request that the relay or the group's admins accept: the other side's
  consent is part of the protocol (section 6).

NIP-72 ("moderated communities") is out of scope; NIP-29 is what the
Nostr NIPs recommend for groups.

# 2. Manifest Fields

For Nostr, the `gateway` field of UN-RFC 0023 section 3.2 means:

| Field     | Value                                                                |
|-----------|----------------------------------------------------------------------|
| `network` | `nostr`                                                              |
| `source`  | `<relay URL>'<group id>`, e.g. `wss://nostr.unseenet.org'unseenet-lab` |
| `host`    | The gateway's Nostr public key, as `npub1…` (NIP-19)                 |
| `abuse`   | A contact reachable from Nostr: an `npub1…` or a URL                 |

The same form names the counterpart in a `portals` entry
(UN-RFC 0023 section 3.5).

# 3. Names

A NIP-29 group id is unique only on its relay, and ids are often random
strings. The gatewayed group is named `nostr.` followed by either:

- a name chosen by the gateway operator and endorsed by the maintainer
  of `nostr` (RECOMMENDED where the id is not meaningful, e.g.
  `nostr.pyramid.table-mesh`), or
- the group id in lower case, with every character not allowed in a
  group name component (UN-RFC 0004 section 1) replaced by `-`.

If neither gives a valid name, the group MUST NOT be gatewayed. Groups
with the same id on different relays are different sources; at most one
of them is gatewayed under a given name.

# 4. Import

## 4.1 What Is Imported

A gateway imports events from the group's own relay only, matching
`{"#h": [<group id>], "kinds": [11, 1111, 9]}`:

| Kind   | NIP    | Meaning                                         |
|--------|--------|-------------------------------------------------|
| `11`   | NIP-7D | A thread: the start of a topic, with a `title` tag |
| `1111` | NIP-22 | A comment: a reply in a thread                  |
| `9`    | NIP-C7 | A chat message                                  |

Before importing from a group the gateway MUST check that its latest
`kind:39000` metadata is signed by the relay's own key (from the relay's
NIP-11 document, `self`, or `pubkey` where `self` is absent) and does not
carry a `private` tag. Groups that fail are not gatewayed.

In addition to UN-RFC 0023 section 4.1, a gateway MUST NOT import:

1. any event whose `id` is not the hash of its serialization, or whose
   signature does not verify (NIP-01). The gateway checks every event
   it receives;
2. moderation and membership events (kinds 9000 to 9022) and the
   relay's own group events (kinds 39000 to 39005);
3. events carrying an `unseenet` tag (section 5.2): they came from
   Unseenet;
4. events with empty content.

Links in the content are text and are imported as text. Media referred to
by them is never fetched.

## 4.2 Conversion

| Unseenet header  | Value                                                            |
|------------------|------------------------------------------------------------------|
| `Subject`        | kind 11: the `title` tag, or the first line of the content. kind 1111: `Re: ` and the subject of the thread it belongs to. kind 9: empty - a chat line has no subject, and none is made up (UN-RFC 0028 section 3.3) |
| `Message-Kind`   | kind 9: `chat`; kinds 11 and 1111: `post` (UN-RFC 0028)          |
| `From`           | The author's display name from their `kind:0` profile where the relay serves one, otherwise the shortened `npub` (`npub1abcdefgh…wxyz`) |
| `References`     | Section 4.4                                                      |
| `Origin-Network` | `nostr`                                                          |
| `Origin-ID`      | The event id, 64 hex characters                                  |
| `Origin-Date`    | `created_at` as an RFC 5322 date in UTC                          |
| `Origin-From`    | The author's public key as `npub1…`                              |
| `Origin-Proof`   | Section 4.3                                                      |
| `Nostr-Kind`     | The event's kind, `11`, `1111` or `9`                            |

The body is the event's `content`. The other headers are set as in
UN-RFC 0023 section 4.2.

## 4.3 Origin-Proof

`Origin-Proof` (UN-RFC 0023 section 4.3.1) is the complete event as
compact JSON on one line: the object with `id`, `pubkey`, `created_at`,
`kind`, `tags`, `content` and `sig`, without whitespace between tokens,
with non-ASCII characters as UTF-8 and line breaks escaped as `\n`.

A client verifies it by:

1. parsing the JSON and recomputing the event id from the NIP-01
   serialization;
2. checking the BIP-340 signature of the id against `pubkey`;
3. checking that the event's `content` equals the article's body (after
   both are given LF line endings and a final line break is ignored) and
   that its `pubkey` is the one in `Origin-From`.

The proof matches when all three hold. A failed check means the gateway,
or someone after it, changed the message.

## 4.4 Threads

| Kind   | Root                      | Parent                    |
|--------|---------------------------|---------------------------|
| `11`   | (it is a root)            | (none)                    |
| `1111` | the `E` tag               | the `e` tag               |
| `9`    | (none)                    | the `e` or `q` tag        |

`References` holds the mapped Unseenet Message-IDs of the root and then
the parent, where they are known (UN-RFC 0023 section 4.4).

## 4.5 Deletions

Two signals mean a message was removed in the group:

1. A deletion request (NIP-09, `kind:5`) with an `e` tag naming an
   imported event and signed by that event's author. The gateway
   records the author of every imported event so it can check this even
   after the relay has dropped the event.
2. The relay no longer serves the event. The relay is the group's
   authority (UN-RFC 0023 section 4.5): authors and admins delete there,
   and many relays drop both the event and the request. A gateway
   asks the relay for the events it imported in the last 7 days; one the
   relay has not served for two consecutive passes, while it still
   serves others from the same group, has been removed.

Either way the gateway posts a cancel for the imported article. Admin
deletions (`kind:9005`) are covered by the second signal.

Nostr has no request not to archive. NIP-40 `expiration` tags SHOULD be
honoured as such a request (UN-RFC 0023 section 4.5).

# 5. Export

## 5.1 Joining

Before writing in a group the gateway sends a join request
(`kind:9021`, with the `h` tag) signed by its Nostr key. The relay
accepts it at once for open groups, or after an admin's decision, or
refuses it. A refused or pending join means the other side has not
agreed, and the gateway MUST NOT try to write in the group
(UN-RFC 0023 section 6.1). A `duplicate:` answer means the gateway is
already a member.

## 5.2 Conversion

An exported article becomes one event, signed by the gateway's Nostr
key, with `created_at` the time of sending:

| The article…                                   | Kind   | Tags besides `h` and `unseenet`                       |
|------------------------------------------------|--------|-------------------------------------------------------|
| refers to nothing known on Nostr               | `11`   | `title` = the Subject                                 |
| answers a thread or comment imported from or exported to the group | `1111` | NIP-22: `E`, `K`, `P` for the thread; `e`, `k`, `p` for the parent |
| answers a chat message                          | `9`    | `q` = the parent's id, relay and author                |

Every exported event carries `["unseenet", "<Message-ID>"]`. Importing
gateways skip events with this tag (section 4.1), so nothing comes back.

The content is the article's body, followed by a blank line and the line

    — <From> (<first 4 characters of the fingerprint>), on Unseenet

so that readers on Nostr can tell Unseenet authors apart even though
every exported event is signed by the gateway.

The relay has accepted the event (UN-RFC 0023 section 5.2 step 4) when it
answers `["OK", <id>, true, …]`.

## 5.3 Why One Gateway Key

The gateway signs every exported event with its own key rather than with
keys made for each Unseenet author. Per-author keys would show authors
apart in Nostr clients, but the gateway would hold secret keys for
people, and those keys would claim on Nostr something nobody can verify.
The author's name and fingerprint in the text, and the `unseenet` tag
pointing at the signed original, say only what is true.

# 6. The Other Side

For Nostr the other side (UN-RFC 0023 section 6.1) is the relay hosting
the group and the group's admins. Their consent is given by accepting
the gateway's join request (section 5.1), and withdrawn by removing it
from the group (`kind:9001`), after which the gateway MUST stop
exporting there. Reading a group that is not `private` needs no consent.

A gateway SHOULD respect the relay's published limits (NIP-11
`limitation`). Many relays allow at most 6 indexable tags per event,
while a NIP-22 comment in a group has 7 (`h E K P e k p`); where a relay
refuses them, the gateway sends replies as chat (`kind:9` with `q`)
instead.

## 6.1 Several Gateways

A NIP-29 group can be served by several gateways (UN-RFC 0038). For
Nostr:

- **The other side's consent** (UN-RFC 0038 section 3.2, step 1) is the
  joining gateway's Nostr key on the group's member list (`kind:39002`)
  or admin list (`kind:39001`) as the relay publishes them. The gateway
  that presents the join request to the owner reads those lists and says
  whether the key is on them. A relay that publishes no lists cannot be
  checked, and the request says so.
- **Already there** (UN-RFC 0038 section 5) means an event in the group
  with the `unseenet` tag (section 5.2) carrying the article's
  Message-ID. Relays index only one-letter tags, so a gateway reads the
  group's recent events and compares the tag itself.
- A gateway takes back (NIP-09) only events it sent itself, never one
  another gateway sent first.

# 7. Portals

A portal to Nostr (UN-RFC 0023 section 3.5) is a NIP-29 group created
for an Unseenet group:

- on a relay where the gateway may create groups (`kind:9007`), for
  example the Unseenet project's own relay `wss://nostr.unseenet.org`;
- with a group id made from the Unseenet group's name, with `.` replaced
  by `-` (`dk.snak` becomes `dk-snak`);
- with metadata (`kind:9002`) whose name is the Unseenet group's name
  followed by `(Unseenet)` and whose `about` says that it is a portal,
  that posts are copied both ways, and where the Unseenet group is.

Unseenet articles become events as in section 5.2. Events written in
the portal are imported into the Unseenet group as in section 4.

# 8. Timing Signals

Nostr has no presence, typing or read receipts in NIP-29 groups, but
reactions (`kind:7`) and zaps (`kind:9735`) are visible activity. A
gateway MUST NOT send reactions, zaps or any other event on behalf of
Unseenet authors apart from the exported message itself (UN-RFC 0023
section 5.3).

`created_at` of an exported event is the time of sending, after the
random delay of UN-RFC 0023 section 5.2, not the article's `Date`.

# 9. Headers Defined Here

| Header       | In       | Defined in  |
|--------------|----------|-------------|
| `Nostr-Kind` | Unseenet | section 4.2 |

# 10. Rationale

- **Why NIP-29 and not NIP-72?** NIP-72 is marked unrecommended in the
  NIPs, and NIP-29's relay authority and join requests give exactly the
  owner and the consent UN-RFC 0023 asks for.
- **Why trust a relay that drops an event?** In NIP-29 the relay is the
  group; there is nowhere else the group exists. The two-pass rule and
  the requirement that other events are still served guard against
  outages.
- **Why the whole event in `Origin-Proof`, not just the signature?**
  The signature covers the serialization of all fields, tags included.
  Without them nothing can be verified.

# 11. Security Considerations

UN-RFC 0023 section 13 applies. In addition:

- `Origin-Proof` proves the text and the author's key, not who holds the
  key. Nostr keys are as cheap as Unseenet keys.
- A relay can drop events to make the gateway cancel them; it can do the
  same to every Nostr client, so the gateway is no worse off than a
  Nostr reader of the group.
- The gateway's Nostr key can post in every group it has joined. It is
  kept sealed with the gateway's passphrase and SHOULD be replaced, and
  the gateway removed from its groups, if the gateway host is
  compromised.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
