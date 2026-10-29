```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0000                                              October 2026
Category: Process
Status: Active

             The Unseenet Request for Comments Process
```

# Abstract

This document describes how the Unseenet protocol is specified, changed
and extended. Like the Internet RFC series that defined Usenet, the
Unseenet specification lives in a numbered series of documents ("UN-RFCs")
rather than in any single implementation. Anyone may write an
implementation; the UN-RFCs are the authority, not the reference code.

# 1. Purpose

Unseenet is meant to be a *network*, not a *program*. Interoperability
between independent nodes and clients is only possible if the protocol
is written down precisely, versioned, and changed in the open. This
series is that written record.

# 2. Requirements Language

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT",
"SHOULD", "SHOULD NOT", "RECOMMENDED", "NOT RECOMMENDED", "MAY", and
"OPTIONAL" in UN-RFCs are to be interpreted as described in BCP 14
(RFC 2119, RFC 8174) when, and only when, they appear in all capitals.

# 3. Document Series

## 3.1 Numbering

UN-RFCs are numbered sequentially with four digits. A number is never
reused. Files live in the `rfc/` directory of the main repository as
`un-rfc-NNNN.md`.

## 3.2 Categories

| Category        | Meaning                                                        |
|-----------------|----------------------------------------------------------------|
| Process         | How the series itself works (this document).                   |
| Standards Track | Normative protocol. Implementations MUST follow it to interoperate. |
| Informational   | Background, rationale, recommended practice. Not required for interop. |
| Experimental    | Proposals under trial. MAY be implemented; MUST NOT be assumed. |

## 3.3 Status

| Status     | Meaning                                                           |
|------------|-------------------------------------------------------------------|
| Draft      | Open for discussion. Can change without notice.                   |
| Proposed   | Implemented in a release, from 1.0; not edited in substance.      |
| Standard   | Also implemented independently, interoperating (section 3.3.2).   |
| Active     | For Process documents that are continuously maintained.           |
| Obsoleted  | Replaced. The header names the replacing UN-RFC.                  |

All protocol documents of this first series are **Draft** while
Unseenet is pre-alpha (before 1.0), also after their pull requests are
merged. A Draft may be changed in place, through section 4.

### 3.3.1 Accepting is not a status

When the maintainer **accepts** a pull request - a new UN-RFC, an
amendment or a correction - that *change* is agreed and may be merged.
It says nothing about the document as a whole: it does not make the
document Proposed, and it never changes its `Status:` line. The pull
request, its issue and the CHANGELOG record what was accepted and when.
"Accepted" is not a status, and a header MUST NOT say it.

### 3.3.2 At 1.0

When Unseenet 1.0 is released, every protocol document that 1.0
implements becomes **Proposed**, and from then on it is not edited in
substance: an error is fixed by an erratum at the end of the document,
and a change is a new UN-RFC that `Updates:` or `Obsoletes:` it
(section 4), as RFCs have always been. A document 1.0 does not
implement stays Draft and may still change. A Proposed document becomes
**Standard** when an independent implementation - not the project's
own code - interoperates with the reference implementation.

## 3.4 Header Block

Every UN-RFC begins with a header block containing number, author(s),
date, category and status. If the document updates or obsoletes others,
the header MUST say so with `Updates:` and/or `Obsoletes:` lines.

A Standards Track document also says what is built, in an
`Implemented:` line right after `Status:`:

| `Implemented:`                               | Meaning                                   |
|----------------------------------------------|-------------------------------------------|
| `-`                                          | Not built yet                             |
| `unseenet 0.5.0`                             | Built in that release of the core         |
| `unseenet 0.4.0, unseenet-gateway 0.1.0`     | Built across these releases               |
| `unseenet main (unreleased)`                 | Built in the core's main, not yet released |
| `...; partly - books (#280)`                 | Only partly built: what is missing, where |

The pull request that builds something - or the part still missing -
updates the line in the same go; releasing the core turns "main (unreleased)" into its
version (`tools/check_rfc_headers.py --release X.Y.Z`). The status says
how settled a document is; this line says how much of it runs.
`tools/check_rfc_headers.py` checks every header on every pull request
that touches `rfc/`, and refuses a status this section does not name.

# 4. Changing the Protocol

1. Open an issue describing the problem (not the solution).
2. Write a Draft UN-RFC as a pull request. Take the next free number.
3. Discussion happens on the pull request. Substantive objections MUST be
   answered in the document (in a "Rationale" or "Considerations" section),
   not only in comments.
4. The maintainer accepts the change, or asks for more, and it is merged.
   The document stays Draft (section 3.3.1).
5. At 1.0 the implemented documents become Proposed, and a Proposed
   document becomes Standard when an independent implementation
   interoperates with the reference implementation (section 3.3.2).

Every Draft MUST say what it costs every node and every client at the
design targets of UN-RFC 0001 section 1.2 - storage, traffic, round
trips over Tor and anything that grows with the number of identities
or groups - in a section "Scale Considerations", or a bullet "Scale"
under its security and privacy considerations. A document that adds
something every identity may have (a key-bound group, a field in every
manifest) MUST give an upper bound per identity.

