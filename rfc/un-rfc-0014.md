```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0014                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0004, 0031

                     Unseenet: Group Charters
```

# Abstract

A group's owner can publish what the group is for and what it asks of
those who write in it - its **charter** - in the group's manifest.
Because the manifest is signed, replicated and versioned, every reader
on every node sees the same charter, and nobody but the owner can change
it. Clients show the charter before a reader first posts.

A charter is not enforced by any machine. That is why it is called a
charter and not rules: in Unseenet, **rules** are a reader's own rules
(UN-RFC 0051), which their client does apply - to hide, mark and order
what that reader sees, and nothing else.

# 1. Motivation

Usenet groups had charters, posted regularly and collected in FAQs, and
newcomers were expected to read them before posting. They lived in
ordinary posts, so they expired, could be forged, and were easy to miss.
Unseenet has a better place for them: the manifest.

The word matters. A group's charter is what the group asks of you; your
own rules (UN-RFC 0051) are what you choose to see. A client that called
both "rules" would suggest that the group's text is applied as your
rules are, and it is not (section 4).

# 2. Manifest Field

UN-RFC 0004 section 3.1 is extended with:

| Field          | Type   | Meaning                                                |
|----------------|--------|--------------------------------------------------------|
| `charter`      | string | The charter: what the group is for and what it asks of those who write, max 8192 characters |
| `charter_type` | string | How `charter` is written: `text/plain` (the default) or Markdown (section 2.1) |

The existing fields `title` (one line) and `description` (a short
paragraph) remain for listings; `charter` is the full text.

Changing the charter is changing the manifest: the owner publishes a
new manifest with a higher `serial` (UN-RFC 0004 section 3.2). Readers
can see that the charter changed by the serial.

For closed groups, the manifest is public (UN-RFC 0004 section 6.6).
Owners who do not want the charter to be public SHOULD put it in the
encrypted `sealed` object instead, under the same names `charter` and
`charter_type`.

## 2.1 Plain Text or Markdown

`charter_type` takes the same values as a post's `Content-Type`
(UN-RFC 0031 section 2):

- absent or `text/plain; charset=utf-8`: plain text;
- `text/markdown; charset=utf-8; variant=unseenet`: Markdown, with the
  subset of a post (UN-RFC 0031 section 3.2) **without images**, since a
  manifest cannot reference blobs (UN-RFC 0027 section 7.1). An image is
  shown as its alt text.

Any other value is shown as plain text, and so is the text in a client
that does not know the field - which is what Markdown is written to
read like. Headings, lists and links let a charter have a structure
("Purpose", "Welcome", "Not welcome", "Moderators") rather than being
one block of text. A "read this first" post or FAQ belongs in a pinned
post (UN-RFC 0033), not in the charter.

Without `charter_type`, `charter` is plain text, so the field is
optional. The limit of 8192 characters counts the source text.

## 2.2 The Earlier Names

Until October 2026 the fields were called `rules` and `rules_type`
(#726). Only the owner can sign a new manifest, so manifests signed with
those names stay in the network until their owners publish again.
Until 1.0:

- a reader MUST take `rules` and `rules_type` as `charter` and
  `charter_type` when the manifest has no `charter`; when it has both,
  `charter` is used and `rules` ignored;
- a writer MUST NOT write `rules` or `rules_type`; publishing a new
  manifest of a group whose current one has them writes them under the
  new names.

Nodes are not affected: they never read the field's content (section 4).
The earlier names are to be removed from this document before 1.0.

# 3. Clients

A client:

- MUST offer a way to read a group's charter;
- SHOULD show it when the reader opens the group for the first time,
  and again when the manifest's `serial` has changed since the reader
  last saw it;
- SHOULD remind the reader that the group has a charter when they write
  their first post in it;
- SHOULD call it the group's charter, and SHOULD NOT call it rules,
  which is the name of the reader's own rules (UN-RFC 0051).

A plain charter MUST be displayed as text, never interpreted as markup.
A Markdown charter is displayed as section 2.1 says. Either way, links
in a charter MUST NOT be followed without the reader's action (UN-RFC
0031 section 3.4). A client that lets the owner write a charter SHOULD
offer the same choice of plain text or Markdown as its post editor.

# 4. Enforcement

A charter is social, not technical. Nodes do not check posts against
it, and no client applies it for the reader. What upholds it is what the
group type offers: moderators in moderated groups, the owner's choice of
posters in channels, membership in closed groups, cancels by the owner
(UN-RFC 0004 section 7), bans (UN-RFC 0004 section 5.1), reports
(UN-RFC 0045) - and each reader's own rules (UN-RFC 0051), which decide
only what that reader sees.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
