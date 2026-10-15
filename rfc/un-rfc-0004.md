```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0004                                              October 2026
Category: Standards Track
Status: Draft

            Unseenet: Groups, Manifests and Access Control
```

# Abstract

This document defines Unseenet groups: how they are named, how they are
created and changed through signed manifests, the four group types and
their posting rules, end-to-end encryption of closed groups with
epoch-based key rotation, and cancellation.

# 1. Group IDs

A Group ID is

```
group-id = name "@" fingerprint
name     = component *( "." component )
component= ( a-z / 0-9 ) *( a-z / 0-9 / "+" / "_" / "-" )
```

where `fingerprint` is the owner's key fingerprint (UN-RFC 0003, 16
characters). `name` is at most 128 octets.

Example: `dk.snak@ab3k5x7qwe2rtz4m`.

Because the fingerprint is part of the ID, anybody can create
`dk.snak`, but only one owner can own `dk.snak@ab3k5x7qwe2rtz4m`.
Clients SHOULD display the short form `dk.snak@ab3k` and MUST warn when
a user subscribes to a group whose name equals that of another
subscribed group with a different fingerprint.

The first name component conventionally names a hierarchy as on Usenet
(`comp`, `sci`, `alt`, `dk`, ...). There is no authority over
hierarchies; they are only a convention for browsing.

# 2. Group Types

| Type        | Who may post                                         | Readable by  |
|-------------|------------------------------------------------------|--------------|
| `open`      | any identity                                         | anyone       |
| `moderated` | owner, moderators; others only with a valid approval | anyone       |
| `channel`   | owner, moderators, and listed posters                | anyone       |
| `closed`    | holders of the current group secret                  | members only |

The type is fixed at creation. A later manifest MUST NOT change it;
nodes MUST reject a manifest that does.

# 3. Manifests

A manifest is an article (UN-RFC 0002) with:

- `Control: manifest`
- `Newsgroups:` the Group ID
- `Author-Key:` the owner's key, whose fingerprint MUST equal the
  fingerprint in the Group ID
- `Content-Type: application/json`
- a body that is a single JSON object in **canonical JSON**: UTF-8,
  object keys sorted by code point, no insignificant whitespace,
  followed by CRLF.

## 3.1 Fields

| Field            | Type            | Req. | Meaning                                  |
|------------------|-----------------|------|------------------------------------------|
| `v`              | integer         | yes  | `1`                                      |
| `name`           | string          | yes  | The name part of the Group ID            |
| `type`           | string          | yes  | `open`, `moderated`, `channel`, `closed` |
| `owner`          | key string      | yes  | Owner key; MUST equal `Author-Key`       |
| `serial`         | integer         | yes  | Starts at 1, increases with each change  |
| `title`          | string          | no   | Short title (max 128 characters)          |
| `description`    | string          | no   | Description (max 2048 characters)         |
| `moderators`     | array of keys   | no   | Moderators                                |
| `posters`        | array of keys   | no   | Extra posters (channel groups)            |
| `min_pow`        | integer         | no   | Minimum postage bits (UN-RFC 0006), default 0 |
| `retention_days` | integer         | no   | Suggested retention, default 90           |
| `sealed`         | b64 string      | no   | Closed groups: encrypted private info (6.6) |

Unknown fields MUST be preserved (they are inside the signed body) and
ignored.

## 3.2 Which Manifest Is Current

Of all valid manifests for a Group ID, the one with the highest
`serial` is current. If two valid manifests have the same serial, the
one with the lexicographically lowest Message-ID wins. This makes the
choice deterministic on every node without coordination.

## 3.3 Creating a Group

A group is created by posting its first manifest (serial 1) to a node.
Whether a node carries a new group is the operator's decision. A node
SHOULD support at least these policies: accept all new groups; accept
groups from a list of trusted owner keys; hold new groups for manual
approval.

Manifests are replicated like any other article and are exempt from the
group's own `min_pow`, but not from the node's minimum postage.

# 4. Manifest Validation

In addition to UN-RFC 0002 section 5, a node MUST check that:

1. The body parses as JSON and is in canonical form.
2. `v` is 1; `name` matches the Group ID; the owner fingerprint matches.
3. `owner` equals `Author-Key`.
4. If a previous manifest is known, `type` is unchanged and `owner` is
   unchanged, except by a transfer (UN-RFC 0015).

# 5. Posting Rules

A node MUST reject an ordinary (non-control) article that does not
satisfy the rule for the group's type under the current manifest:

