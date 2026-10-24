```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0035                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0000, 0008, 0011, 0017, 0029, 0030, 0031, 0042, 0043

                   Unseenet: Pages, Sites and Books
```

# Abstract

This document lets a channel group be shown as a **site**: a small set
of static **pages** of Markdown with images, found by a path such as
`index` or `projects/ovos`, which readers browse in their client. Each
page is a signed article; a new version replaces the old one, and the
current version of every page is part of the group's state, so nodes
keep it however rarely the site changes. An identity may have a
personal site in the key-bound group `site@<fingerprint>`. Pages use
the safe Markdown of UN-RFC 0031 and the attachments of UN-RFC 0027:
no HTML, no scripts and nothing fetched from outside the network.
Sites are small by design, and node operators choose whether they
carry them.

A site with a `contents` page is a **book**: its pages have a reading
order, and readers may propose new versions of a page as comments. The
owner chooses whether editors accept proposals (`review`) or whether
readers may publish versions directly (`wiki`), and may have nodes keep
a few earlier versions of every page, so that changes can be checked
and undone.

# 1. Motivation

Before the web, a BBS had bulletins, a Unix account had a `.plan`,
Usenet groups had FAQs posted again and again, and Gopher had menus of
plain documents. Today Gemini keeps that idea alive. People still want
a place to say who they are, describe a project or keep a guide that
is not a post in a stream (unseenet #212).

Anyone can already put a static web site on an onion service, but then
they must keep a server running, and the site is gone when it is off.
Unseenet can do three things such a site cannot:

- **The pages are replicated.** They stay readable when the author's
  machine is off, on every node that carries the group.
- **The pages are signed.** Nobody but the owner and the people the
  owner lists can change them, and every reader can check it.
- **The pages are found from a key or a name.** A reader who knows
  `andreas@lorensen` (UN-RFC 0019) finds the site with no directory.

Pages are not the web. This document deliberately leaves out HTML,
scripts, forms, styles, remote content and anything else that makes a
page a program. A site is a handful of documents to read.

Some documents are read in order and kept up by more than one person:
a manual, a FAQ that its readers improve, or this very series of
UN-RFCs, which should be readable inside the network it describes
(unseenet #280). A **book** is a site with a reading order (section
10.1), where readers propose changes as comments (section 10.2) and
where earlier versions can be kept (section 10.4). It is not a second
kind of group: everything else in this document applies to books.

# 2. Terms

- **Site:** a channel group with `"view": "pages"` (section 3).
- **Path:** the name of a page within a site (section 4.1).
- **Page article:** an article with a `Page` header (section 4.2).
- **Version:** one page article of a path. A new version names the
  versions it replaces in `Supersedes` (section 4.4).
- **Current version:** for one path, the page article that counts
  (section 5.1). It is either a page or a removal.
- **Page in force:** a path whose current version is a page and that is
  among the site's `max_pages` (section 5.2).
- **Home page:** the page shown when a reader opens the site, by default
  the path `index`.
- **Personal site:** the key-bound group `site@<fp>` (section 7).
- **Starter:** the owner, a moderator or a poster (UN-RFC 0030
  section 2).
- **Book:** a site whose path `contents` is in force (section 10.1).
- **Base:** the version a new version or a proposal changes: the first
  Message-ID in a version's `Supersedes`, or in a proposal's
  `References` (section 10.3).
- **Proposal:** a comment that offers a new version of a page
  (section 10.2).
- **Conflict:** two or more versions of a path with the same base
  (section 10.3).
- **Kept version:** an earlier version of a page that nodes keep
  because of the `history` field (section 10.4).

# 3. The Pages View

UN-RFC 0008 section 3.1 is extended: `view` may be `pages`.

A group may have `"view": "pages"` only if its type is `channel`
(UN-RFC 0004 section 2), and only if it is not closed. A node MUST
reject a manifest with `"view": "pages"` for any other group. Who may
write pages is who may post in a channel: the owner, moderators and
listed `posters`, and in `wiki` mode also others (section 10.5).

A site's manifest MAY contain:

| Field       | Type    | Default    | Meaning                                       |
|-------------|---------|------------|-----------------------------------------------|
| `max_pages` | integer | `32`       | How many pages may be in force (1-100)        |
| `home`      | string  | `"index"`  | The path of the home page (section 4.1)       |
| `history`   | integer | `1`        | Earlier versions kept per page (1-4)          |
| `edit`      | string  | `"review"` | `review` or `wiki` (section 10.5)             |
| `wiki_ripe` | integer | `2`        | Lowest level for direct `wiki` edits (0-4)    |
| `index`     | string  | `"no"`     | `yes` or `no`: may search engines index the site (section 9.3) |

`(1 + history) × max_pages` MUST NOT be more than 200 (section 6.1). A
manifest with `"edit": "wiki"` MUST have `comments` set to `open`
(UN-RFC 0030 section 3).

A value outside these ranges makes the manifest invalid (UN-RFC 0004
section 4, step 3).

Articles in a site that are not page articles are ordinary articles.
Clients showing the pages view MUST NOT show them as pages; they MAY
offer them in the threads view as usual. An owner who wants comments on
a site uses UN-RFC 0030 as in any channel.

# 4. Page Articles

## 4.1 Paths

A path is 1 to 8 segments separated by `/`. A segment is 1 to 64
characters of `a-z`, `0-9`, `-`, `_` and `.`, and is not `.` or `..`.
Paths are compared as octets; there is no case folding and no
normalisation. Examples: `index`, `about`, `projects/ovos`,
`guides/getting-started`.

## 4.2 Headers and Body

A page article is an article (UN-RFC 0002) in a site with:

- `Page: <path>`;
- `Supersedes:` the versions it replaces, when it is not the first
  version of its path (section 4.4);
- `Subject:` the page's title, at most 128 characters;
- `Content-Type: text/markdown; charset=utf-8; variant=unseenet`
  (UN-RFC 0031 section 2), or `text/plain`;
- no `References`: a page is not a reply, and a reply to a page is an
  ordinary article or a proposal (section 10.2);
- optionally `Page-Source: <Message-ID>`, naming a proposal or an
  earlier version whose text this version takes over (section 10.2).

Its body is at most 65 536 octets. Markdown in a page uses the subset
for posts (UN-RFC 0031 section 3.2), with the links of section 8, and
images as blobs (UN-RFC 0027, UN-RFC 0031 section 3.5). The `Blobs`
header lists them as for any article.

A **removal** is a page article with the header `Page-Removed: yes`,
an empty body and no `Blobs`. It removes the path from the site.

## 4.3 Validity

A page article is **valid** when:

1. it is in a group whose current manifest has `"view": "pages"`;
2. its author is the owner, a moderator or a listed poster in that
   manifest, or the site is in `wiki` mode and the author may edit
   directly (section 10.5);
3. its path, subject and size follow sections 4.1 and 4.2, and its
   `Supersedes` follows section 4.4;
4. it is not a cancel or other control article.

A node MUST reject a page article that is not valid. A page article
whose author later loses their role stays stored, but no longer
counts (section 5.1).

## 4.4 New Versions

A new version of a page uses `Supersedes` (UN-RFC 0042), as an edited
post does, under the rules UN-RFC 0042 section 2.1 lets this document
set:

- **Who:** anyone who may write pages in the site (section 3), not only
  the author of the earlier version: the owner, moderators and posters
  look after a site together, and in `wiki` mode others too (section
  10.5).
- **Which:** the versions of the same path the writer knows, newest
  first, at most 32; first the version it edited, its base (section
  10.3). Older
  versions need not be named, since the path already ties the versions
  together. The first version of a path has no `Supersedes`.
- Every Message-ID named MUST be a page article of the same path in the
  same site. UN-RFC 0042 rule 5 (same `References`) does not apply: a
  page has none.

A removal (section 4.2) names the versions it removes in the same way.
Replaced versions are **not** withdrawn (UN-RFC 0042 section 2.1): a
site keeps the previous version of each page, or as many as its
`history` says (sections 5.1, 6.1 and 10.4), and older versions expire
normally.

# 5. Which Pages Count

## 5.1 Current Versions

For each path, the page articles that **count** are the valid ones
whose author is owner, moderator or poster in the **current** manifest,
or, while the site is in `wiki` mode, may edit directly under it
(section 10.5), and that have not been withdrawn by a valid cancel.
Among them, the current version is the one UN-RFC 0042 section 5.2
picks: a version no other counting version names in `Supersedes`, and
of several the one with the latest `Date`, then the lower Message-ID.
The **previous version** of a page is the newest counting version that
its current version names; it is the first of its kept versions
(section 10.4).

A version that no longer counts replaces nothing. When a writer loses
their role, the versions they replaced become current again: their
pages fall back to the version before, rather than disappearing. In a
site many people write, removing someone who damaged pages so undoes
their last edits; removing someone whose edits are wanted is a choice
the client warns about (section 9.2).

A writing client names the version it edited (section 9.2).

## 5.2 Pages in Force

Of the paths whose current version is a page, not a removal, the
`max_pages` whose current versions have the latest `Date` (same order
as above) are in force. The home page is in force if it exists, and
then counts as one of them.

Every node and client that holds the same articles comes to the same
result, as with pins (UN-RFC 0033 section 4.2).

# 6. Nodes

## 6.1 Kept Articles

The current versions of a site's pages are kept articles in the sense
of UN-RFC 0017 section 2.1, with no markers: the page articles are the
targets themselves.

- **Which:** the current version of every page in force (section 5.2),
  its kept versions (section 10.4, by default only the previous
  version) and the versions in conflict with it (section 10.3), and the
  current version of every path whose current version is a removal, as
  long as that removal is inside the group's window.
- **How many:** `(1 + history) × max_pages` (section 3), current and
  kept versions together, with the versions in conflict counted in the
  same limit; at most 200, which leaves room for pins within the 256 of
  UN-RFC 0017 section 2.2. When a site passes it, versions in conflict
  leave first, then the oldest kept versions.
- **Order:** after the pins of UN-RFC 0033, the current versions of
  pages by ascending path, then for each path its kept versions from
  newest to oldest and its versions in conflict.

Everything else - that they do not expire, that an old current version
is accepted so a new node receives the whole site, the blobs of pages
and the 8 MiB of blobs per group - is UN-RFC 0017 sections 2.1 and 2.2.
When a page article is no longer kept, because newer versions replaced
it beyond `history`, its path was removed or pushed out of `max_pages`,
or its author lost their role, it expires normally (UN-RFC 0012).
Versions older than the kept ones are therefore not kept, and a site
does not grow with each edit.

A page whose images a node refused (UN-RFC 0027 section 7.3) stays, and
its images are shown by their alt text.

## 6.2 Carrying Sites

Sites are optional for nodes, like pictures (UN-RFC 0022 section 10).
A node operator MAY:

- carry no sites at all;
- carry personal sites but not others, or the reverse;
- carry the text of sites but not their blobs (UN-RFC 0027 section 8.2).

A node that does not carry a site answers for it as for any group it
does not carry. A node says whether it carries sites in its node
information (UN-RFC 0011 section 4), in the policy field

| Field   | Type   | Meaning                                         |
|---------|--------|-------------------------------------------------|
| `sites` | string | `accept`: carries sites; `refuse`: does not     |

Sites are content that stays, and no node should keep content of that
kind it has not chosen to. An implementation MUST therefore ship with
`sites` set to `refuse`, as for `avatars` (UN-RFC 0022 section 10); the
operator turns it on. A node that does not state `sites` is taken to
refuse them. A node MAY refuse or remove the site of an identity it
blocks (UN-RFC 0018 section 8.2).

## 6.3 Postage

A page article pays the postage of an article of its size (UN-RFC 0006),
with the extra bits for blobs of UN-RFC 0027 section 4.5. Nothing else
is charged: `max_pages`, the page size of section 4.2 and the limits
of UN-RFC 0017 section 2.2 keep a site small.

# 7. Personal Sites

## 7.1 The Site Group

An identity's personal site is the group it owns named `site`:

```
site@<fingerprint of the identity's key>
```

It is a **personal group** (UN-RFC 0029 section 2.1), like the personal
feed (UN-RFC 0034 section 5): anyone who knows a key, or a name that
leads to it (UN-RFC 0019), can find it, and how it is started, ended,
renewed, found and followed is said there once for all personal
groups. Its manifest has `view`: `pages`, besides what UN-RFC 0029
section 2.1 requires.

## 7.2 Other Sites

Any open channel can be a site: a project's (for example
`unseenet.site`), an association's under a country hierarchy, or a
guide that belongs to a group of its own. Such sites are ordinary
groups; they follow their hierarchy's rules (UN-RFC 0018) and expire,
if at all, as their manifests say.

