```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0042                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0000, 0004, 0030

                    Unseenet: Editing Posts (Supersedes)
```

# Abstract

Today an author can only withdraw a post (UN-RFC 0004 section 7), not
correct it. Old Usenet had `Supersedes`: a new version that replaces
the old one in one step. This document adds it for Unseenet. An edit is
an ordinary article by the same author with a `Supersedes` header that
names every earlier version; nodes withdraw those versions as if they
had been cancelled, and clients show the newest version in the old
one's place in the thread, marked as edited. Signatures stay: each
version is a signed article of its own, and only its author can replace
it.

# 1. Motivation

People make mistakes: a typo, a wrong link, a sentence that says more
than they meant. Withdrawing and posting again moves the post to the end
of the thread and leaves replies pointing at nothing. Chat networks let
people edit, and gateways already import edits from Matrix as new lines
that refer to the old one (UN-RFC 0037 section 4.4); readers then see
both.

Signed articles cannot change, so an edit is a new article. What needs
defining is how nodes and clients link it to the article it replaces.

# 2. The Supersedes Header

```
Supersedes: <v2@example> <v1@example>
```

An article with `Supersedes` is an **edit**. The header lists the
Message-IDs of **every earlier version** of the post, the newest first,
separated by spaces: an edit of an edit names both versions before it.
At most 32 Message-IDs; a post can therefore be edited 32 times.

Listing every version, rather than only the one before as Usenet does,
means a node or client that receives the versions out of order, or
never sees some of them, still knows which articles the newest one
replaces and which replies belong under it.

An edit MUST:

1. be in the same group as the versions it names;
2. have the same `Author-Key` as each of them (section 4.1);
3. not be a control article, and name no control article;
4. have the same kind as the versions it names (UN-RFC 0028 section 3):
   a chat line is edited into a chat line, a post into a post;
5. have the same `References` as the first version, so that it stands
   in the same place in its thread (section 5.1);
6. not name itself, and name no Message-ID twice.

The edit MAY change the subject and the body, and anything else the
author may set.

An edit is permitted, carries postage and is accepted like any article
in its group (UN-RFC 0004 section 5, UN-RFC 0006): in a moderated group
it needs a new approval, and in a channel a comment can be edited only
while its thread is open for comments (UN-RFC 0030). Otherwise an edit
would get round moderation or a closed thread.

In closed groups `Supersedes` is in the **outer** article, where nodes
can read it, like a cancel's `Control` header (UN-RFC 0004 section 7.5).

Inboxes (UN-RFC 0009) are left out for now: a sealed article does not
show its sender to the node, so a node cannot check that an edit comes
from the same author. A private post cannot be edited.

# 3. Nodes

## 3.1 Accepting an Edit

A node checks an edit as any article, and then for each Message-ID in
`Supersedes`:

- if it holds that article, and it is **not** by the same author, in
  the same group and of the same kind, or it is a control article, the
  node MUST reject the edit (`441 permission`);
- if it holds that article and it is valid to replace, it withdraws it
  as for a valid cancel (UN-RFC 0004 section 7.2): it SHOULD delete it
  and MUST NOT forward it afterwards;
- if it does not hold it, it remembers the edit as a **pending
  supersede** for that Message-ID, as a pending cancel, and refuses the
  article if it arrives later and the edit is valid for it.

The edit itself is stored and forwarded like any article.

## 3.2 Threads and Comments

A node that needs a thread's root - for comments in channels (UN-RFC
0030 section 4) - and finds that the root was replaced by an edit uses
the edit as the root. It counts `comment_days` from the `Date` of the
**earliest** version it has known, so that editing a thread's first
post does not reopen its comments. A node that has known only the edit
counts from the edit's `Date`.

## 3.3 Archives

An archive node (UN-RFC 0012) treats a replaced version as a cancelled
article (UN-RFC 0027 section 7.2).

# 4. Clients

## 4.1 Checking

A client MUST check an edit itself before acting on it, as it does for
cancels (UN-RFC 0004 section 7.3): signature, same group, same author,
same kind, no control articles. An edit that fails is shown as an
ordinary post and replaces nothing. A node is not trusted for this:
otherwise a misbehaving node could replace other people's posts in its
readers' caches.

## 4.2 Showing

A client that holds a valid edit:

