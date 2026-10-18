```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0033                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0004, 0012, 0017, 0027

                   Unseenet: Pinned Posts
```

# Abstract

Every article in a group expires when it is older than the group's
window (UN-RFC 0012), so a group cannot keep a welcome post, a FAQ or
"read this first" for longer than its `retention_days`. This document
lets the owner and moderators of a group **pin** a few articles. A pin
is a signed control article; pinned articles become part of the group's
state, so nodes keep them and new nodes receive them, and clients show
them at the top of the group, in the threads view and in the chat view.

# 1. Motivation

Sticky threads in forums and pinned messages in chat programs are
familiar to almost everyone who uses a discussion system. On Unseenet
there are only two ways to get something like it today, and both are
poor (unseenet #193):

- **`retention_days = 0`** keeps everything in the group, not just the
  few posts that matter, and asks every node to store the group forever.
- **Reposting** before the post expires, as the project does for its
  lists (UN-RFC 0018, 0020), gives the post a new Message-ID, so it
  loses its thread, its replies and the links that point to it.

Pinning should keep a handful of articles, chosen by the people who
already have authority over the group, without giving anyone a way to
make nodes store more than a small, fixed amount per group.

# 2. Terms

- **Pin:** an article with `Control: pin <message-id>`.
- **Unpin:** an article with `Control: unpin <message-id>`.
- **Target:** the article a pin or unpin names.
- **Pin in force:** a pin that counts, as worked out in section 4.
- **Pinned article:** the target of a pin in force.

# 3. Pin and Unpin Articles

A pin or unpin is an article (UN-RFC 0002) with:

- `Control: pin <message-id>` or `Control: unpin <message-id>`;
- `Newsgroups:` the group of the target;
- `Author-Key:` the owner's or a moderator's key;
- an empty body, or in open, moderated and channel groups a short note
  for readers (at most 256 characters), such as "Read this first".

Like cancels (UN-RFC 0004 section 7.5), pins and unpins are **never
encrypted**, also in closed groups: nodes must read the `Control`
header to keep the target. In a closed group the body MUST be empty.

A pin or unpin is **valid** when all of these hold:

1. It is in the same group as the target.
2. Its author is the owner or a moderator of the group according to
   the current manifest.
3. The target is not a control article.
4. The group is not an inbox or local group (UN-RFC 0009).

As with cancels, whether a pin is valid can only be decided once its
target is known; section 5.2 says what a node does before that.

Pins and unpins are control articles, so they cannot be cancelled
(UN-RFC 0004 section 7.1). A pin is undone with an unpin.

# 4. Which Pins Are in Force

## 4.1 Manifest Field

A manifest (UN-RFC 0004 section 3) MAY contain:

| Field      | Type    | Default | Meaning                              |
|------------|---------|---------|--------------------------------------|
| `max_pins` | integer | `5`     | How many pins may be in force (0-25) |

A value outside 0-25 makes the manifest invalid (UN-RFC 0004 section 4,
step 3). `0` turns pinning off for the group.

## 4.2 Working It Out

For each target, only the **latest** valid pin or unpin counts: the one
with the latest `Date`, and of equal dates the one whose Message-ID is
greatest in code point order. The target is pinned if that article is
a pin. Then:

1. Pins whose author is no longer owner or moderator in the current
   manifest are not in force. Removing a moderator therefore removes
   their pins; a client SHOULD tell the owner which pins will go and
   offer to pin them again under the owner's key.
2. Pins whose target has been withdrawn with a valid cancel are not in
   force.
3. Of the rest, the `max_pins` latest (same order as above) are in
   force; older ones are not.

Every node and client that holds the same articles comes to the same
result. A pin that is not in force stays stored like any article and
expires with the group's window.

# 5. Nodes

## 5.1 Group State

UN-RFC 0017 section 2 is extended. The state of a group also includes:

- the pins in force, and the latest unpin of each target that has one
  and is still inside the window;
- the pinned articles;
- in a closed group, carried copies (section 6) that are pinned.

A node MUST NOT expire state articles (UN-RFC 0017 section 2). When an
article leaves the state, because it was unpinned, because a newer pin
pushed it past `max_pins`, or because its pinner lost their role, it
expires normally (UN-RFC 0012) and may disappear at once if it is older
than the window.

## 5.2 Accepting Pins and Targets

- A node MUST reject a pin or unpin that is not valid (section 3) when
  it holds the target.
- A node that receives a pin before its target SHOULD remember it as a
  *pending* pin, as it does with pending cancels (UN-RFC 0004 section
  7.2), and MAY forget it after the group's window.
- UN-RFC 0012 section 3 is amended: a node MUST NOT reject an article
  for being older than the window if it holds a pin in force, or a
  pending pin that would be in force, naming that article. It forwards
  such an article to its peers as usual.

## 5.3 NEWNEWS

UN-RFC 0017 section 3, step 1, is refined. A node lists a group's
state in this order: manifests, key updates by ascending epoch, pins
and unpins, then pinned articles. A node that fetches in order thus has
each pin before its target and accepts the target even if it is old.

## 5.4 Blobs

UN-RFC 0027 section 7.1 is amended: a node SHOULD keep a blob as long
as a pinned article references it, also beyond its own blob retention.
A node MAY still refuse to keep blobs that would break its quotas
(UN-RFC 0027 section 8); a client then shows the attachment as no
longer available.

# 6. Closed Groups

A pinned article of an earlier epoch is a problem in a closed group:
members who joined later never got that epoch's secret and cannot read
it, and after a key update with `closes_previous` nodes reject articles
of earlier epochs altogether (UN-RFC 0004 section 6.5).

The pinning client therefore **carries** the article into the current
epoch instead of pinning the original:

1. It posts a new encrypted article in the current epoch whose inner
   block is the original's inner block, with these inner headers added:

   | Header           | Value                                      |
   |------------------|--------------------------------------------|
   | `Carried-From`   | Message-ID of the original                 |
   | `Carried-Author` | the original's `Author-Key`                |
   | `Carried-Date`   | the original's `Date`                      |

2. It pins the carried copy, not the original.

When a new epoch starts, the owner's client SHOULD carry each pinned
article again into the new epoch, pin the new copy and unpin the old
one, so pins survive rotation. A client that removes a member MUST NOT
carry articles written by the removed member unless the owner chooses
to.

The carried copy is signed by the carrier, not by the original author:
the carrier vouches that it is a faithful copy, and nobody else can
check it. Clients MUST show a carried copy as written by its original
author **as stated by** the carrier (for example "pinned by @lorensen,
originally by @sonia"), never as if the original author had signed it.

A pin in the current epoch of an article in the current epoch needs no
carrying.

# 7. Clients

## 7.1 Pinning

- A client SHOULD let the owner and moderators of a group pin and unpin
  articles. Following the principle that write controls are only
  offered where they work, it MUST NOT offer pinning to others, or in
  groups with `max_pins` 0.
- Pinning is a rare action: the reference TUI offers it from the
  command palette and the article's menu, not as a shortcut; the web
  client from the message menu.
- When the group already has `max_pins` pins in force, the client MUST
  tell the user which pin will stop counting, and offer to unpin
  another one instead.
- Before unpinning an article older than the group's window, the client
  MUST say that the article will then disappear from nodes.
- A client MUST check pins itself (section 3, section 4), as it does for
  manifests and cancels; a node is not trusted for this.

## 7.2 Showing in the Threads View

- Pinned articles are shown in a **Pinned** section above the thread
  list, newest pin first, with a pin mark: 📌, or `[P]` where emoji do
  not render (UN-RFC 0031). The thread stays in its place in the tree
  as well, with the pinned article marked.
- A pinned reply is shown with the subject of its thread, and opening it
  opens the thread at that article.
- A pin's note, if any, is shown with the pinned article.
- The section can be collapsed, and a client SHOULD remember that per
  group.

## 7.3 Showing in the Chat View

- A **pinned bar** above the chat shows the newest pinned line or post
  with its first line, its author and, if there are more, a count such
  as "1/3". Selecting the bar moves to the next pin; a client SHOULD
  also offer a list of all pins.
- Choosing a pin jumps to it in the chat history. If the lines around
  it have expired, the client shows it with a note that earlier
  messages are no longer available.
- Pinned lines are also marked in the stream.
- The bar can be hidden, and a client SHOULD remember that per group.

## 7.4 Notifications

A client MAY mark a group as having a new pin since the user last read
it. It SHOULD NOT send any notice outside the group for a pin.

# 8. Changes to Other Documents

- UN-RFC 0004 section 3.1: the manifest field `max_pins` (section 4.1).
- UN-RFC 0012 section 3: pinned articles are exempt from the window
  (section 5.2).
- UN-RFC 0017 section 2 and 3: pins and pinned articles are part of the
  state and are listed after key updates (sections 5.1, 5.3).
- UN-RFC 0027 section 7.1: blobs of pinned articles are kept with them
  (section 5.4).

# 9. Security and Privacy Considerations

- **Storage:** a group can make nodes keep at most 25 articles beyond
  the window, plus their unpins and blobs. Articles keep their normal
  size limit, and blobs their quotas. Pinning is no way to store more
  than that.
- **Authority:** only the owner and the group's current moderators can
  pin. A removed moderator's pins stop counting at once (section 4.2),
  so a rogue moderator cannot leave pins behind.
- **Closed groups:** a pin shows the nodes that the owner or a
  moderator pinned some article, and which one by Message-ID, as a
  cancel does. It says nothing about the content. Carried copies rest
  on the carrier's word (section 6); clients must say so.
- **Old content:** an article that comes back through a pin is shown
  as pinned, with its original date, so readers are not misled into
  thinking it is new.
- **Withdrawn posts:** a cancel still wins: a withdrawn article is not
  kept by a pin.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