# 8. Links

UN-RFC 0031 section 3.4 is extended for page articles.

- **Within the site:** a link whose destination has no scheme is a path
  in the same site, relative to the directory of the current page as in
  a file system: on `projects/ovos`, `skills` is `projects/skills` and
  `/about` is `about`. `..` goes one segment up and never above the
  site. An optional `#fragment` names a heading in the target page, as
  the client derives anchors from headings; a client that cannot show
  it opens the top of the page.
- **To another site, or a personal one:** the page's address (UN-RFC
  0031 section 3.4.1), `unseenet:<group-id>?p=<path>`; for a personal
  site `unseenet:site@<fingerprint>?p=<path>`. Without `p` it opens the
  site's home page. The older forms `unseenet:<fingerprint>/<path>` and
  `unseenet:join?g=<group-id>&p=<path>` are still read, as UN-RFC 0031
  section 3.4.1 says.

A link that leads to a page that is not in force, or a site the node
does not carry, opens nothing and is shown as unavailable; it is not an
error. Where a name certificate is valid for the fingerprint (UN-RFC
0019), clients SHOULD show the name rather than the fingerprint, but
MUST let the reader see the fingerprint.

# 9. Clients

## 9.1 Reading

- A client shows a site as its home page, with the title of the site
  (its manifest's `title`), the owner's name or fingerprint, and a way
  to reach every page in force: a list or a tree built from the paths,
  ordered by path. It MUST NOT show pages that are not in force.
- Pages are rendered as posts are (UN-RFC 0031). A terminal client MAY
  show the Markdown source; it SHOULD then list the page's links,
  numbered, so they can be followed from the keyboard.
- Following links within the network keeps a history the reader can
  go back and forward in.
- Nothing in a page makes a client fetch anything from outside the
  network (UN-RFC 0031 section 3.1). Links to the web follow UN-RFC 0031
  section 3.4 and the client's own rules; the bootable client never
  opens them.
- A client SHOULD remember the current version it has seen of each page
  of a site it reads. If a node then offers it a version that one it has
  seen names in `Supersedes`, the client SHOULD say that a newer version
  exists but is not available, rather than show the older one as
  current (section 14).
- Wherever a client shows an identity, it SHOULD offer the identity's
  personal site when the site group is current, as for feeds (UN-RFC
  0034 section 5.4).

## 9.2 Writing

- The client keeps the Markdown source the author wrote and offers a
  preview rendered as readers will see it.
- A new version names first the version the client edited, its base
  (section 10.3), and then the earlier ones it knows (section 4.4).
  Before publishing, the client SHOULD fetch the site's current state,
  so that an edit from another device or another writer is not silently
  overtaken.
- The client SHOULD warn before a change would push a page out of
  `max_pages`, or take the site's blobs above 8 MiB (UN-RFC 0017
  section 2.2).