- shows **only the newest version**, in the place of the first one in
  its thread, and does not show the replaced versions as posts;
- marks it as edited, with the time of the newest version, for example
  "(edited 21:58)";
- shows replies to **any** version under the newest one (section 5.1);
- MAY let the user see the earlier versions **it has itself received**.
  It does not fetch them, and nodes have withdrawn them.

When a client receives a version older than one it already shows, it
keeps the newer one.

A valid cancel (UN-RFC 0004 section 7) of the version shown withdraws
the post: the client drops the earlier versions it holds as well, or
they would be shown again. Nodes have withdrawn them already.

## 4.3 Editing

A client SHOULD let its user edit their own posts and chat lines. It
opens the newest version's text, and posts the edit with `Supersedes`
naming that version and every version it names, and with the first
version's `References`.

Before sending, a client MUST make clear that editing is best effort
in the same way as withdrawing (UN-RFC 0004 section 7.4): people may
already have read, quoted or kept the earlier version.

A client sends mention notices (UN-RFC 0032) only for people the edit
mentions and no earlier version did.

# 5. Threading

## 5.1 Replies to Earlier Versions

Replies name the version their writer saw, in `References`. A client
treats a Message-ID that an edit replaces as the newest version
wherever it appears in `References`: a reply to the first version is
shown under the newest, and so is a reply to any version in between.
Replies are never changed; only how they are shown.

## 5.2 Several Edits at Once

An author who edits the same post twice from two devices may create
two edits that both name the same earlier version. A client shows the
one with the later `Date` (and on a tie, the lower Message-ID), and
treats the other as a replaced version too. Nodes keep both, since each
is a valid edit of the earlier one.

# 6. Gateways

A gateway MAY import an edit from another network as an Unseenet edit
when it posted the edited message itself, since it is then the author
of both (UN-RFC 0037 section 4.4 imports edits as new lines today). A
gateway that exports to a network with edits MAY export an Unseenet
edit as an edit there. Exporting to Usenet, a gateway writes only the
first Message-ID of `Supersedes`, as RFC 5536 allows one.

# 7. Security and Privacy Considerations

- **Bait and switch.** An author can make readers agree with one text
  and then change it. The "edited" mark (section 4.2) and the earlier
  versions a client has itself received are the defence; a reply that
  quotes the earlier text keeps it. This is the same risk as withdrawing
  and posting again, made visible.
- **Nobody else can edit.** Only the author's key can replace a version;
  an edit by another key is rejected by nodes and ignored by clients.
  Moderators withdraw, they do not edit: changing someone's words is not
  the same as removing them.
- **Best effort.** As with cancels, people, clients and nodes that do
  not follow this document, and archives, may keep earlier versions.
- **Closed groups.** `Supersedes` shows the nodes that an author edited
  a post and which one, as a cancel does; the content stays encrypted.
- **Scale.** An edit costs every node what a post costs, plus a lookup
  per Message-ID in `Supersedes` (at most 32) and, for versions not yet
  seen, a pending entry kept as long as a pending cancel. It adds
  nothing per identity: the limit of 32 versions bounds what one post
  can cost, and postage bounds how often anyone posts.

# 8. Rationale

- **Why replace and not keep every version?** Most edits fix a mistake
  that the author does not want kept - a wrong address, a name. Keeping
  every version on every node would make that impossible and cost
  storage. Withdrawing is what a cancel already does, so nodes need
  nothing new beyond linking the versions.
- **Why only the author?** A moderator who changes a post puts words in
  someone's signed name. Moderators can withdraw (UN-RFC 0004 section 7)
  and say why.
- **Why list every version?** So that the order in which articles
  arrive does not matter (section 2), and replies to any version can be
  threaded without the versions in between.
- **Why 32?** Enough for any real correction; a small, fixed bound on
  what one post can make a node remember.
- **Why not inboxes?** A node cannot see the sender of a sealed article.
  A later document can let the recipient's client check edits of
  private posts, since only it can open them.

# 9. Changes to Other Documents

- **UN-RFC 0004** section 7: an edit withdraws the versions it names
  as a cancel would, by their author only (section 3.1).
- **UN-RFC 0030** section 4: a replaced thread root is found through its
  edit, and `comment_days` counts from the earliest version (section
  3.2).
- **UN-RFC 0000** section 6: 0042 is added to the index.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
