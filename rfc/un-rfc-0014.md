```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0014                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0004

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
| `rules` | string | The charter: purpose and rules, plain text, max 8192 characters |

The existing fields `title` (one line) and `description` (a short
paragraph) remain for listings; `rules` is the full text.

Changing the rules is changing the manifest: the owner publishes a new
manifest with a higher `serial` (UN-RFC 0004 section 3.2). Readers can
see that the rules changed by the serial.

For closed groups, the manifest is public (UN-RFC 0004 section 6.6).
Owners who do not want the rules to be public SHOULD put them in the
encrypted `sealed` object instead, under the same name `rules`.

# 3. Clients

A client:

- MUST offer a way to read a group's rules;
- SHOULD show them when the reader opens the group for the first time,
  and again when the manifest's `serial` has changed since the reader
  last saw them;
- SHOULD remind the reader that the group has rules when they write
  their first post in it.

Rules are plain text and MUST be displayed as such, never interpreted as
markup or followed as links automatically.

# 4. Enforcement

Rules are social, not technical. Nodes do not check posts against them.
What enforces them is what the group type offers: moderators in
moderated groups, the owner's choice of posters in channels, membership
in closed groups, cancels by the owner (UN-RFC 0004 section 7), and each
reader's own filters.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
