```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0025                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0002, 0004, 0005, 0006

                 Unseenet: Key Ripening and Standing
```

# Abstract

Identity keys are free, so a spammer can use a new key for every
article and no ban or block ever reaches the next one. This document
makes new keys cost something without giving anybody the power to
decide who may post. A key **ripens** by a verifiable delay function
(VDF) computed over its own public key: a sequential computation that
takes real time on any computer, cannot be sped up by running it on
many machines, and can be checked by anyone in milliseconds. The proof
travels in the article, so every node computes the same standing from
the article alone, with no register, no clock and no third party. Riper
keys pay less postage. Anything that lowers the price of posting must be
verifiable from the article; anything that raises it is a local choice.

# 1. Motivation

UN-RFC 0006 prices articles, not identities. Bans (UN-RFC 0004) and
hierarchy blocks (UN-RFC 0018 section 5.4) act on keys. Together they
fail against the simplest spam script there is: *new key, post, discard
the key, repeat*. Postage alone cannot close the gap, because SHA-256 is
cheap on GPUs (UN-RFC 0006 section 5): any difficulty that stops a
well-equipped spammer stops ordinary users first.

Nodes cannot limit posting by origin either, because a node must never
learn where an article entered the network (UN-RFC 0001). The cost has
to be attached to the key or the article.

The obvious fixes - a reputation service, nodes attesting how old a key
is, requiring an existing member to vouch for newcomers - all create
someone who can decide who may speak. A government, a company or a
clique could then lock people out by pressure on a few operators.
Unseenet does not allow that (section 8).

# 2. Terms

Ripening
: The sequential work a key's holder has done on that key's VDF,
  measured in iterations *t*.

Level
: A step on the ripening scale (section 4), derived from *t*.

Standing
: Everything a node or reader uses to judge a key. In this document,
  only the level is part of the protocol. Local observations are
  allowed but are never required of anyone else (section 6).

# 3. The Ripening Proof

## 3.1 VDF

Ripening uses the Wesolowski VDF over class groups of imaginary
quadratic fields, as deployed in Chia (`chiavdf`). Class groups need no
trusted setup: nobody holds a secret that would let them ripen keys
faster than anyone else.

For an identity public key `pk` (UN-RFC 0003):

```
seed = H( DS("UNSEENET-RIPEN-1") || pk )
D    = discriminant derived from seed, 1024 bits
x    = the generator form (2, 1, c) of the class group of D
y    = x^(2^t)
pi   = Wesolowski proof that y = x^(2^t)
```

The discriminant derivation and the encoding of forms follow `chiavdf`
(`create_discriminant`, compressed form serialization). Section 10 lists
writing these out in full as an open item; until then `chiavdf` is the
normative reference for these two steps.

Because `D` is derived from `pk`, a proof belongs to one key and cannot
be moved to another.

## 3.2 Header

```
Key-Ripening: vdf-cg1; t=<iterations>; y=<b64>; pi=<b64>
```

`Key-Ripening` is a REQUIRED header from this document on (it is added
to the required headers of UN-RFC 0002 section 2). It lies outside the
canonical form, like `Proof-Of-Work`, so it does not change the
signature or the Message-ID, and a node forwards it unchanged.

`y` and `pi` are compressed forms of 100 octets each, so the header is
about 290 characters.

A node verifies the header by checking `pi` for `x`, `y` and `t`. One
verification costs about 4 ms on a current desktop core (section 4.1),
independent of `t`. A node MUST check postage (UN-RFC 0006) before the
ripening proof, so that a flood of articles with bogus proofs costs the
sender postage before it costs the node a verification. Nodes SHOULD
cache the result per `(pk, t, y)`.

A client keeps the VDF state for each of its keys and SHOULD publish a
new proof at least at every level boundary. The client MAY continue the
computation for as long as the key is in use; `t` only grows.

# 4. Levels

| Level | Iterations *t* at least | Fast desktop¹ | ARM server² | Surcharge *s* |
|-------|-------------------------|---------------|-------------|---------------|
| -     | below 2^26              | -             | -           | not accepted³ |
| 0     | 2^26                    | ~7 minutes    | ~11 minutes | +6 bits       |
| 1     | 2^29                    | ~55 minutes   | ~1.5 hours  | +4 bits       |
| 2     | 2^32                    | ~7 hours      | ~12 hours   | +2 bits       |
| 3     | 2^35                    | ~2.5 days     | ~4 days     | 0             |
| 4     | 2^37                    | ~10 days      | ~15 days    | -2 bits       |

¹ Measured: about 165,000 iterations per second with `chiavdf.prove` on
one core of an AMD Ryzen 9 5950X (section 4.1).

² Measured: about 103,000 iterations per second on one Ampere
Neoverse-N1 core (Oracle Cloud Always Free), which is close to what an
older laptop is expected to manage. Laptops, phones and Raspberry Pis
are still to be measured (section 10).

³ Unless the group or node allows level `-` (section 5).

A key's level is the highest row whose threshold its proof meets.

## 4.1 Measurements

`scripts/bench-ripening.py` in the reference implementation measures
proving and verification on one core. First results, 1024-bit
discriminant:

| What                                   | Ryzen 9 5950X | Neoverse-N1 (ARM) |
|----------------------------------------|---------------|-------------------|
| `chiavdf.prove` (squaring and proof)   | ~165,000 it/s | ~103,000 it/s     |
| `vdf_bench square_asm` (squaring only, hand-optimized assembly, as used by Chia timelords) | ~200,000 it/s | not measured |
| `chiavdf.verify_wesolowski`, any *t*   | ~3.7 ms       | ~6.8 ms           |
| `y` plus `pi`                          | 200 octets    | 200 octets        |

