```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0017                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0005, 0012, 0027

           Unseenet: Catching Up by Pull, and Group State
```

# Abstract

Push feeds (UN-RFC 0005 section 5.2) carry new articles between peers as
they arrive, but a node that is new, or was down, never gets what it
missed. This document specifies how a node catches up by **pulling**
with `NEWNEWS` and `ARTICLE`, and defines a group's **state** - the
articles a node needs before it can accept anything else in the group -
which nodes keep regardless of age and list first, so that a node
catching up can accept what follows.

# 1. Motivation

UN-RFC 0005 section 5.3 names pull as the way to catch up but leaves
three problems open:

1. **Order.** A node rejects posts in a group it does not carry, and
   encrypted posts whose epoch it does not know. `NEWNEWS` lists
   articles by when they arrived, so a group's manifest, created long
   ago, falls outside the window a node asks for.
2. **Expiry.** Key updates of closed groups are ordinary articles and
   expire with the group's retention. After that, a node that joins
   cannot learn the group's current epoch and rejects every encrypted
   post in it - also those pushed to it.
3. **Where to start.** A node pulling for the first time does not know
   how far back to ask.

# 2. Group State

The **state** of a group is:

- its current manifest (UN-RFC 0004 section 3.2);
- in a closed group, the `key-update` articles of the current epoch and
  of the epoch before it (the epochs whose articles a node still accepts,
  UN-RFC 0004 section 6.5);
- the group's **kept articles** (section 2.1), when another document
  defines them for the group.

A node MUST NOT expire state articles, whatever the group's retention.
Other articles expire as before (UN-RFC 0012). When an article stops
being part of the state - a newer manifest, a newer epoch, a kept
article that is no longer kept - it expires normally, and may disappear
at once if it is older than the window.

## 2.1 Kept Articles

Some articles should outlive the group's window: a pinned post (UN-RFC
0033), the current version of a page (UN-RFC 0035). This section says
once how nodes keep them; each such document only says which articles
are kept, and refers here. It is the one definition of content that
does not expire, so that other uses build on it rather than adding their
own.

A document that defines kept articles MUST give:

1. **Which.** A rule that picks the kept articles from the articles a
   node holds and the group's current manifest alone, so that every node
   and client holding the same articles comes to the same result.
   Articles that make others kept, such as pins, are **markers**; the
   articles they name are **targets**. A marker MAY itself be kept.
2. **How many.** A manifest field that limits how many targets can be
   kept at once, with a default and a maximum (section 2.2).
3. **Order.** Where its kinds of articles go in the listing of section 3.

Kept articles follow these rules:

- **Not expired** while kept (above).
- **Accepted when old.** UN-RFC 0012 section 3 is amended: a node MUST
  NOT reject an article for being older than the window if, with the
  articles it holds, it would be kept, or a marker it holds or remembers
  as pending names it. It forwards such an article to its peers as usual,
  so a new node gets the whole state.
- **Pending markers.** A node that receives a marker before its target
  cannot yet tell whether it is valid. It SHOULD remember it as pending,
  as with cancels (UN-RFC 0004 section 7.2), and MAY forget it after the
  group's window.
- **Blobs.** UN-RFC 0027 section 7.1 is amended: a node SHOULD keep a
  blob as long as a kept article references it, also beyond its own blob
  retention. The blob does not become a state article itself; a node MAY
  still refuse blobs as UN-RFC 0027 sections 7.3 and 8 allow, and a
  client then shows the attachment as not available.
- **In closed groups** the kept articles are the encrypted articles as
  carried; markers MUST be readable by nodes (unencrypted), as cancels
  are (UN-RFC 0004 section 7.5).

## 2.2 Limits

One set of limits applies to everything kept in a group, whatever
defines it:

| Limit | Value |
|---|---|
| Targets kept per kind | what the kind's document derives from its manifest field (for example `max_pins`, 0-25; twice `max_pages`, a current and a previous version of up to 100 pages) |
| Targets kept in one group, all kinds | 256 |
| Blobs of kept articles in one group | 8 MiB |

A node MUST NOT keep more than these. When the targets of one kind pass
its manifest field, the oldest by the kind's own order leave first; when
a group passes 256 targets, a node does not keep the new ones beyond the
window. A node MUST reject an article that would take the blobs of a
group's kept articles above 8 MiB, counted against the kept articles it
holds when the article arrives, and MAY set a lower limit. The defaults
and maxima of a document's manifest field MUST fit within these.

Nothing else is charged for keeping: kept articles pay the postage of
any article of their size (UN-RFC 0006, with UN-RFC 0027 section 4.5 for
blobs).

