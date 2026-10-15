```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0003                                              October 2026
Category: Standards Track
Status: Draft

        Unseenet: Identities, Keys and Cryptographic Primitives
```

# Abstract

This document fixes the encodings, key types, hash functions,
signature scheme and encryption primitives used throughout Unseenet.
Other UN-RFCs refer to the names defined here.

# 1. Encodings

`b32`
: Base32 as in RFC 4648 section 6, **lowercase**, without `=` padding.

`b64`
: Base64url as in RFC 4648 section 5, without `=` padding.

`H(x)`
: SHA-256 of the octet string `x`.

`DS(label)`
: A domain separator: the ASCII string `label` followed by one zero
  octet (0x00). Every hash, signature and key derivation in Unseenet is
  prefixed with a distinct domain separator so that a value made for one
  purpose can never be valid for another.

`||`
: Concatenation of octet strings.

All integers written as text are base-10 ASCII without leading zeros.

# 2. Identities

An identity is an **Ed25519** key pair (RFC 8032, "pure" Ed25519).

The textual form of a public key is

```
ed25519:<b32 of the 32-octet public key>
```

for example `ed25519:4bq5...` (60 characters in total). The algorithm
prefix exists for agility. Implementations MUST reject keys and
signatures with unknown prefixes; they MUST NOT fall back to weaker
algorithms.

The **fingerprint** of a public key is

```
fp(pk) = first 16 characters of b32( H( DS("UNSEENET-FP-1") || pk ) )
```

(80 bits). Fingerprints are used in group IDs (UN-RFC 0004). Clients
SHOULD display at least the first 4 characters next to display names.

A person MAY hold any number of identities. Clients SHOULD make it easy
to use a separate identity per closed group, because a single identity
used everywhere links all of a person's posts together.

Display names (`From` header) are unauthenticated labels. Clients MUST
NOT present two different keys with the same display name as the same
person.

# 3. Signatures

A signature over message `m` for purpose `P` is

```
sig = Ed25519-Sign( sk, DS(P) || m )
```

and is written as `ed25519:<b64 of the 64-octet signature>`.

Purposes defined in this series:

| Purpose label            | Signs                                        | Defined in |
|--------------------------|----------------------------------------------|------------|
| `UNSEENET-ARTICLE-1`     | canonical article                            | 0002       |
| `UNSEENET-MEMBER-1`      | canonical article (closed-group membership)  | 0004       |
| `UNSEENET-APPROVAL-1`    | group ID and Message-ID (moderator approval) | 0004       |

# 4. Encryption

## 4.1 Key Agreement

Encryption to an identity uses the identity's Ed25519 key converted to
X25519 (the birational map used by libsodium's
`crypto_sign_ed25519_pk_to_curve25519` and
`crypto_sign_ed25519_sk_to_curve25519`).

A **sealed box** is libsodium's `crypto_box_seal`: an ephemeral X25519
key, X25519 key agreement, XSalsa20-Poly1305. It hides the sender.

## 4.2 Symmetric Encryption

Group content is encrypted with **XChaCha20-Poly1305** (IETF variant,
libsodium `crypto_aead_xchacha20poly1305_ietf`), 32-octet key,
24-octet random nonce, with associated data as specified by the
caller. The serialized form is `nonce || ciphertext_with_tag`.

Nonces MUST be generated from a cryptographically secure random source.
Given the 192-bit nonce, random nonces are safe for any realistic
number of messages per key.

## 4.3 Key Derivation from a Group Secret

A closed group in epoch *e* has a 32-octet random **group secret** `S`.
Two keys are derived from it:

```
enc_key     = H( DS("UNSEENET-GROUP-ENC-1")    || S )
member_seed = H( DS("UNSEENET-GROUP-MEMBER-1") || S )
```

`member_seed` is used as an Ed25519 seed; its public key is the
**member key** of that epoch (UN-RFC 0004, section 6).

# 5. Node Keys

A node's network identity is its Tor v3 onion service key, which is
itself Ed25519. It is independent of any author identity and is not
used to sign articles. A node operator SHOULD NOT reuse an author key
as the onion service key.

# 6. Random Numbers

All keys, secrets and nonces MUST come from the operating system CSPRNG
(e.g. `getrandom(2)`, `os.urandom`, libsodium `randombytes`).

# 7. Security Considerations

- Ed25519 signatures are deterministic and not malleable when verified
  strictly (RFC 8032 section 5.1.7). Implementations MUST use a strict
  verifier, because Message-IDs depend on signature bytes (UN-RFC 0002).
- The algorithm prefixes allow future migration, e.g. to post-quantum
  signatures, by a later UN-RFC. Until then, Unseenet offers no
  protection against an adversary with a large quantum computer; recorded
  closed-group traffic could be decrypted in such a future.
- Converting Ed25519 keys to X25519 is safe when, as here, the same key
  is used for signatures and sealed-box decryption under strictly
  separated purposes, but implementations MAY instead publish a separate
  X25519 key in a future revision.
