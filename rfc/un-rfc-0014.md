```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0014                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0004, 0031

                  Unseenet: Group Rules (Charters)
```

# Abstract

A group's owner can publish the group's purpose and rules - its
**charter** - in the group's manifest. Because the manifest is signed,
replicated and versioned, every reader on every node sees the same
rules, and nobody but the owner can change them. Clients show the rules
before a reader first posts.

# 1. Motivation

Usenet groups had charters, posted regularly and collected in FAQs, and
newcomers were expected to read them before posting. They lived in
ordinary posts, so they expired, could be forged, and were easy to miss.
Unseenet has a better place for them: the manifest.

# 2. Manifest Field

UN-RFC 0004 section 3.1 is extended with:

| Field   | Type   | Meaning                                                   |
|---------|--------|-----------------------------------------------------------|
| `rules` | string | The charter: purpose and rules, max 8192 characters |
| `rules_type` | string | How `rules` is written: `text/plain` (the default) or Markdown (section 2.1) |

The existing fields `title` (one line) and `description` (a short
paragraph) remain for listings; `rules` is the full text.

Changing the rules is changing the manifest: the owner publishes a new
manifest with a higher `serial` (UN-RFC 0004 section 3.2). Readers can
see that the rules changed by the serial.

For closed groups, the manifest is public (UN-RFC 0004 section 6.6).
Owners who do not want the rules to be public SHOULD put them in the
encrypted `sealed` object instead, under the same names `rules` and
`rules_type`.

## 2.1 Plain Text or Markdown

`rules_type` takes the same values as a post's `Content-Type`
(UN-RFC 0031 section 2):

- absent or `text/plain; charset=utf-8`: plain text;
- `text/markdown; charset=utf-8; variant=unseenet`: Markdown, with the
  subset of a post (UN-RFC 0031 section 3.2) **without images**, since a
  manifest cannot reference blobs (UN-RFC 0027 section 7.1). An image is
  shown as its alt text.

Any other value is shown as plain text, and so is the text in a client
that does not know the field - which is what Markdown is written to
read like. Headings, lists and links let a charter have a structure
("Purpose", "Allowed", "Not allowed", "Moderators") rather than being
one block of text. A "read this first" post or FAQ belongs in a pinned
post (UN-RFC 0033), not in the rules.

Without `rules_type`, `rules` is plain text, so the field is optional
and older manifests mean what they always meant. The limit of 8192
characters counts the source text.

# 3. Clients

A client:

- MUST offer a way to read a group's rules;
- SHOULD show them when the reader opens the group for the first time,
  and again when the manifest's `serial` has changed since the reader
  last saw them;
- SHOULD remind the reader that the group has rules when they write
  their first post in it.

Plain rules MUST be displayed as text, never interpreted as markup.
Markdown rules are displayed as section 2.1 says. Either way, links in
rules MUST NOT be followed without the reader's action (UN-RFC 0031
section 3.4). A client that lets the owner write rules SHOULD offer the
same choice of plain text or Markdown as its post editor.

# 4. Enforcement

Rules are social, not technical. Nodes do not check posts against them.
What enforces them is what the group type offers: moderators in
moderated groups, the owner's choice of posters in channels, membership
in closed groups, cancels by the owner (UN-RFC 0004 section 7), and each
reader's own filters.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