# 3. NEWNEWS

UN-RFC 0005 section 5.3 is refined. A node answering

```
NEWNEWS <wildmat> <yyyymmdd> <hhmmss> GMT
```

MUST list, in this order:

1. the Message-IDs of the **state** of every group it carries that
   matches the wildmat, whatever their age, manifests before key
   updates, key updates by ascending epoch, then kept articles (section
   2.1) in the order their documents give, every marker before the
   targets it names;
2. the Message-IDs of other articles in matching groups that it
   **received** at or after the given time, in the order it received
   them;
3. the Message-IDs of `rmgroup` articles (UN-RFC 0013) for matching
   groups that it accepted at or after the given time.

Each Message-ID is listed at most once. Because state comes first, a
node that fetches and accepts the list in order has every group's state
before its posts. `ARTICLE` with the Message-ID of an `rmgroup` article
MUST return it.

`NEWNEWS` is a reader command; a node MUST answer it without peer
authentication.

# 4. Pulling

A node pulls from a peer as follows:

1. Connect. If it has the peer's node key (UN-RFC 0016), it SHOULD
   authenticate: that checks it reached the node it meant (UN-RFC 0016
   section 4, step 3), and a node MUST abort the pull if that check
   fails. If the peer does not accept its key, the node MAY continue as
   an ordinary reader.
2. Send `DATE` and remember the peer's time `T`.
3. Send `NEWNEWS <wildmat> <since> GMT`, where `since` is:
   - for the first pull from that peer, `T` minus the node's own
     retention period (UN-RFC 0012 replication window);
   - otherwise the `T` of the last complete pull, minus a margin
     (RECOMMENDED: 15 minutes), because articles may arrive at the peer
     while it answers.

   Times are always the peer's clock, so the clocks need not agree.
4. Fetch, with `ARTICLE <id>`, every listed Message-ID not in its
   history, in the order listed.
5. Remove the `Path` and `Xref` headers that the peer adds for
   newsreaders (UN-RFC 0005 section 3), and accept each article as if a
   peer had pushed it: same checks, same history, and queued for the
   node's other peers but not back to the one it came from.
6. Add the Message-ID of every article it rejects to its history too,
   so that it is not fetched again.
7. If it fetched everything listed, store `T` as the time of the last
   complete pull. A node MAY limit how many articles it fetches per pull;
   it then keeps the old time and continues at the next pull.

A node SHOULD pull from each peer when it starts (after a random delay,
so that peers are not all asked at once) and periodically
(RECOMMENDED: every hour). Push remains the way new articles travel;
pull fills the gaps.

The wildmat selects the groups the node wants. A node SHOULD ask for
`*` or for whole hierarchies rather than single groups, since the
wildmat tells the peer what it is interested in.

# 5. Leaf Nodes

Because pulling uses only reader commands, a node can catch up from any
node, also one that does not list it as a peer. A small personal node
can so carry a set of groups from one or more public nodes without asking
their operators for anything. To get its own users' posts out, it still
needs a peer that accepts pushes from it (UN-RFC 0016).

# 6. Security Considerations

- **Interest.** The wildmat in `NEWNEWS` shows a peer which groups a node
  carries. Section 4 recommends broad patterns.
- **Cost.** Anyone can make a node list its state and recent IDs. Listing
  IDs is cheap; fetching articles is what any reader can already do.
  Nodes MAY limit `NEWNEWS` and `ARTICLE` per connection (UN-RFC 0005
  section 6).
- **Authority.** Pulled articles are checked exactly like pushed ones:
  signatures, postage, posting rules (UN-RFC 0004 section 5) and dates. Pulling from a malicious
  node can deliver nothing that pushing could not.
- **Removals.** Listing `rmgroup` articles lets a node that missed a
  removal while it was down learn about it and delete the group.
- **Local groups** (UN-RFC 0009) appear in a node's `NEWNEWS` like any
  other group, but are rejected by a puller like any article from a peer.
- **Kept content.** Kept articles are content nodes hold indefinitely.
  The limits of section 2.2 bound what one group can make every node
  keep, whatever document defines it; only owners and moderators can
  write the markers that pick it (UN-RFC 0033, 0035). Old articles
  that are not kept still cannot circulate: a node accepts an old
  article only if it would be kept.

# 7. Changes to Other Documents

- **UN-RFC 0012** section 3: an old article is accepted when it would be
  kept (section 2.1).
- **UN-RFC 0027** section 7.1: blobs of kept articles are kept with them
  (section 2.1). Its sentence "Blobs are never part of a group's state"
  stays true: they are kept, not state.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
