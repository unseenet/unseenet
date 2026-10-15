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

Reserved for future work: 0008 (low-latency chat delivery),
0009 (moderation submission queue), 0010 (node discovery).

# 7. Author's Address

Andreas Lorensen, Denmark. <https://github.com/andlo>

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