- **open:** no additional rule.
- **channel:** `Author-Key` is the owner, a moderator or a poster.
- **moderated:** `Author-Key` is the owner or a moderator, **or** the
  article carries
  - `Approved-By:` a moderator's (or the owner's) key, and
  - `Approval:` a signature by that key, purpose `UNSEENET-APPROVAL-1`,
    over `group-id || 0x00 || message-id` (the Message-ID including
    angle brackets, as ASCII).

  Because `Approved-By` and `Approval` are outside the canonical form,
  approving an article does not change its Message-ID. How an
  unapproved article reaches a moderator is not specified in this
  version (reserved: UN-RFC 0009); clients MAY hand it over out of band.
- **closed:** see section 6.5.

# 6. Closed Groups

## 6.1 Epochs and the Group Secret

A closed group's lifetime is divided into **epochs** numbered from 1.
Each epoch has a random 32-octet group secret `S_e`. From it,
`enc_key_e` and the epoch's **member key** are derived as in UN-RFC
0003 section 4.3.

## 6.2 Key Updates

An epoch begins with a key-update control article by the owner:

- `Control: key-update <epoch>`
- `Content-Type: application/json`
- canonical JSON body:

```json
{"envelopes":{"<tag>":"<b64 sealed box>", ...},"epoch":2,"member_key":"ed25519:...","v":1}
```

Each envelope is a sealed box (UN-RFC 0003 section 4.1) to one member,
containing `S_e` (32 octets). The tag lets a member find their envelope
without revealing who they are:

```
tag = first 16 chars of b32( H( DS("UNSEENET-RECIPIENT-1") ||
        group-id || 0x00 || epoch-as-text || 0x00 || member_pk ) )
```

Tags differ between groups and between epochs, so they cannot be used to
link a member across groups.

The owner MUST include an envelope for themself. A new epoch MUST be
started whenever a member is removed.

## 6.3 Adding Members Without Rotation

To add a member without starting a new epoch, the owner posts
`Control: key-grant <epoch>` with the same body format but without
`member_key`. Nodes validate only that the author is the owner.

## 6.4 Joining

How a prospective member communicates their public key to the owner is
outside the protocol (e.g. an invitation link or a message in another
group). A client SHOULD support invitation URIs of the form

```
unseenet:join?g=<group-id>&n=<node-onion-address>
```

which tell the client which group to subscribe to and which node to ask.

## 6.5 Encrypted Articles

An ordinary article in a closed group MUST:

- have `Encrypted: xchacha20poly1305; epoch=<e>`;
- NOT have `From` or `Subject` in the outer header block;
- have as body the b64 encoding (lines of at most 76 characters) of
  `nonce || ciphertext`, encrypted with `enc_key_e` and associated data
  `group-id || 0x00 || epoch-as-text`;
- carry `Member-Signature:`, a signature with the epoch's member key,
  purpose `UNSEENET-MEMBER-1`, over the canonical form `C` of the
  article.

The plaintext is an inner block in article syntax: inner headers
(at least `From` and `Subject`; optionally `Content-Type` and others),
an empty line, and the inner body.

A node MUST reject the article unless `Member-Signature` verifies with
the member key of epoch *e*, and *e* is the current epoch or the one
before it (to tolerate replication delay). Thus only holders of the
group secret can post, and nodes enforce this without being able to
read anything.

## 6.6 Sealed Manifest Information

The manifest of a closed group is public. Its `title` and `description`
SHOULD therefore be omitted or generic. Private information MAY be put
in `sealed`: the b64 of `nonce || ciphertext` of a canonical JSON
object, encrypted with `enc_key_1` and associated data
`group-id || 0x00 || "manifest"`.

# 7. Cancellation

`Control: cancel <message-id>` withdraws an article. It is valid when
its author is the author of the target article, or the owner or a
moderator of the group. A node that accepts a valid cancel SHOULD
delete the target and MUST NOT forward the target afterwards. The
cancel itself is forwarded like any article. A node that has not seen
the target yet SHOULD remember the cancel so it can refuse the target.

Old Usenet's forged cancels are impossible because cancels are signed
and checked against the target.

# 8. Security and Privacy Considerations

- **Removed members** keep everything they already received. Rotation
  only protects future content. There is no forward secrecy within an
  epoch. A stronger scheme (e.g. MLS, RFC 9420) may be specified later.
- **Metadata** visible to nodes for closed groups: Group ID, manifest,
  number of envelopes (≈ member count), article sizes, approximate
  dates and author keys.
- **Owner key loss** means the group can no longer be changed. Owners
  SHOULD keep an offline backup of the owner key.
- Nodes enforce posting rules, but a malicious node can still drop
  articles. Clients SHOULD read from more than one node.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