Published Standard documents are never edited in substance. Errors are
fixed by errata notes at the end of the document; changes are made by a
new UN-RFC that `Updates:` or `Obsoletes:` the old one.

# 5. Extension Principles

The protocol is designed to be extended without breaking old software:

- **Be liberal in what you accept, conservative in what you send**, except
  where security is concerned. Unknown headers MUST be preserved and
  forwarded. Unknown signatures, unknown capabilities, unknown control
  types and unknown group types MUST NOT cause a node to crash or to
  drop unrelated traffic.
- **Versioned wire format.** Articles carry `Unseenet-Version`. Nodes
  advertise supported features as NNTP capabilities (UN-RFC 0005).
- **Experimental names.** Experimental headers and commands use an `X-`
  or `XUN-` prefix until standardized.
- **Security is never negotiated down.** An extension MUST NOT allow a
  peer to request weaker cryptography than this series requires.

# 6. Index of the First Series

| No.  | Title                                         | Category        |
|------|-----------------------------------------------|-----------------|
| 0000 | The Unseenet Request for Comments Process     | Process         |
| 0001 | Architecture and Terminology                  | Informational   |
| 0002 | Article Format                                | Standards Track |
| 0003 | Identities, Keys and Cryptographic Primitives | Standards Track |
| 0004 | Groups, Manifests and Access Control          | Standards Track |
| 0005 | ONNTP: Transport and Peering over Onion Services | Standards Track |
| 0006 | Proof-of-Work Postage                         | Standards Track |
| 0007 | Protecting Data at Rest                       | Informational   |
| 0008 | Chat Groups and Low-Latency Delivery          | Standards Track |
| 0009 | Inbox Groups and Local Groups                 | Standards Track |
| 0010 | Lists of Known Nodes                          | Standards Track |
| 0011 | Node Information and Operator Contact         | Standards Track |
| 0012 | Retention, Archive Nodes and History          | Standards Track |
| 0013 | Removing Groups                               | Standards Track |
| 0014 | Group Charters                                | Standards Track |
| 0015 | Transferring Group Ownership                  | Standards Track |
| 0016 | Peer Authentication with Node Keys            | Standards Track |
| 0017 | Catching Up by Pull, and Group State          | Standards Track |
| 0018 | Hierarchies and Authority over Group Names    | Standards Track |
| 0019 | Names for Identities                          | Standards Track |
| 0020 | Keeping Lists from Inside the Network         | Standards Track |
| 0021 | Listed Nodes Must Be Connected                | Standards Track |
| 0022 | Profiles for Identities                       | Standards Track |
| 0023 | Gateways to Other Networks                    | Standards Track |
| 0024 | Usenet Gateways                               | Standards Track |
| 0025 | Key Ripening and Standing                     | Standards Track |
| 0026 | Nostr Gateways                                | Standards Track |
| 0027 | Attachments                                   | Standards Track |
| 0028 | Chats and Posts                               | Standards Track |
| 0029 | Key-bound Groups, Lifetime and Renewal        | Standards Track |
| 0030 | Comments in Channels                          | Standards Track |
| 0031 | Formatting: Markdown and Emoji                | Standards Track |
| 0032 | Mention Notices                               | Standards Track |
| 0033 | Pinned Posts                                  | Standards Track |
| 0034 | Feeds and Following                           | Standards Track |
| 0035 | Pages, Sites and Books                        | Standards Track |
| 0036 | Attestations                                  | Standards Track |
| 0037 | Matrix Gateways                               | Standards Track |
| 0038 | Gateway Cooperation and the Gateway Directory | Standards Track |
| 0040 | Key-bound Groups at Scale                     | Standards Track |
| 0041 | Fetching Many Manifests at Once               | Standards Track |
| 0042 | Editing Posts (Supersedes)                    | Standards Track |
| 0043 | Web Entrances and Clients on the Open Web     | Standards Track |
| 0044 | Your State in the Network                     | Standards Track |
| 0045 | Spam Reports                                  | Standards Track |
| 0046 | The Local Client API                          | Standards Track |
| 0047 | Team Inboxes                                  | Standards Track |
| 0048 | Reactions                                     | Standards Track |
| 0049 | Imported Posts and the Time of Posting        | Standards Track |
| 0050 | Copying an Identity, and Recovery Words       | Standards Track |
| 0051 | Your Own Rules for Your Feed and Your Groups  | Standards Track |
| 0052 | Tags                                         | Standards Track |
| 0053 | Content Labels                               | Standards Track |
| 0054 | Councils, and a Registrar Without an Owner   | Standards Track |
| 0055 | What a Node Carries                          | Standards Track |
| 0056 | A Group's Own Emoji                          | Standards Track |
| 0057 | A People Directory                           | Standards Track |
| 0058 | Finding Groups                               | Standards Track |
| 0059 | Link Cards                                   | Standards Track |
| 0060 | Sharing                                      | Standards Track |

The moderation submission queue first reserved as 0009 is covered by
UN-RFC 0009 section 3.

# 7. Author's Address

Andreas Lorensen, Denmark. <https://github.com/andlo>

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
