```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0009                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0002, 0004, 0005

               Unseenet: Inbox Groups and Local Groups
```

# Abstract

This document adds a fifth group type, **inbox**: anyone may post, only
the owner can read. Posts are sealed to the owner's key, and the outer
article is signed by a one-time key, so nodes learn neither the content
nor the sender. Inboxes provide private messages between people, a way
to contact node operators, and a submission queue for moderated groups.
The document also defines **local groups**, which are never replicated
between nodes.

# 1. Motivation

UN-RFC 0004 offers no way to write privately to a person who has not
first invited you into a closed group. That leaves three gaps:

1. two people cannot exchange private messages;
2. nobody can privately contact a node's operator (e.g. about abuse);
3. a post awaiting approval in a moderated group has no private path to
   the moderators (the problem reserved for this number in UN-RFC 0000).

An inbox closes all three with one mechanism.

# 2. Inbox Groups

## 2.1 Manifest

An inbox is a group (UN-RFC 0004) whose manifest has `"type": "inbox"`.
All other manifest rules apply. Owners SHOULD set a short
`retention_days` (RECOMMENDED: 30); the owner keeps what they want to
keep in their own client.

## 2.2 Well-known Inbox of an Identity

The group named `inbox` owned by an identity is that identity's
**personal inbox**:

```
inbox@<fingerprint of the identity's key>
```

Because the Group ID is derived from the key, anyone who knows a
person's key knows where to write to them. A client MAY create a
personal inbox automatically when an identity is created.

## 2.3 Inbox Articles

An ordinary article in an inbox group MUST:

- have `Encrypted: sealedbox`;
- NOT have `From` or `Subject` in the outer header block;
- be signed (`Author-Key`, `Signature`) by a **fresh one-time key** that
  is used for no other article;
- have as body the b64 encoding (lines of at most 76 characters) of a
  sealed box (UN-RFC 0003 section 4.1) to the owner's key, containing
  the **inner article**.

The inner article is in article syntax and carries:

| Header             | Required | Value                                         |
|--------------------|----------|-----------------------------------------------|
| `From`             | yes      | Sender's display name                          |
| `Subject`          | yes      | Subject                                        |
| `Sender-Key`       | no       | Sender's real identity key                     |
| `Sender-Signature` | with `Sender-Key` | See below                             |
| `Reply-Inbox`      | no       | A Group ID where the sender wants replies      |
| `Content-Type`     | no       | Default `text/plain; charset=utf-8`            |

`Sender-Signature` is a signature by `Sender-Key` (UN-RFC 0003 section
3), purpose `UNSEENET-INBOX-SENDER-1`, over

```
group-id || 0x00 || outer-author-key-text || 0x00 || C_inner
```

where `C_inner` is the canonical form (UN-RFC 0002 section 3) of the
inner article without `Sender-Signature`. Binding the outer one-time key
and the group prevents the inner article from being lifted into another
message or another inbox.

An inner article without `Sender-Key` is anonymous. Clients MUST show
such messages as anonymous and MUST NOT display a `From` name as if it
were verified.

## 2.4 Node Rules

Nodes cannot check who may write to an inbox, because everybody may. A
node MUST reject an ordinary article in an inbox group unless it meets
section 2.3 as far as a node can see: `Encrypted: sealedbox`, no outer
`From`/`Subject`, and a valid outer signature and postage.

Owners of inboxes that receive spam SHOULD raise `min_pow` in the
manifest. Nodes MAY apply a higher minimum postage to inbox groups than
to other groups.

## 2.5 Replies

A reply is a new inbox article to the sender's `Reply-Inbox` (or to
`inbox@<fp of Sender-Key>` if that is absent), with `References` set to
the Message-ID of the article replied to.

# 3. Submissions to Moderated Groups

A moderated group's manifest MAY name an inbox in a new field:

| Field         | Type     | Meaning                                         |
|---------------|----------|-------------------------------------------------|
| `submissions` | Group ID | Inbox owned by the group owner or a moderator   |

To submit, a client builds the article for the moderated group exactly
as it would post it (signed, with postage and Message-ID), and sends it
as the **body** of an inbox article to `submissions`, with
`Content-Type: message/unseenet` in the inner headers.

The moderator approves by adding `Approved-By` and `Approval` (UN-RFC
0004 section 5) and posting the original article to the group. Its
Message-ID is unchanged, so replies and references made before approval
remain valid. Rejection needs no message, but a moderator MAY reply.

This replaces the reservation of UN-RFC 0009 for a moderation queue.

# 4. Local Groups

A manifest MAY contain:

| Field   | Type    | Default | Meaning                                |
|---------|---------|---------|----------------------------------------|
| `local` | boolean | `false` | The group exists on one node only      |

For a local group a node:

- MUST NOT offer its manifest or articles to peers;
- MUST reject its manifest and articles when they arrive from a peer
  (as opposed to from a client);
- otherwise treats it like any group of its type.

Local groups are for things that belong to one node, such as its
operator's inbox (UN-RFC 0011), a node's own announcements, or a group
for the people using one node. They correspond to the local hierarchies
and `Distribution: local` of Usenet.

`local` cannot be changed by a later manifest (UN-RFC 0004 section 4,
step 4, is extended accordingly).

# 5. Changes to Other Documents

- UN-RFC 0002 section 2.3: `Sender-Key`, `Sender-Signature` and
  `Reply-Inbox` appear only in inner articles and are listed there.
- UN-RFC 0003 section 3: purpose `UNSEENET-INBOX-SENDER-1` is added.
- UN-RFC 0004 section 2: type `inbox` is added; section 3.1: fields
  `submissions` and `local` are added.
- UN-RFC 0005 section 5.2: local groups are never queued for peers.

# 6. Security and Privacy Considerations

- **What a node sees:** that an inbox received a message of a certain
  size at a certain time. It does not see the content, the sender (the
  outer key is used once), or whether a sender identified themselves.
- **Timing:** a reply sent soon after a message arrives may let an
  observer of several nodes link the two. Clients MAY delay replies.
- **Deniability:** a message with `Sender-Key` is provably from that
  sender to anyone the owner shows it to. Senders who need deniability
  should omit `Sender-Key`.
- **No forward secrecy:** if an owner's key is compromised, all stored
  messages to it can be decrypted. Owners SHOULD keep inbox retention short.
- **Spam:** an inbox is open by design. Postage is the defense; clients
  SHOULD also let owners ignore messages without `Sender-Key` or from
  unknown keys.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