- Before an owner or moderator removes a writer whose versions are
  current, the client SHOULD say which pages will fall back to their
  previous version (section 5.1), and offer to publish the current ones
  again under their own key, as for pins (UN-RFC 0033 section 4.2).
- A client MAY offer to go back to a kept version of a page (section
  10.4).
- Images are prepared as UN-RFC 0027 section 9.1 requires.

## 9.3 Search Engines

A site can be shown on the open web through the web form of its
addresses (UN-RFC 0031 section 3.4.1). Whether search engines may index
it there is the owner's choice, in the manifest field `index`:

- **`no`** (the default): anything that shows the site on the web MUST
  ask search engines not to index it (a `noindex` robots meta tag or
  header) and MUST NOT list it in a sitemap.
- **`yes`:** the owner wants the site to be found. It MAY be indexed and
  listed in a sitemap.

Groups that are not sites have no such field and MUST NOT be offered
for indexing. When an owner sets `index` to `yes`, the client SHOULD
say that search engines and web archives keep copies that the network
cannot expire or withdraw (section 14). This document says only what
the field means; how a web entrance shows sites is for UN-RFC 0043.

# 10. Books

## 10.1 Contents and Reading Order

A site whose path `contents` is in force is a book. The body of the
`contents` page is Markdown whose lists of links give the book's
reading order: the targets of its links, in the order they appear,
taken depth first through nested lists. Nested lists are parts and
chapters. Links to pages in other sites (section 8) MAY appear; they
are part of the order, so one book can gather several.

