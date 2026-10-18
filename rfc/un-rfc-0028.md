```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0028                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0002, 0004, 0008, 0009

                 Unseenet: Chats and Letters
```

# Abstract

People talk in two ways on Unseenet: in a running **chat**, line by
line, and in **letters**: messages with a subject that are read on
their own and answered with a quote, like Usenet posts. This document
gives every message a kind, so that clients can show the two apart and
let people choose. It applies the same way to posts in groups and to
private messages. It also lets the owner of a group say which kinds the
group takes, and lets nodes enforce that where they can see it.

# 1. Motivation

Unseenet keeps both ways of talking on purpose: chat is quick, and
discussion with subjects, threads and quotes is what Usenet was made
for and what most of today's networks have lost. Until now, though,
"chat" was only a way of *showing* a group (UN-RFC 0008) or a
conversation. The messages themselves did not say how they were
written:

- A line written in a chat got a made-up subject (its first line), and
  shown as threads every line became a thread of its own.
- One client showed every private message as a chat and another showed
  every one as a letter, and nobody could write the other kind on
  purpose.
- A group owner could not say "this is a discussion group" and have it
  mean anything.

# 2. Terms

**Chat** (a chat line)
:   A short message in a running conversation. It has no subject. It is
    read in order with the lines around it.

**Letter**
:   A message meant to be read on its own: it has a subject, it can
    start a thread, and it is answered with a quote. In a group a
    letter is an ordinary post; in an inbox it is a private letter.

# 3. The Message-Kind Header

## 3.1 Value

```
Message-Kind: chat
Message-Kind: letter
```

The value is compared case-insensitively, after trimming white space.
A message **without** `Message-Kind`, or with a value a receiver does not
know, is a **letter**. Senders SHOULD always include the header.

## 3.2 Where It Goes

| Group type                      | Where `Message-Kind` is              |
|---------------------------------|---------------------------------------|
| open, moderated, channel        | the article's header block            |
| closed (UN-RFC 0004 section 6)  | the encrypted inner article           |
| inbox (UN-RFC 0009 section 2.3) | the sealed inner article              |

In closed groups and inboxes the header MUST NOT appear in the outer
article; there it is part of the content and only readers can see it.

Control articles (those with a `Control` header) have no kind; a
`Message-Kind` on a control article MUST be ignored. Data groups
(UN-RFC 0008, `"view": "data"`) carry articles for programs and do not
use kinds.

## 3.3 Subject

- A **letter** MUST have a non-empty `Subject`.
- A **chat** line has a `Subject` header like every message (UN-RFC
  0002 section 2.2, UN-RFC 0009 section 2.3), and its value SHOULD be
  empty. Senders MUST NOT make up a subject for a chat line, such as its
  first line.
- Receivers MUST NOT depend on the subject of a chat line. To show a
  chat line where a subject is expected (a list of posts), a client
  shows the start of its text instead, marked as a chat line.

## 3.4 Replies

A reply SHOULD have the kind of the message it answers. A client MAY
answer a chat line with a letter (to take something up properly) or a
letter with a chat line, where the group takes both kinds (section 4).
A chat line MAY carry `References`; clients SHOULD show it in the chat
in order all the same.

# 4. Which Kinds a Group Takes

## 4.1 Manifest Field

A manifest (UN-RFC 0004 section 3) MAY contain:

| Field   | Type             | Default                | Meaning                     |
|---------|------------------|------------------------|-----------------------------|
| `kinds` | array of strings | `["chat", "letter"]`   | The kinds the group takes   |

The array MUST be non-empty, MUST contain only `"chat"` and
`"letter"`, and MUST NOT repeat a value. A manifest that breaks this is
invalid (UN-RFC 0004 section 4, step 3). A later manifest MAY change
`kinds`; it applies to articles posted after it, not to articles a node
already holds.

Inbox groups always take both kinds; `kinds` in an inbox manifest MUST
be ignored.

## 4.2 Kinds and View

`view` (UN-RFC 0008) says how clients show a group by default;
`kinds` says what the group takes. They are independent, but owners
SHOULD keep them consistent:

| Kind of group             | `view`    | `kinds`                 |
|---------------------------|-----------|-------------------------|
| discussion                | `threads` | `["letter"]`            |
| chat                      | `chat`    | `["chat"]`              |
| both (the default)        | either    | `["chat", "letter"]`    |

# 5. Node Rules

In open, moderated and channel groups a node MUST reject an article
(UN-RFC 0002 section 5, the permission step) whose kind (section 3.1)
is not in the group's `kinds`, using the manifest that is current when
the article arrives. Control articles are exempt.

In closed groups and inboxes the kind is encrypted, and a node cannot
and MUST NOT try to enforce it. There, clients enforce `kinds`
(section 6).

A node that refuses an article for its kind SHOULD say so in its
response, so the client can tell the user.

# 6. Clients

## 6.1 Writing

- The chat input line writes chat lines; the compose window writes
  letters.
- A client MUST NOT offer to write a kind the group does not take, and
  MUST NOT post such an article to a closed group.
- Wherever a client lets a user write privately to someone, it SHOULD
  offer both: a chat with them and a letter to them.

## 6.2 Showing

- **Threads view:** letters as a thread tree, read one at a time.
  Chat lines are shown with a chat mark and the start of their text,
  and a client SHOULD keep consecutive chat lines together rather than
  as a thread each.
- **Chat view:** chat lines in order. Letters are shown as letters,
  with their subject, so they stand out from the lines around them.
- **Private messages:** chats per person, oldest first; letters like
  posts in a discussion group. A client MAY show both together, as long
  as the kind of each message is visible. A chat from someone the user
  has no conversation with MUST NOT be hidden; showing it among the
  letters, marked as a chat, is enough.
- In a closed group, articles of a kind the group does not take SHOULD
  be hidden, or marked, as the group's rules are not being followed.

The user's own choice of view per group (UN-RFC 0008) still applies:
it changes how a group is shown, never what kind a message is.

# 7. Gateways

A gateway (UN-RFC 0023) brings messages in as letters unless the other
network says otherwise; a network profile MAY map its own kinds (for
example short notes) to chat lines. When a chat line goes out to a
network that needs a subject, the gateway MAY use the start of its text
as the subject.

# 8. Changes to Other Documents

- UN-RFC 0002 section 2.3: `Message-Kind` is added to the optional
  headers; section 5: the permission step includes section 5 of this
  document.
- UN-RFC 0004 section 3.1: the field `kinds` is added; section 6: the
  encrypted inner article MAY carry `Message-Kind`.
- UN-RFC 0008 section 3.1: `view` is how a group is shown; what it
  takes is `kinds` in this document.
- UN-RFC 0009 section 2.3: `Message-Kind` is added to the inner headers.

# 9. Security and Privacy Considerations

- **Open groups:** the kind is in the clear, like the rest of the
  article. It says nothing that the text does not already show.
- **Closed groups and inboxes:** the kind is encrypted. A node cannot
  tell a chat line from a letter by its headers.
- **Size and timing:** chat lines are usually short and come in bursts,
  letters are longer. An observer of a closed group or an inbox may
  guess the kind from that pattern. This was already true before this
  document; clients MAY pad messages to reduce it.
- **Enforcement in closed groups** is up to the members' clients. A
  member with a modified client can post a kind the group does not
  take; the other clients hide or mark it (section 6.2), and the owner
  can remove the member.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
