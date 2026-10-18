```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0028                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0009

          Unseenet: Chats and Letters in Private Messages
```

# Abstract

Private messages (UN-RFC 0009) are used in two ways: as a running chat
between two people, and as letters with a subject that are answered
with a quote, like posts in a discussion group. This document adds an
inner header that says which one a message is, so that clients can show
them apart and let people choose. The header is inside the sealed box;
nodes cannot see it.

# 1. Motivation

Chat and discussion are different ways of talking. Unseenet keeps both
for groups (chat groups and discussion groups); private messages should
offer both too. Without a marker, one client shows every private
message as a chat and another shows every one as a letter, and a user
cannot write the other kind on purpose.

# 2. The Message-Kind Header

An inner article (UN-RFC 0009 section 2.3) MAY carry:

| Header         | Required | Value                 |
|----------------|----------|-----------------------|
| `Message-Kind` | no       | `chat` or `letter`    |

- **`letter`**: a message with a subject, meant to be read on its own
  and answered with a quote. This is the default: an inner article
  without `Message-Kind`, or with a value a client does not know, is a
  letter.
- **`chat`**: a short message in a running conversation. Its `Subject`
  header MUST be present (UN-RFC 0009 requires it) and SHOULD be empty;
  receivers MUST NOT depend on it.

A reply SHOULD have the same kind as the message it answers, but a
client MAY answer a chat with a letter or a letter with a chat.

`Message-Kind` is covered by `Sender-Signature`, like every other inner
header, so it cannot be changed in transit.

# 3. Clients

Clients SHOULD:

- show chats as a conversation per person, oldest first, without
  subjects;
- show letters like posts in a discussion group: a list with subjects,
  threaded by `References`, read one at a time, answered with a quote;
- let the user choose, wherever they can write to someone, between a
  chat and a letter.

Clients MAY show both kinds together, as long as the kind of each
message is visible.

# 4. Changes to Other Documents

- UN-RFC 0009 section 2.3: `Message-Kind` is added to the inner headers.

# 5. Security and Privacy Considerations

- **What a node sees:** nothing new. The header is inside the sealed
  box, so a node cannot tell a chat from a letter by its headers.
- **Size and timing:** chats are usually short and come in bursts,
  letters are usually longer. An observer who sees an inbox receive many
  small messages close together may guess that they are chats. This was
  already true before this document; clients MAY pad messages to reduce
  it.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