A one-core ARM node can thus verify about 150 ripening proofs per
second before caching, which is far more than the article rate of a
small network.

A spammer with the best available software therefore gains only about
a factor 1.3 over the reference client on the same processor. The gap
between machines is the gap in single-core speed, a small factor, not
the orders of magnitude of SHA-256 on GPUs.

# 5. Required Postage

This section replaces the formula in UN-RFC 0006 section 3:

```
required = max( floor_pow,
                max(node_min_pow, group_min_pow) + s(level) )
```

where `s(level)` is the surcharge from section 4 and `floor_pow` is 12.
A key below the node's or the group's minimum level is not accepted.

The minimum levels are advertised like the minimum postage:

- a node advertises `UNSEENET-MINRIPE <level>` (UN-RFC 0005), default 0;
- a manifest MAY set `min_ripe` (UN-RFC 0004), an integer level or `-`,
  default 0. A closed group may set `-`, because its owner already
  admits its members.

A node SHOULD NOT forward an article to a peer whose advertised minimum
level the article does not meet, just as for postage.

With the RECOMMENDED defaults of UN-RFC 0006 (node 18, open groups 20)
a brand-new key pays 26 bits in an open group, about a minute in
CPython, while a key at level 4 pays 18 bits.

# 6. Local Standing

A node or a reader MAY judge keys by more than their level: the number
of articles it has seen from the key, spam reports from issuers it
follows (#122), duplicate detection (#123), its own block lists. Such
local standing:

- MAY make the node stricter for articles it accepts or forwards, and
  MAY make a client hide articles;
- MUST NOT be required of other nodes, and MUST NOT be presented to
  others as a property of the key;
- MUST NOT lower the price of posting below what section 5 gives.

This is the rule that keeps standing decentralized: **anything that
lowers the cost of posting is verifiable by anyone from the article
itself; anything that raises it is a local choice.** Nobody can take a
key's level away from it on other nodes. Anyone who disagrees with a
node's local choices can post through another node or run their own.

# 7. Clients

- A client SHOULD start ripening a key as soon as it is created, run it
  while the client is open, keep the state in the encrypted vault
  (UN-RFC 0007), and resume after a restart.
- A client SHOULD show the level and the time to the next level, and say
  plainly why a fresh key cannot post at once.
- A user who wants a one-off identity can still have one: it costs about
  ten minutes of waiting and a higher postage on its articles, not
  permission from anybody.
- On battery-powered devices a client SHOULD ripen only while charging,
  unless the user chooses otherwise.

# 8. Rationale

**Why a VDF rather than more proof of work.** Proof of work is parallel:
a GPU farm does in a second what a laptop does in an hour. A VDF is
sequential: the best hardware is only a small factor faster than an
ordinary laptop core, so the spammer's advantage shrinks from several
orders of magnitude to a constant. A spammer can still ripen many keys
at once, but each key costs real core-time, so a key that gets banned
is a loss. That is enough to make bans and blocks meaningful again,
which is the point.

**Why not memory-hard postage (Argon2id).** It narrows the GPU gap but
costs as much to verify as one attempt, which turns verification into
a denial-of-service lever against nodes. A Wesolowski proof is verified
in milliseconds.

**Why no attestations, reputation servers or required vouching.**
Each of them creates an authority. Whoever runs the service, or the
nodes whose attestation counts, could be pressured to refuse keys.
Ripening needs only the key holder's own computer and time. Vouching may
come later as an optional shortcut, but never as the only way in.

**Why levels and not a continuous formula.** Levels are easy to
advertise, to explain to users and to change by a later document.

# 9. Security Considerations

- **Botnets.** A botnet ripens many keys in parallel. Ripening does not
  make spam impossible; it makes every key cost real time, so that bans,
  blocks and spam reports cost the spammer something.
- **Faster software and hardware.** Hand-optimized code is about 1.3
  times faster than the reference client on the same processor
  (section 4.1); the fastest desktop cores are a small factor faster than
  old laptops. Dedicated hardware might do more, perhaps a factor of
  ten. All of this shortens ripening for one key; none of it makes
  thousands of keys cheap.
- **Stolen keys.** A thief who takes a vault also takes the ripening of
  its keys. This is one more reason to protect the vault (UN-RFC 0007).
- **Trade in ripe keys.** Ripened keys could be sold. A sold key is still
  one key and is lost when banned or reported.
- **Linkability.** The level shows roughly how much work went into a key.
  It reveals nothing about the holder or where they post from.
- **Parameters.** 1024-bit discriminants follow Chia's choice. Ripening
  only needs to resist computation for weeks, not decades.

# 10. Open Issues

- Measure older laptops, a Raspberry Pi, Apple Silicon and an Android
  phone with `scripts/bench-ripening.py` and adjust the thresholds in
  section 4, which so far rest on a fast desktop and an ARM server.
- Write out the discriminant derivation and form encoding normatively,
  so implementations do not depend on `chiavdf`.
- `chiavdf` publishes wheels for Linux x86-64 and ARM64, Windows and
  macOS on Apple Silicon (an older version there). A client on Android
  needs its own build or a verifier of its own.
- Transition: during pre-alpha, should nodes accept articles without
  `Key-Ripening` at level `-` for a fixed period?
- Whether proofs for long-lived keys should be refreshed periodically.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
