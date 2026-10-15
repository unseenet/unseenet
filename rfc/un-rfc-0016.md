```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0016                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0003, 0005, 0011

          Unseenet: Peer Authentication with Node Keys
```

# Abstract

Nodes that peer authenticate each other with long-term **node keys**
instead of shared passwords. A node proves that it holds its key by
signing a fresh challenge from the node it connects to; the signature is
bound to both keys, so it cannot be replayed or relayed. Peers exchange
only public keys, so nothing secret is written into a peer's
configuration.

# 1. Motivation

UN-RFC 0005 section 5.1 lets peers authenticate with `AUTHINFO USER`
and `AUTHINFO PASS` and a shared secret. That has several weaknesses:

1. The secret is stored in clear in both nodes' configuration, so a leak
   on either side lets anyone push articles as that peer.
2. One secret is used in both directions, and nothing stops an operator
   from giving every peer the same one.
3. Changing it needs both operators to act at the same time.
4. The user name is the peer's self-chosen node name, which carries no
   meaning of its own.

Public keys fix all four. A node that pushes articles proves who it is;
the node it pushes to is already authenticated by its onion address
(UN-RFC 0005 section 1).

# 2. Node Keys

A **node key** is an Ed25519 key pair (UN-RFC 0003) that identifies a
node to its peers. It is distinct from:

- the Tor onion service key, which belongs to Tor and authenticates the
  address;
- the operator's identity key (UN-RFC 0011), which identifies a person.

A node MUST generate its node key on first start and keep it across
restarts. The secret key MUST be stored encrypted (UN-RFC 0007). The
public key is written in the usual form `ed25519:<b32>` and is not
secret.

A node SHOULD show its node key to its operator at start, and MUST
publish it in its node information (UN-RFC 0011) as:

| Field      | Type       | Meaning              |
|------------|------------|----------------------|
| `node_key` | key string | The node's node key  |

# 3. Configuration

UN-RFC 0005 section 5.1 is extended: each configured peer has, in
addition to its onion address and group set,

- the peer's **node key**.

The node uses this key both to accept the peer when it connects
(section 4) and to check that the node it connects to is the peer it
meant (section 4, step 3). A configured name for the peer is a local
label only.

# 4. Protocol

A node that supports this document lists the capability

```
UNSEENET-PEERKEY
```

The connecting node (the **client**, C, with key `kc`) authenticates to
the accepting node (the **server**, S, with key `ks`):

```
C: XUN-PEER <kc>
S: 383 <ks> <nonce>
C: XUN-PEER-PROOF <sig>
S: 281 peer authenticated          (or 481 authentication failed)
```

1. C sends `XUN-PEER` with its node key.
2. S answers `383` with its own node key and a nonce: 32 octets from a
   cryptographically secure random source, in base64 (UN-RFC 0003). S
   MUST answer the same way whether or not `kc` belongs to a configured
   peer, so that the command cannot be used to probe S's peer list. A
   malformed key is answered with `501`.
3. C MUST check that `ks` equals the node key it has configured for the
   peer it meant to reach. If it does not, C MUST NOT continue and MUST
   NOT send any articles on this connection.
4. C computes

   ```
   sig = Sign(sk_c, "UNSEENET-PEER-AUTH-1",  nonce || ks || kc)
   ```

   where `ks` and `kc` are the raw 32-octet public keys, and sends it with
   `XUN-PEER-PROOF`.
5. S accepts if `kc` is the node key of a configured peer and `sig` is a
   valid signature by `kc` over `nonce || ks || kc`. It answers `281`, and
   the connection counts as authenticated as that peer for the rest of
   the session (UN-RFC 0005 section 5.2). Otherwise it answers `481`.

Each nonce MUST be used for at most one `XUN-PEER-PROOF`; S forgets it
after the first attempt, whatever the result. `XUN-PEER-PROOF` without a
preceding `XUN-PEER` is answered with `482`.

# 5. Signature Purpose

UN-RFC 0003 section 3 is extended with:

| Purpose label            | Signs                                   | Defined in |
|--------------------------|-----------------------------------------|------------|
| `UNSEENET-PEER-AUTH-1`   | nonce, server key and client key        | 0016       |

# 6. Accepting Articles from Peers

UN-RFC 0005 section 5.1 allows a node to refuse `IHAVE`, `CHECK` and
`TAKETHIS` from connections that have not authenticated as a peer. With
this document, a node SHOULD do so by default. Clients posting with
`POST` are unaffected.

# 7. Passwords

`AUTHINFO USER`/`PASS` remains valid for compatibility. A node:

- SHOULD warn its operator when a peer is configured with a password
  only;
- MUST compare passwords in constant time;
- MUST ignore a configured password for a peer that has a node key, and
  MUST NOT fall back to a password when key authentication with that peer
  fails (UN-RFC 0000: security is never negotiated down).

# 8. Security Considerations

- **Relay.** A malicious node M that C feeds could forward a challenge
  from a third node S to C, hoping C signs it. C signs `ks` as the key it
  sees, which is M's (C checked it in step 3), so the signature is
  useless at S.
- **Replay.** A nonce is good for one attempt, so a recorded proof cannot
  be used again.
- **Key compromise.** Someone who steals a node's data directory *and*
  its passphrase can act as that node towards its peers until they
  remove or replace its key. Operators replace a node key by generating a
  new one and sending it to their peers; there is no revocation protocol.
- **Guessing.** Signatures cannot be guessed, but a node SHOULD still
  delay its answers to failed attempts and close the connection after a
  few, to save resources.
- **Linkability.** A node key is a stable identifier. It is only shown to
  peers and in node information, which already names the node.

# 9. Implementation Notes (informative)

The reference node keeps the node key in `node_key.vault` next to the
onion key, sealed with the same passphrase, prints it at start
(`Node key: ed25519:...`) and with `unseenet-node --show-key`, and
defaults `require_peer_auth` to true.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