A client showing a book:

- SHOULD offer the `contents` page as the table of contents, next to
  the home page, which MAY be the same page;
- SHOULD offer "previous" and "next" on every page that appears in the
  reading order, and show where in the book the reader is;
- shows pages that are in force but not in the reading order as for
  any site (section 9.1).

A site without a `contents` page is not a book and is shown as before.
Nothing else in this document changes for books, and the limits of
sections 3, 6.1 and 6.4 apply to each book. A collection larger than
one book allows, such as the whole UN-RFC series, is split into several
books whose `contents` pages link to each other.

## 10.2 Proposals

A **proposal** offers a new version of a page for the editors to
accept. It is a comment (UN-RFC 0030), so it may only be posted where
comments are open, and the comment rules apply to it: `comment_days`,
`banned`, postage and `min_ripe`. A proposal has:

- `References: <Message-ID of its base>`, a version of the page, which
  as a thread root makes the proposal a comment on it;
- `Page-Proposal: <path>`, the path of that page;
- a `Subject`, `Content-Type`, body and `Blobs` as a page article
  (section 4.2), holding the whole proposed page, not a difference.

A proposal is not a page article: it has no `Page` header and never
counts as a version (section 5.1). It is not kept and expires as any
article does. A node that holds the base MUST reject a proposal whose
`Page-Proposal` is not the base's path.

