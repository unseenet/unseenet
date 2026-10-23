```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0035                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0000, 0008, 0011, 0017, 0029, 0031, 0042

                       Unseenet: Pages and Sites
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

# 3. The Pages View

UN-RFC 0008 section 3.1 is extended: `view` may be `pages`.

A group may have `"view": "pages"` only if its type is `channel`
(UN-RFC 0004 section 2), and only if it is not closed. A node MUST
reject a manifest with `"view": "pages"` for any other group. Who may
write pages is who may post in a channel: the owner, moderators and
listed `posters`.

A site's manifest MAY contain:

| Field       | Type    | Default   | Meaning                                       |
|-------------|---------|-----------|-----------------------------------------------|
| `max_pages` | integer | `32`      | How many pages may be in force (1-100)        |
| `home`      | string  | `"index"` | The path of the home page (section 4.1)       |

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
  ordinary article.

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
   manifest;
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
  look after a site together.
- **Which:** the versions of the same path the writer knows, newest
  first, at most 32; at least the current version it edited. Older
  versions need not be named, since the path already ties the versions
  together. The first version of a path has no `Supersedes`.
- Every Message-ID named MUST be a page article of the same path in the
  same site. UN-RFC 0042 rule 5 (same `References`) does not apply: a
  page has none.

A removal (section 4.2) names the versions it removes in the same way.
Replaced versions are **not** withdrawn (UN-RFC 0042 section 2.1): a
site keeps the previous version of each page (sections 5.1 and 6.1),
and older versions expire normally.

# 5. Which Pages Count

## 5.1 Current Versions

For each path, the page articles that **count** are the valid ones
whose author is owner, moderator or poster in the **current** manifest,
and that have not been withdrawn by a valid cancel. Among them, the
current version is the one UN-RFC 0042 section 5.2 picks: a version no
other counting version names in `Supersedes`, and of several the one
with the latest `Date`, then the lower Message-ID. The **previous
version** of a page is the newest counting version that its current
version names.

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

- **Which:** the current version of every page in force (section 5.2)
  and its previous version (section 5.1), and the current version of
  every path whose current version is a removal, as long as that
  removal is inside the group's window.
- **How many:** `max_pages` (section 3) current versions, and one
  previous version each: the limit of this kind in UN-RFC 0017 section
  2.2 is twice `max_pages`, at most 200, which leaves room for pins.
- **Order:** after the pins of UN-RFC 0033, the current versions of
  pages by ascending path.

Everything else - that they do not expire, that an old current version
is accepted so a new node receives the whole site, the blobs of pages
and the 8 MiB of blobs per group - is UN-RFC 0017 sections 2.1 and 2.2.
When a page article is no longer kept, because two newer versions
replaced it, its path was removed or pushed out of `max_pages`, or its
author lost their role, it expires normally (UN-RFC 0012). Versions
older than the previous one are therefore not kept, and a site does not
grow with each edit.

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
- **To a personal site:** `unseenet:<fingerprint>/<path>` opens that
  page on the identity's personal site; `unseenet:<fingerprint>` alone
  keeps its meaning from UN-RFC 0022 (the identity).
- **To another site:** `unseenet:join?g=<group-id>&p=<path>` extends the
  join link of UN-RFC 0004 with the path to open.

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
  current (section 13).

## 9.2 Writing

- The client keeps the Markdown source the author wrote and offers a
  preview rendered as readers will see it.
- A new version names the version the client edited, and the earlier
  ones it knows (section 4.4). Before publishing, the client SHOULD
  fetch the site's current state, so that an edit from another device
  or another writer is not silently overtaken.
- The client SHOULD warn before a change would push a page out of
  `max_pages`, or take the site's blobs above 8 MiB (UN-RFC 0017
  section 2.2).
- Before an owner or moderator removes a writer whose versions are
  current, the client SHOULD say which pages will fall back to their
  previous version (section 5.1), and offer to publish the current ones
  again under their own key, as for pins (UN-RFC 0033 section 4.2).
- A client MAY offer to go back to the previous version of a page: it
  publishes the previous version's content as a new version.
- Images are prepared as UN-RFC 0027 section 9.1 requires.

# 10. Gateways

Gateways (UN-RFC 0023) do not carry page articles in this document.
Mappings to other networks, such as Nostr long-form articles or Gemini
capsules, need a document of their own.

# 11. Changes to Other Documents

- **UN-RFC 0008** section 3.1: `view` gains the value `pages`, for open
  channel groups only (section 3).
- **UN-RFC 0042** section 2.1: a new version of a page uses
  `Supersedes`, written by anyone who may write pages, and replaced
  versions are kept as the previous version rather than withdrawn
  (sections 4.4, 6.1).
- **UN-RFC 0017** section 2.1: a site's current pages are kept
  articles (section 6.1). What that means for UN-RFC 0012 and UN-RFC
  0027 is said there.
- **UN-RFC 0011** section 4: the policy field `sites` (section 6.2).
- **UN-RFC 0029** section 2: the table of key-bound groups gains
  `site@<fp>`, a personal group (UN-RFC 0029 section 2.1), this
  document section 7.1.
- **UN-RFC 0031** section 3.4: links within a site and to pages
  (section 8).
- **UN-RFC 0000** section 6: 0035 is added to the index.

# 12. Rationale

- **Why not HTML?** HTML brings scripts, styles, forms, remote fonts
  and images, and all the ways a page can track or fool its reader.
  The Markdown of UN-RFC 0031 is already safe in every client and reads
  well as plain text in a terminal. Sites lose layout and gain the
  certainty that reading a page cannot hurt the reader.
- **Why channels only?** A page is something its owner stands behind.
  Pages anybody may change are a wiki, which needs rules for conflicts,
  vandalism and history that this document does not attempt.
- **Why not closed groups?** In a closed group nodes cannot read the
  `Page` header, so they cannot tell the current version from an old
  one. Members-only sites need the carried copies of UN-RFC 0033
  section 6 or something like them, and a document of their own.
- **Why the current and the previous version?** Full history is what
  makes a site grow without end; nodes keep what is current, and
  readers and archives (UN-RFC 0012) may keep more. One previous version
  is the least that lets a page fall back when a writer is removed, and
  lets anyone undo the last edit. Browsing and restoring older history
  belong to a later wiki mode.
- **Why `Supersedes` and not a version number?** Saying which version
  an edit replaces is the one way Unseenet says "a new version"
  (UN-RFC 0042 section 2.1), so nodes and clients handle pages and
  posts with the same code. It also orders versions by what each writer
  saw, not by clocks; the date only settles two edits of the same
  version.
- **Why limits this low?** 32 pages and 8 MiB is plenty for a person's
  or a project's site, and small enough that carrying a few thousand
  sites costs a node little. Larger collections belong in ordinary
  groups with attachments, which expire.
- **Why a key-bound personal site?** So that it can be found from a key
  or a name with no directory, and disappears when the key is no longer
  used (UN-RFC 0029), as profiles and feeds do.
- **Why not put pages in the profile?** A profile is small, lives in a
  manifest and cannot have images (UN-RFC 0027 section 7.1). Keeping
  sites apart also lets an operator carry profiles without sites.

# 13. Security and Privacy Considerations

- **A personal site is public and linked to the identity.** Everything
  in it can be kept by anybody, also after it is changed or removed.
  UN-RFC 0029 section 2.1 makes the client say so. Users who need to
  keep things apart SHOULD use a separate identity for a site.
- **Abuse.** Static content that stays is more attractive for unlawful
  material than a discussion. The limits of section 3 and UN-RFC 0017 section 2.2, the
  operator's freedom to carry no sites, no site images or any single
  blob (section 6.2, UN-RFC 0027 section 7.3), and blocks within a
  hierarchy (UN-RFC 0018 section 8.2) apply. A site that breaks a node's rules can be dropped
  as any group can.
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
- **Reading patterns.** A reader's node can see which sites are read
  through it, as for any group. Over Tor it does not learn by whom.
- **Rendering cost.** The 64 KiB limit and the rendering limits of
  UN-RFC 0031 section 7 keep a crafted page from hanging a client.
- **Scale.** A personal site is one more key-bound group per identity,
  but it exists only when its owner asks for it (UN-RFC 0029 section 2.1), so it
  does not grow with the number of identities as profiles do. The upper
  bound per identity is one site of at most 100 pages of 64 KiB, each
  with one previous version (12.5 MiB of text), and 8 MiB of blobs
  (sections 3, 4.2 and 6.1, UN-RFC 0017 section 2.2); with the default
  `max_pages` of 32 the text is at most 4 MiB. Older versions expire
  (section 6.1), so editing does not make a site grow. A node
  carries sites only when its operator turns them on, and may carry
  their text without their blobs (section 6.2), so at the design
  targets of UN-RFC 0001 section 1.2 a node pays only for the sites it
  has chosen. A new node gets a site through the ordinary state
  transfer of UN-RFC 0017 (sections 6.2 and 6.3), with no extra round
  trips.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
