```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0002                                              October 2026
Category: Standards Track
Status: Draft

                      Unseenet: Article Format
```

# Abstract

This document defines the Unseenet article: its syntax, required and
forbidden headers, canonical form, signature, content-derived
Message-ID, and the validation procedure every node and client applies.

# 1. Syntax

An article is a sequence of UTF-8 lines, each terminated by CRLF,
consisting of a header block, one empty line, and a body. This is the
format of RFC 5322 / RFC 5536 with the following restrictions:

1. Header names are ASCII, case-insensitive, and match
   `[A-Za-z0-9-]+`.
2. Header **folding is forbidden**. Each header is exactly one line.
3. A header name MUST NOT appear more than once.
4. Header values MUST NOT contain CR, LF or NUL.
5. The whole article, as transmitted (before NNTP dot-stuffing), MUST
   NOT exceed **65 536 octets**. Nodes MUST accept articles of at least
   32 768 octets and MAY set their limit anywhere between the two.

# 2. Headers

## 2.1 Required in Every Article

| Header             | Value                                                        |
|--------------------|--------------------------------------------------------------|
| `Unseenet-Version` | `1`                                                           |
| `Message-ID`       | Content-derived, see section 4                               |
| `Newsgroups`       | Exactly one Group ID (UN-RFC 0004). No crossposting.         |
| `Date`             | RFC 5322 date-time, UTC, e.g. `Thu, 15 Oct 2026 19:50:00 +0000` |
| `Author-Key`       | Author's public key, `ed25519:...` (UN-RFC 0003)             |
| `Signature`        | Author's signature, section 3                                 |
| `Proof-Of-Work`    | Postage, UN-RFC 0006                                          |

## 2.2 Required Unless the Article Is Encrypted or a Control Article

| Header    | Value                                  |
|-----------|----------------------------------------|
| `From`    | Display name (free text, max 128 characters) |
| `Subject` | Subject line (max 256 characters)       |

Control articles (those with a `Control` header, UN-RFC 0004) MAY omit
`From` and `Subject`.

In encrypted articles (UN-RFC 0004, section 6), `From` and `Subject`
MUST NOT appear in the outer header block; they are carried inside the
ciphertext.

## 2.3 Optional

| Header          | Value                                                        |
|-----------------|--------------------------------------------------------------|
| `References`    | Space-separated Message-IDs, oldest first (threading)        |
| `Content-Type`  | Default `text/plain; charset=utf-8`                           |
| `Expires`       | RFC 5322 date-time; nodes MAY delete after this              |
| `Control`       | Control article type, UN-RFC 0004                             |
| `Encrypted`     | Encryption parameters, UN-RFC 0004                            |
| `Member-Signature` | Closed-group membership proof, UN-RFC 0004                 |
| `Approved-By`   | Moderator key, UN-RFC 0004                                    |
| `Approval`      | Moderator signature, UN-RFC 0004                              |

Any other header MAY be present. Nodes MUST preserve and forward
unknown headers unchanged; they are covered by the signature.

## 2.4 Forbidden

`Path` and `Xref` MUST NOT appear in an article. Nodes MUST reject
articles containing them. (A node MAY *synthesize* them when serving an
article to a newsreader, see UN-RFC 0005, but they are never part of the
article and never forwarded.)

## 2.5 Date Granularity

To reduce timing correlation, clients SHOULD round `Date` **down** to a
multiple of 10 minutes. Nodes MUST reject articles whose `Date` is more
than 1 hour in the future, and MAY reject articles older than the
group's retention period.

# 3. Canonical Form and Signature

The **canonical form** `C` of an article is computed as follows:

1. Take every header **except** `Message-ID`, `Signature`,
   `Proof-Of-Work`, `Member-Signature`, `Approved-By` and `Approval`.
2. Lowercase each header name. Strip leading and trailing whitespace
   (SP, HTAB) from each value.
3. Sort the headers by name, comparing octets.
4. Emit each header as `name ":" SP value CRLF`.
5. Emit one CRLF.
6. Emit the body, with every line ending converted to CRLF. If the body
   does not end in CRLF, append one. (NNTP dot-stuffing is a transport
   matter and is never part of `C`.)

The author signs:

```
Signature = Sign( author_sk, purpose "UNSEENET-ARTICLE-1", C )
```

with the encoding of UN-RFC 0003, section 3.

The excluded headers are excluded because they are either derived from
`C` (Message-ID, Proof-Of-Work), or added by someone other than the
author afterwards (Approval), or are signatures themselves.

# 4. Message-ID

The Message-ID is derived from the signed content:

```
id = first 32 characters of b32( H( DS("UNSEENET-MSGID-1") || C || sig ) )
Message-ID: <id@unseenet>
```

where `sig` is the raw 64-octet Ed25519 signature. This gives 160 bits.

Consequences:

- A Message-ID cannot be chosen freely. An attacker cannot pre-empt a
  legitimate article by injecting a different one with the same ID.
- Two nodes that receive the same article always agree on its ID.
- A node MUST recompute the ID and reject the article if it differs.

# 5. Validation Procedure

A node MUST perform these checks, in this order, before accepting an
article from a client or a peer. A client SHOULD perform them on
articles it displays. Failure at any step means rejection.

1. Size within limit; syntax valid (section 1).
2. `Unseenet-Version` is `1`.
3. All required headers present; no forbidden headers.
4. `Author-Key` and `Signature` use known algorithms and are well formed.
5. Signature verifies over `C` (strict verification, UN-RFC 0003).
6. Message-ID equals the value computed in section 4.
7. Message-ID is not already in the node's history (duplicate). A
   duplicate is not an error for the sender; see UN-RFC 0005.
8. `Date` is within the window of section 2.5.
9. Postage meets the required difficulty (UN-RFC 0006).
10. The group is carried by this node and the article is permitted by
    the group's manifest (UN-RFC 0004). Manifests themselves are
    validated by UN-RFC 0004, section 4.

# 6. Example

```
Unseenet-Version: 1
Message-ID: <q3x7ku2m5a4e6rj2wl9zpn4c8y3h2t5v@unseenet>
Newsgroups: dk.snak@ab3k5x7qwe2rtz4m
Date: Thu, 15 Oct 2026 19:50:00 +0000
From: Andreas
Subject: Hej fra Unseenet
Author-Key: ed25519:...
Content-Type: text/plain; charset=utf-8
Signature: ed25519:...
Proof-Of-Work: sha256; bits=20; nonce=Hk9r2w

Det virker!
```

# 7. Security Considerations

- `Author-Key` is visible to every node, even in closed groups. It links
  articles by the same author. See UN-RFC 0003 section 2 on per-group
  identities.
- Signatures prove authorship to anyone, permanently. An author cannot
  later deny having written a signed article. This is a deliberate
  trade-off for spam resistance and accountability; deniable messaging
  is out of scope for this series.
- The 64 KiB limit is a protection against storage exhaustion and keeps
  the network unsuitable for bulk file distribution.