A starter, or in `wiki` mode anyone who may edit directly, accepts a
proposal by publishing a new version of the page with the proposal's
text, and `Page-Source` naming the proposal. Its `Supersedes` names
first the current version at that time, which need not be the
proposal's base. The proposal stays signed by its author, so readers can check
who wrote the text that was accepted, also after the proposal itself
has expired from the nodes, as long as someone has kept a copy.

Replies to a page that are not proposals are ordinary comments.
Clients MUST show proposals apart from comments, and SHOULD offer to
show a proposal as the difference between its base and its text, and
against the current version if that has changed since.

## 10.3 Bases and Conflicts

Every version of a path except the first names its base first in
`Supersedes` (section 4.4): the version its writer edited. A node does
not check that the base was current, which it may not know.

When two writers edit the same version, both new versions name it, and
neither names the other. Of the counting versions of a path that no
other counting version names in `Supersedes`, section 5.1 picks one as
current, so every node and client agrees on what the page shows; the
others are in **conflict** with it. They are kept (section 6.1) until
a version names them; at most 4 versions in conflict per path are
kept, the newest by `Date` and Message-ID as in section 5.1, and a
newer one replaces the oldest.

A client that holds a version in conflict with the current version
MUST show the page as having a conflict and SHOULD let the reader see
both texts. An editor resolves a conflict by publishing a new version,
based on the current version, that takes from the others what should
stay and names them too in `Supersedes`.

