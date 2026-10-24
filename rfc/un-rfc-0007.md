```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0007                                              October 2026
Category: Informational
Status: Draft

                Unseenet: Protecting Data at Rest
```

# Abstract

This document gives recommended practice for protecting Unseenet data
stored on clients (often USB sticks) and nodes against theft and
seizure. It is informational: interoperability does not depend on it,
but implementations are expected to follow it.

# 1. Threat Model

| Threat                                     | Protected?                       |
|--------------------------------------------|----------------------------------|
| USB stick lost or seized while unplugged   | Yes, with this document          |
| Node disk seized while powered off         | Yes, with this document          |
| Node seized while running                  | Closed-group content: yes (nodes never hold keys). Everything else on the node: no |
| Client run on a compromised computer       | No. Use a trusted OS (e.g. Tails) |
| Compelled disclosure of a passphrase       | No (legal, not technical)         |

# 2. Client (USB) Storage

## 2.1 Vault

All client state — identities, group secrets, subscriptions, cached
articles, settings — SHOULD be kept in a single encrypted **vault**
file, so that the stick holds nothing readable without the passphrase.
Since UN-RFC 0044, what is not a key or a group secret is also kept,
encrypted, in the network, so the vault's own copy of it is a local copy
that the network can restore; the format is unchanged.
The recommended format is:

```
magic     "UNSVAULT1"            9 octets
opslimit  uint32 big-endian      4 octets
memlimit  uint32 big-endian, KiB 4 octets
salt      16 octets
box       XSalsa20-Poly1305 secretbox of the payload (nonce || ciphertext)
```

The key is derived with **Argon2id** from the passphrase and salt.
RECOMMENDED parameters: opslimit 3, memlimit 256 MiB (libsodium
"moderate"). Implementations MAY use higher values.

## 2.2 Working in Memory

The decrypted payload SHOULD never be written to disk. A practical
approach is an in-memory SQLite database that is serialized, encrypted
and written atomically (write to temporary file in the same directory,
then rename) on every save.

## 2.3 Host Hygiene

A client running from a USB stick SHOULD NOT write anything to the host
computer: no temporary files outside the stick, no logs, no caches. Tor
data (consensus cache) SHOULD live on the stick or in memory.

# 3. Node Storage

1. The node's data directory SHOULD be on a block device encrypted with
   e.g. LUKS. Unlocking SHOULD require operator interaction at boot (for
   headless machines, e.g. SSH into the initramfs), so the key is never
   stored on the machine.
2. The onion service private key SHOULD be stored encrypted with a
   passphrase and handed to Tor at runtime through the control port
   (`ADD_ONION`), so that Tor never writes it to its own directory.
3. Nodes never hold closed-group secrets. Closed-group articles are
   stored as received: encrypted.
4. Nodes SHOULD log as little as possible and never log client circuit
   information, Message-IDs per connection, or reading patterns.

# 4. Limits of Software Protection

- Garbage-collected languages such as Python cannot reliably erase
  secrets from memory, and secrets may reach swap. Users with a strong
  adversary SHOULD run the client on an amnesic system with no swap,
  such as Tails.
- A running, unlocked machine can be read by whoever holds it. Nothing
  in this document changes that.
- Encryption does not hide that Unseenet is installed. Users for whom
  that is itself a risk should consider the legal situation where they
  live.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
