```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0006                                              October 2026
Category: Standards Track
Status: Draft

                  Unseenet: Proof-of-Work Postage
```

# Abstract

Anonymous identities are free, so Unseenet prices posting instead:
every article carries a proof of computational work ("postage"), in
the spirit of Hashcash. This document defines the postage algorithm,
its header, and how required difficulty is determined.

# 1. Header

```
Proof-Of-Work: sha256; bits=<n>; nonce=<b64>
```

`bits` is the claimed number of leading zero bits; `nonce` is 1 to 32
octets chosen by the poster.

# 2. Algorithm

Let `C` be the canonical form of the article (UN-RFC 0002 section 3).

```
digest = H( DS("UNSEENET-POW-1") || H(C) || nonce )
```

The postage is valid with difficulty *n* if `digest` begins with at
least *n* zero bits (most significant bit of the first octet first).
The claimed `bits` value MUST be at least *n*, and the digest MUST
actually have at least `bits` leading zero bits.

Postage covers the canonical form, so it cannot be moved to another
article, and it is outside the canonical form, so it does not change
the signature or the Message-ID.

# 3. Required Difficulty

The difficulty an article must meet at a node is

```
required = max( node_min_pow, group_min_pow )
```

where `node_min_pow` is advertised as `UNSEENET-MINPOW` (UN-RFC 0005)
and `group_min_pow` is the current manifest's `min_pow` (UN-RFC 0004),
which does not apply to manifests themselves.

A node MAY raise its minimum temporarily under load. Articles already
accepted are not re-checked.

Peers may have different minimums. A node SHOULD NOT forward an article
to a peer whose advertised minimum the article does not meet.

# 4. Guidance

Rough cost of *n* bits is 2^n hash evaluations:

| bits | hashes  | ~CPython on a laptop | ~native code |
|------|---------|----------------------|--------------|
| 16   | 65 k    | < 0.1 s              | instant      |
| 20   | 1 M     | ~1 s                 | ~0.05 s      |
| 22   | 4 M     | ~4 s                 | ~0.2 s       |
| 24   | 16 M    | ~15 s                | ~1 s         |

RECOMMENDED defaults: node minimum 18, open groups 20. Busy open
groups under spam pressure may raise `min_pow`.

# 5. Considerations

- SHA-256 is cheap on GPUs and ASICs, so a well-equipped spammer has an
  advantage of several orders of magnitude over an ordinary user. The
  algorithm name (`sha256`) exists so that a memory-hard algorithm (e.g.
  Argon2id) can be added by a later UN-RFC. The name `argon2id` is
  reserved for that purpose.
- Postage is deliberately useless work. "Useful" proof-of-work, such
  as the work units of volunteer computing projects (SETI@home and
  other BOINC projects, or Folding@home), was considered and rejected.
  Postage needs four properties such work lacks: the puzzle is derived
  from the article itself, so it cannot be computed in advance or
  reused; any node can verify it with one hash evaluation without
  trusting anyone; its difficulty can be set to any number of bits; and
  no party issues or judges the work. Volunteer computing hands out
  work units from a central server, checks results by having other
  machines recompute them, and cannot bind a unit to an article. A
  central issuer would also learn when a client is about to post, which
  works against hiding where an article entered the network.
- Puzzles that are both useful and cheap to verify do exist, for
  example searching for prime chains from an origin derived from a hash
  (as in Primecoin). They keep the properties above but add complexity
  for marginal value. At a few seconds per article, the total work of
  the network would in any case be small next to a single machine
  running volunteer computing full time. Operators who want their
  hardware to do useful work can run such software beside their node;
  it is not part of the protocol.
- Postage limits volume; it does not judge content. Content filtering
  remains the job of moderators, node operators and readers
  (UN-RFC 0001 section 4).

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