## 10.4 Kept Versions

Nodes keep, for every page in force, the first `history` counting
versions that its current version names in `Supersedes`, in that
order (newest first, section 4.4). With the default of 1 this is the
previous version of section 5.1; a book may keep up to 4. A removal
ends the history: it and the versions it names are not kept. Kept
versions are kept articles (section 6.1) and share the site's limits
with the pages in force.

A client:

- SHOULD offer a page's kept versions with their dates and authors,
  and the difference between any two of them;
- lets a starter, or in `wiki` mode anyone who may edit directly,
  restore a kept version by publishing its text as a new version, with
  `Page-Source` naming the kept version.

Older versions than the kept ones expire. Readers and archives may keep
more (UN-RFC 0012); a version found there is still signed and can be
checked.

## 10.5 Edit Modes

The manifest field `edit` decides who publishes versions:

- **`review`** (the default): only starters publish versions. Others
  propose (section 10.2), if comments are open.
- **`wiki`**: besides starters, every key that may comment (UN-RFC 0030
  section 4) and whose ripening level (UN-RFC 0025 section 4) is at
  least `wiki_ripe` may **edit directly**: publish page articles other
  than removals. Only starters remove pages, since a removal ends a
  page's kept versions (section 10.4). Proposals are still allowed.

UN-RFC 0030 section 4 is amended: in a site in `wiki` mode, a node MUST
accept a page article from a key that may edit directly, even though it
is a thread root.

A version written by a key that is not a starter counts only while the
site is in `wiki` mode (section 5.1). Before an owner's client publishes
a manifest that turns `wiki` mode off, it MUST publish, as the owner,
every current version written by others again, with `Page-Source`
naming the original, so that the pages do not change for readers when
the mode does. Kept versions written by others stop counting and
expire.

Moderators and the owner undo vandalism by restoring a kept version
(section 10.4), and stop it by banning the key (UN-RFC 0004 section
5.1), by raising `wiki_ripe`, or by setting `edit` to `review`. A
moderator MAY also withdraw a version with a cancel, as any article.

# 11. Gateways

Gateways (UN-RFC 0023) do not carry page articles in this document.
Mappings to other networks, such as Nostr long-form articles or Gemini
capsules, need a document of their own.

# 12. Changes to Other Documents

- **UN-RFC 0008** section 3.1: `view` gains the value `pages`, for open
  channel groups only (section 3).
- **UN-RFC 0042** section 2.1: a new version of a page uses
  `Supersedes`, written by anyone who may write pages, and replaced
  versions are kept as the page's kept versions rather than withdrawn
  (sections 4.4, 6.1, 10.4).
- **UN-RFC 0017** section 2.1: a site's current pages, their kept
  versions and versions in conflict are kept articles (section 6.1);
  the limit of this kind in section 2.2 is `(1 + history) ×
  max_pages`, at most 200. What that means for UN-RFC 0012 and UN-RFC
  0027 is said there.
- **UN-RFC 0030** section 4: in `wiki` mode, page articles from keys
  that may edit directly are accepted (section 10.5); proposals are
  comments with an extra header (section 10.2).
- **UN-RFC 0011** section 4: the policy field `sites` (section 6.2).
- **UN-RFC 0029** section 2: the table of key-bound groups gains
  `site@<fp>`, a personal group (UN-RFC 0029 section 2.1), this
  document section 7.1.
