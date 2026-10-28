```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0032                                              October 2026
Category: Standards Track
Status: Draft
Implemented: unseenet 0.4.0
Updates: 0009, 0019

                   Unseenet: Mention Notices
```

# Abstract

A post can name a person by a certified name such as `@lorensen`
(UN-RFC 0019). The named person's client notices this only in groups
it follows. This document lets the writer's client also send a short
**mention notice** to the named person's inbox, so that they learn of
it in a group they do not follow. A notice points to the post; it does
not copy it. Nodes see an ordinary inbox article and learn nothing new.

# 1. Motivation

Mentions are worked out by each client in the posts it has fetched
(unseenet #109): a post naming `@sonia` in `dk.snak` is marked for
Sonia only if she follows `dk.snak`. Often the point of naming someone
is to draw in a person who does not read the group.

A notice must not become a way to fill inboxes, to make a post look
as if it named someone it does not, or to tell anybody more than the
post itself already says. Hence the rules below: few notices per post,
normal postage for each, and a receiver that checks the post before it
shows anything.

# 2. Terms

- **Mention:** a certified name of the receiver (UN-RFC 0019 section
  4: `@name`, `sub@name`, `@domain` or `name@domain`) written in the
  `Subject` or body of a post. Display names and petnames are not
  mentions.
- **Mentioned post:** the article that contains the mention.
- **Notice:** the inbox article of section 3.

# 3. The Notice

A notice is an inbox article (UN-RFC 0009 section 2.3) to the
receiver's well-known inbox (`inbox@<fp>`, UN-RFC 0009 section 2.2).
Its inner article carries:

| Header          | Required | Value                                              |
|-----------------|----------|----------------------------------------------------|
| `From`          | yes      | The writer's display name                          |
| `Subject`       | yes      | The mentioned post's `Subject`, or `Mention` for a chat line |
| `Sender-Key`    | yes      | The writer's key: the mentioned post's `Author-Key` |
| `Sender-Signature` | yes   | As UN-RFC 0009 section 2.3                         |
| `Content-Type`  | yes      | `text/x-unseenet-mention; charset=utf-8`           |
| `Message-Kind`  | yes      | `post` (UN-RFC 0028)                               |
| `Mention-Group` | yes      | Group ID of the mentioned post                     |
| `Mention-Of`    | yes      | Message-ID of the mentioned post                   |

The body is one short line for clients that do not know this type, for
example:

```
Andreas mentioned you in !dk.snak@ph5f: Mit marsvin hoster
```

The body MUST NOT contain the mentioned post's text. A notice is never
anonymous: the receiver needs `Sender-Key` to check it (section 5).

# 4. Writer's Client

## 4.1 When to Send

After the mentioned post has been accepted by a node (it has its
Message-ID), the writer's client MAY send one notice to each person the
post mentions. It:

- sends notices only for mentions it resolved to a key (UN-RFC 0019
  section 8.3), and for no other name;
- MUST NOT send more than **5** notices for one post. If a post
  mentions more people, the user chooses which 5 get one; the others
  are mentioned in the text only;
- MUST NOT send a notice to the writer's own keys, for a post in a
  closed group (its members follow it, and a notice would tell a
  non-member that the group exists), in an inbox group, or for a
  private post;
- MUST NOT send a second notice for the same post and person, also
  when the post is sent again;
- pays the inbox's postage for each notice, as for any inbox article;
- SHOULD wait a random time (up to a few minutes) before sending, so
  that notices do not arrive in step with the post.

## 4.2 Choice

Sending notices is **on by default**. The client SHOULD show, before a
post is sent, who will get a notice, and MUST let the user turn
notices off for that post and in general.

## 4.3 Posts to Moderated Groups

A post submitted to a moderated group (UN-RFC 0009 section 3) is not in
the group until a moderator approves it, and its author may not be
online then. So the notices travel with the submission:

1. When submitting, the writer's client builds each notice of section 3
   as a complete inbox article (sealed to the receiver, signed, with the
   postage of the receiver's inbox), with `Mention-Of` set to the
   submitted article's Message-ID, which approval does not change.
2. It sends them, in one **notice bundle**, to the same inboxes as the
   submission: an inbox article whose inner article has

   | Header         | Value                                      |
   |----------------|--------------------------------------------|
   | `Content-Type` | `application/x-unseenet-notices`           |
   | `Notices-For`  | Message-ID of the submitted article        |
   | `Sender-Key`   | Required: the submitted article's author   |

   and as body each notice in base64 (lines of at most 76 characters),
   separated by an empty line. At most 5 notices.
3. A moderator's client that approves the submission posts the notices
   of a bundle whose `Sender-Key` is the submitted article's
   `Author-Key`, after a random wait as in section 4.1. It MUST NOT post
   anything from a bundle that is not an inbox article to a personal
   inbox (UN-RFC 0009 section 2.2), and MUST NOT post a bundle's notices
   if it rejects the submission. If several moderators approve, the node
   refuses the second copies as duplicates.

The moderator cannot read the notices, and cannot change them without
breaking the author's signature. A bundle is not shown as a private
post.

# 5. Receiver's Client

A client that receives a notice:

1. MUST discard it if `Sender-Key` is missing or its
   `Sender-Signature` does not verify, if the user ignores the sender
   (unseenet #72), or if the user has turned notices off;
2. MUST discard it if it already has the mentioned post from a group
   it follows: that post is marked there already (no double mention);
3. SHOULD fetch the mentioned post (`ARTICLE <Mention-Of>` from a node
   that carries `Mention-Group`) and MUST discard the notice if the
   post's `Author-Key` is not the notice's `Sender-Key`, or if the post
   does not mention one of the receiver's certified names;
4. if the post cannot be fetched (yet), MAY keep the notice and try
   again later, and MUST NOT show it as a checked mention until then.

A checked notice is shown with the other mentions (*For you*, ♦), not
as an ordinary private post, with a way to open the post. If the user
does not follow the group, the client shows the group and asks before
subscribing, as for a `#group` reference (unseenet #172).

A client that does not implement this document shows a notice as an
ordinary private post with its one-line body, which is still useful.

# 6. Nodes and Gateways

Nothing changes for nodes: a notice is an ordinary inbox article and
is accepted under UN-RFC 0009 section 2.4.

Gateways (UN-RFC 0023, 0026) MUST NOT turn mentions in articles from
other networks into notices, and MUST NOT carry notices to other
networks.

# 7. Changes to Other Documents

- UN-RFC 0009 section 2.3: `Mention-Group` and `Mention-Of` are added to
  the optional inner headers, with the content type of section 3.
- UN-RFC 0019 section 8: a client MAY send and receive mention notices
  as described here.
- UN-RFC 0009 section 3: a submission MAY be followed by a notice bundle
  (section 4.3), which a moderator posts on approval.

# 8. Security and Privacy Considerations

- **What a node learns:** nothing new. The notice is sealed to the
  receiver and signed outside by a one-time key, like every inbox
  article. A node that sees inbox articles soon after a post could
  guess that the post mentions those inboxes' owners; the post says so
  in clear text anyway, and the random delay of section 4.1 makes the
  guess harder.
- **What the receiver learns:** that the writer's key wrote the post,
  which the signed post already shows. A notice for a post in a closed
  group is not allowed, so it never reveals such a group.
- **Spam and harassment:** at most 5 notices per post, postage for
  each, more expensive new keys (UN-RFC 0025), and the receiver's
  check (section 5) limit what one person can do. Notices from people
  the receiver ignores are dropped, and notices can be turned off.
- **False notices:** a notice for a post that does not exist, was
  written by someone else, or does not name the receiver is discarded
  after the check, so it cannot be used to draw people to arbitrary
  posts or groups.
- **Moderators:** a notice bundle tells a moderator whose inboxes the
  author will notify, which the post's text says anyway. A moderator can
  hold back the notices only by holding back the post.
- **Withdrawn posts:** if the mentioned post is withdrawn (UN-RFC 0004),
  the check fails and the notice is not shown, or is removed.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
