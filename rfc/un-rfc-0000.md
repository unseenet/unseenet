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
| Proposed   | Believed complete; awaiting two independent implementations.      |
| Standard   | Interoperably implemented by at least two independent codebases.  |
| Active     | For Process documents that are continuously maintained.           |
| Obsoleted  | Replaced. The header names the replacing UN-RFC.                  |

All protocol documents in this first series are **Draft**.

## 3.4 Header Block

Every UN-RFC begins with a header block containing number, author(s),
date, category and status. If the document updates or obsoletes others,
the header MUST say so with `Updates:` and/or `Obsoletes:` lines.

# 4. Changing the Protocol

1. Open an issue describing the problem (not the solution).
2. Write a Draft UN-RFC as a pull request. Take the next free number.
3. Discussion happens on the pull request. Substantive objections MUST be
   answered in the document (in a "Rationale" or "Considerations" section),
   not only in comments.
4. A Draft becomes Proposed when the maintainers merge it.
5. A Proposed document becomes Standard when two independent
   implementations interoperate.

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
| 0014 | Group Rules (Charters)                        | Standards Track |
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

The moderation submission queue first reserved as 0009 is covered by
UN-RFC 0009 section 3.

# 7. Author's Address

Andreas Lorensen, Denmark. <https://github.com/andlo>

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