- **UN-RFC 0031** section 3.4: links within a site and to pages
  (section 8).
- **UN-RFC 0043:** what shows sites on the web follows the manifest
  field `index` (section 9.3).
- **UN-RFC 0000** section 6: 0035 is added to the index.

# 13. Rationale

- **Why not HTML?** HTML brings scripts, styles, forms, remote fonts
  and images, and all the ways a page can track or fool its reader.
  The Markdown of UN-RFC 0031 is already safe in every client and reads
  well as plain text in a terminal. Sites lose layout and gain the
  certainty that reading a page cannot hurt the reader.
- **Why channels only?** A page is something its owner and the people
  the owner trusts stand behind. Even a wiki (section 10.5) is a
  channel whose owner has opened it, and can close it again.
- **Why are books sites and not a group type of their own?** A book
  needs signed pages, versions, links, limits and the state that keeps
  them, which sites already have. A second type would duplicate all of
  it and drift apart. A book only adds an order, proposals and a little
  history, and a site gains them by having a `contents` page.
- **Why is the order a page and not a manifest field?** Editors change
  the order as often as the pages, and a page can be proposed,
  versioned and restored like any other. A manifest is the owner's
  alone, and changing it for every new chapter would make the owner a
  bottleneck.
- **Why are proposals comments?** Comments already have the rules a
  proposal needs: who may write, for how long, postage, ripening and
  moderation (UN-RFC 0030). A proposal sits under the page it changes,
  where readers discuss it. It carries the whole text, because
  differences break when several proposals change the same version.
- **Why does wiki need history and ripening?** A wiki without kept
  versions cannot undo vandalism, which is why earlier drafts of this
  document left wikis out. Kept versions make undoing one step, and
  `wiki_ripe` makes a fresh throw-away key wait about half a day
  (level 2, UN-RFC 0025 section 4) before it can change a page.
  Removals are left to starters, since they end the history.
- **Why show conflicts instead of merging them?** Articles reach nodes
  late and out of order, so two people often edit the same version.
  Letting the last one win silently loses work; merging text
  automatically guesses. Section 5.1 gives every reader the same page,
  and the client shows that another text exists.
- **Why not closed groups?** In a closed group nodes cannot read the
  `Page` header, so they cannot tell the current version from an old
  one. Members-only sites need the carried copies of UN-RFC 0033
  section 6 or something like them, and a document of their own.
- **Why keep one to four earlier versions?** Full history is what makes
  a site grow without end; nodes keep what is current, and readers and
  archives (UN-RFC 0012) may keep more. One previous version is the
  least that lets a page fall back when a writer is removed, and lets
  anyone undo the last edit. A book may keep up to four, so readers can
  check what a page said before a change, signed and inside the network
  rather than on a server they must trust. They share the site's
  limits, so `history` trades pages for depth and never raises the
  bound.
- **Why `Supersedes` and not a version number?** Saying which version
  an edit replaces is the one way Unseenet says "a new version"
  (UN-RFC 0042 section 2.1), so nodes and clients handle pages and
  posts with the same code. It also orders versions by what each writer
  saw, not by clocks; the date only settles two edits of the same
  version, and the first entry of `Supersedes` names the base a
  conflict is found from (section 10.3).
- **Why limits this low?** 32 pages and 8 MiB is plenty for a person's
  or a project's site, and small enough that carrying a few thousand
  sites costs a node little. The UN-RFC series in October 2026 was 43
  documents and 552 KB, none above 64 KiB, which fits; as it grows it
  becomes several books (section 10.1). Larger collections belong in
  several books or in ordinary groups with attachments, which expire.
- **Why a key-bound personal site?** So that it can be found from a key
  or a name with no directory, and disappears when the key is no longer
  used (UN-RFC 0029), as profiles and feeds do.
- **Why not put pages in the profile?** A profile is small, lives in a
  manifest and cannot have images (UN-RFC 0027 section 7.1). Keeping
  sites apart also lets an operator carry profiles without sites.

# 14. Security and Privacy Considerations

- **A personal site is public and linked to the identity.** Everything
  in it can be kept by anybody, also after it is changed or removed.
  UN-RFC 0029 section 2.1 makes the client say so. Users who need to
  keep things apart SHOULD use a separate identity for a site.
- **Abuse.** Static content that stays is more attractive for unlawful
  material than a discussion. The limits of section 3 and UN-RFC 0017 section 2.2, the
  operator's freedom to carry no sites, no site images or any single
  blob (section 6.2, UN-RFC 0027 section 7.3), and blocks within a
  hierarchy (UN-RFC 0018 section 8.2) apply. A site that breaks a
  node's rules can be dropped as any group can.
- **Vandalism in a wiki.** A key that may edit directly can replace a
  page with anything until a moderator restores it. Kept versions make
  that one step (section 10.4), removals are not open to it, and
  `wiki_ripe` and bans make each new attempt cost hours of ripening.
  A node that receives a vandalised version before its restoration
  serves it in the meantime, as it would any article until a cancel
  arrives. Owners who cannot watch a book SHOULD use `review`.
- **Proposals as a channel for spam.** Proposals are comments and cost
  what comments cost (UN-RFC 0030, UN-RFC 0006, UN-RFC 0025). They are
  not kept, so unaccepted ones expire; a proposal never changes what a
  page shows until an editor accepts it.
- **Who wrote what.** A version accepted from a proposal is signed by
  the editor who accepted it, not by the proposer. `Page-Source` lets a
  reader find the proposer's signed text while it is still held, but
  the editor is the one who answers for what the page says.
- **Stale pages.** A node can serve an old version of a page, or none,
  but cannot forge one: every version is signed. Section 9.1 has the
  client remember the current version it has seen, so a node that holds
  back a newer version is noticed by readers who have seen it.
- **Impersonation.** Anybody can make a site that looks like somebody
  else's, but not `site@<fp>` for a key they do not hold. Clients SHOULD
  show a site by its owner's name (UN-RFC 0019) or fingerprint, never by
  its title alone.
- **Deceptive links and phishing.** Pages have no forms and no scripts,
  and links show where they go (UN-RFC 0031 section 3.4). A page can
  still ask a reader to do something foolish in words; clients cannot
  prevent that.
- **Indexed sites outlive the network.** A site with `index` set to
  `yes` can be copied by search engines and web archives, which keep
  it after its pages expire, are replaced or withdrawn. `no` is the
  default for that reason, as `X-No-Archive` once was on Usenet; it is
  a request, which well-behaved search engines follow, not a protection.
- **Reading patterns.** A reader's node can see which sites are read
  through it, as for any group. Over Tor it does not learn by whom.
- **Rendering cost.** The 64 KiB limit and the rendering limits of
  UN-RFC 0031 section 7 keep a crafted page from hanging a client.
- **Scale.** A personal site is one more key-bound group per identity,
  but it exists only when its owner asks for it (UN-RFC 0029 section 2.1), so it
  does not grow with the number of identities as profiles do. The upper
  bound per identity is one site of at most 200 kept versions of 64
  KiB, current, kept and in conflict together (12.5 MiB of text), and
  8 MiB of blobs (sections 3, 4.2 and 6.1, UN-RFC 0017 section 2.2);
  with the defaults (32 pages, one previous version each) the text is
  at most 4 MiB. A book's `history` and conflicts share that bound
  rather than raise it, and older versions expire (section 6.1), so
  editing does not make a site grow. A node carries sites only when its
  operator turns them on, and may carry their text without their blobs
  (section 6.2), so at the design targets of UN-RFC 0001 section 1.2 a
  node pays only for the sites it has chosen. A new node gets a site
  through the ordinary state transfer of UN-RFC 0017 (sections 2.1 and
  3), with no extra round trips.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
