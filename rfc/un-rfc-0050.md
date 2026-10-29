```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0050                                              October 2026
Category: Standards Track
Status: Draft
Implemented: unseenet 0.6.0, unseenet-entrance 0.3.0, unseenet-gui 0.3.0
Updates: 0005, 0007

      Unseenet: Copying an Identity to Another Device, and Recovery Words
```

# Abstract

People want the same identity on more than one device: a stick and a
PC, a PC and a phone, a second PC. They also need a way back when a
stick is lost or a phone is stolen. This document specifies two things.
**Copying** sends identities from a device that has them to a new one,
over Tor, protected by a short one-time code shown as text and as a QR
code. **Recovery words** show an identity's key as 24 words that the
user writes down, and that bring the identity back on any device; the
rest of what the user had comes from the network (UN-RFC 0044). Neither
needs a service that holds vaults, and neither lets a PIN protect a
vault that someone else can get hold of.

# 1. Motivation

UN-RFC 0007 keeps everything in one encrypted vault file. That is right
for a stick, but moving the file by hand is hard on phones and tablets,
and people who find it hard will send it through cloud folders and chat
apps instead.

An obvious answer is a "vault in the cloud": a service that keeps the
vault and gives it back for a PIN the user chooses. A PIN has between
10,000 and 1,000,000 possibilities. Whoever gets the stored file - the
service's operator, someone who seizes or breaks into the service - can
try them all in minutes, whatever key derivation is used. Services that
make a PIN safe (Signal's PIN, phone makers' backup) do it with hardware
on their servers that counts guesses and erases after a few. That is a
central party everyone must trust, and a target. It does not fit a
network where nobody has control (UN-RFC 0001).

Since UN-RFC 0044, almost everything a user has follows their key
through the network: subscriptions, contacts, read marks, settings,
copies of sent private posts. What must be carried by hand is the keys.
This document makes carrying them easy in the two cases that matter:
from one device to another while both are at hand (section 3), and back
from nothing (section 4).

# 2. Terms

- **Old device**: the device that has the vault.
- **New device**: the device that receives a copy. "New" means new to
  this identity; it may already have other identities.
- **Copy**: the keys end up on both devices. The old device keeps
  everything. A user may copy to any number of devices.
- **Code**: the short one-time code of a copy, such as `7-guitar-tunnel`.
- **Recovery words**: 24 words that encode one identity's seed.

# 3. Copying an Identity

## 3.1 What the User Sees

On the old device the user chooses *Copy to another device…*. The
client asks for the vault passphrase if the vault is locked, lets the
user choose what to copy (section 3.6), and shows a QR code and a code
such as `7-guitar-tunnel`.

On the new device the user chooses *Get identity from another device*,
offered at first start next to *Create a new identity* and *Restore
from recovery words*, and in the palette. They scan the QR code or type
the code.

Both devices then show the same two **check words** (section 3.5). The
user confirms on the old device that they match, the identities are
sent, and the new device asks for its own passphrase (or PIN, section
5) and writes its vault. The state then comes from the network
(UN-RFC 0044 section 7.3).

## 3.2 The Code

A code has three parts: `<n>-<word1>-<word2>`.

- `word1` and `word2` are chosen at random by the old device from the
  BIP39 English word list (2048 words), giving 22 bits.
- `n` is a number from 1 to 999 given by the meeting point (section
  3.3). It is not secret.

The QR code carries everything the new device needs without a meeting
point:

```
unseenet-copy:1:<onion address of the old device>:<code>
```

A code is valid for one attempt and at most 10 minutes. After a failed
attempt, a cancel, or the time limit, the old device closes its onion
service and the user must start again with a new code.

## 3.3 The Meeting Point

The old device opens a one-time onion service for the copy, in the Tor
it already runs, with `ADD_ONION` and `Flags=DiscardPK` so that no key
is kept, and removes it with `DEL_ONION` when the copy ends.

With the QR code the new device connects to it directly. With a typed
code it must first learn the onion address. For that, nodes offer a
**meeting point**: a small table, kept in memory only, never replicated
to peers and never logged, from which a record is fetched once.

```
XUNMEET OPEN <onion-address> <tag>     -> 290 <n>
XUNMEET LOOKUP <n> <tag>               -> 291 <onion-address>
                                       -> 490 no such meeting
```

where

```
tag = hex(H(DS("UNSEENET-COPY-TAG-1") || word1 || "-" || word2)[0:16])
```

`OPEN` gives the record a number `n` that is unique among the node's
open records, and the record lives 10 minutes. `LOOKUP` returns the
address only when both `n` and `tag` match, and then deletes the
record. A node SHOULD allow at most 3 non-matching lookups for one `n`,
then delete that record, and SHOULD limit `OPEN` and `LOOKUP` per
connection.

Both devices use the project's known-node list (UN-RFC 0010 section 6),
which every client carries. The old device opens the meeting at the
first node in the list that it can reach and that advertises the
`XUNMEET` capability. The new device asks those nodes in the same order
until one returns an address. Because the tag must match, asking the
wrong node finds nothing and disturbs nobody else's copy.

The node learns that some device, at some time, is copying something.
It does not learn which identity, and it learns no more than the
one-time onion address, which is worthless once the copy is over.

## 3.4 The Exchange

The new device connects to the old device's onion service. The two run
**SPAKE2** (over Ed25519, as used by Magic Wormhole) with the whole code
as the password and the identities `unseenet-copy-old` and
`unseenet-copy-new`, giving a shared key `K`. Each side then sends a
confirmation, `H(DS("UNSEENET-COPY-CONFIRM-1") || role || K)`, and
checks the other's. If a confirmation is wrong, the old device closes
the onion service: the code is used up.

A PAKE gives an attacker who does not know the code exactly one guess
online, and nothing to try offline. With 22 bits that is a chance of
about one in four million, and the attempt is visible, because the
user's own copy then fails.

From `K`:

```
copy_key    = H(DS("UNSEENET-COPY-KEY-1")    || K)
check_value = H(DS("UNSEENET-COPY-CHECK-1")  || K)
```

## 3.5 Check Words

Both devices show two words chosen from the BIP39 list by the first 22
bits of `check_value`. The old device sends nothing until the user has
confirmed there that the words match those on the new device.

This protects against someone who saw the code - on the screen, over a
shoulder, in a photo - and connects first. They would get their own
`K` and their own check words, which do not match the user's new device.

## 3.6 What Is Copied

The old device sends one message, encrypted with XChaCha20-Poly1305
under `copy_key` (UN-RFC 0003): the chosen parts of the vault payload
(UN-RFC 0007 section 2.1) in the vault's own format.

- By default: every identity in the vault, and the group secrets of the
  closed groups those identities are in.
- The user MAY deselect identities, and MAY leave out group secrets.
  Clients SHOULD make leaving out an identity easy, since a phone is
  more often lost than a stick.
- Never copied: the cache (it comes from nodes) and the local copy of
  the state (it comes from the network).

The new device answers with an acknowledgement, and both close the
connection. The old device then removes the onion service.

## 3.7 The New Device's Vault

The new device writes a vault of its own, under its own passphrase, as
in UN-RFC 0007 section 2.1, or with a PIN where section 5 allows it. If
it already has a vault, the user unlocks it and the copied identities
are added to it. An identity that is already there is not overwritten;
missing group secrets are added.

After a copy the two vaults are separate files. What is in the state
(UN-RFC 0044) follows the key and is merged as usual. Group secrets of
closed groups joined later on one device do not reach the other; to
bring them over, the user copies again (section 3.6 adds missing group
secrets). They are never put in the network (section 4.5).

## 3.8 Devices That Cannot Open an Onion Service

A client that runs in a browser through a web entrance (UN-RFC 0043)
cannot open an onion service. It MAY take part as the new device, using
the QR code or meeting point, when its entrance allows a connection to
the one-time onion address. It cannot be the old device in this
version (section 9).

## 3.9 The Connection

The old device's one-time onion service listens on virtual port 9119.
Every message on the connection is a 4-octet length, big-endian,
followed by that many octets. A message is at most 64 KiB, except the
copy (step 5), which is at most 1 MiB. A device that receives anything
else, or a message out of order, closes the connection; the old device
then removes its onion service (the code is used up, section 3.2).

1. **Hello.** Each side sends `UNSEENET-COPY-1` (ASCII) and checks the
   other's. A later version of this document changes the number.
2. **SPAKE2.** Each side sends its SPAKE2 message (section 3.4). The
   password is the code in its normal form, `<n>-<word1>-<word2>` with
   full words in lower case, however it was typed; the old device is
   SPAKE2's side A with identity `unseenet-copy-old`, the new device side
   B with `unseenet-copy-new`, both ASCII.
3. **Confirmation.** In `H(DS("UNSEENET-COPY-CONFIRM-1") || role || K)`
   (section 3.4) `role` is the sender's SPAKE2 identity, so the two
   confirmations differ. The new device sends its confirmation; the old
   device checks it and only then sends its own; the new device checks
   that. Either side closes on a wrong one.
4. **Check words.** Both show the check words (section 3.5): the first
   22 bits of `check_value`, most significant first, as two numbers of
   11 bits, each picking a word from the BIP39 English list. The new
   device waits; the old device waits for the user, at most until the
   code's 10 minutes are over. If the user says the words do not match,
   or cancels, the old device closes the connection without sending
   anything.
5. **The copy.** The old device sends `aead(copy_key, payload, aad)`:
   a 24-octet nonce followed by the XChaCha20-Poly1305 ciphertext
   (UN-RFC 0003 section 4.2), with `aad` the ASCII `UNSEENET-COPY-1`.
   `payload` is canonical JSON (UN-RFC 0004):

   ```
   {"v": 1,
    "identities": {"<name>": {"seed": "<64 hex>", "display": "...",
                              "signature": "..."}},
    "default": "<name>",
    "groups": {"<group ID>": {"keys": {"<epoch>": "<64 hex>"}}}}
   ```

   `identities` holds the chosen identities (section 3.6), with their
   name in the vault, `display` and `signature` (which may be absent);
   `default` is one of them; `groups` holds the secrets of the closed
   groups to copy, per epoch, and is empty when the user left them out.
6. **Acknowledgement.** The new device writes its vault (section 3.7)
   and sends `aead(copy_key, answer, aad)`, `answer` being
   `{"ok": true, "added": ["<name>", ...]}` or `{"ok": false, "error":
   "..."}`. Both close the connection, and the old device removes its
   onion service.

A client that reaches Tor without its control port - a Tor it did not
start and may not control, such as the system Tor on Tails - cannot
open an onion service and cannot be the old device. It can be the new
device, and says so when the user tries to copy from it.

# 4. Recovery Words

## 4.1 Encoding

An identity is a 32-octet Ed25519 seed (UN-RFC 0003). Its recovery
words encode that seed directly:

1. `checksum` = the first 8 bits of SHA-256(seed).
2. The 256 bits of the seed followed by the 8 checksum bits give 264
   bits, read as 24 numbers of 11 bits, most significant first.
3. Each number picks a word from the BIP39 English word list.

This is BIP39's encoding of entropy, but not its seed derivation: the
words are the seed itself, not a password for PBKDF2. So every existing
identity has recovery words, and nothing about keys changes. Clients
MUST call them "Unseenet recovery words" and SHOULD say they are not a
cryptocurrency wallet phrase, so nobody types them into a wallet.

Clients MUST accept words in any case, with extra spaces, and SHOULD
accept the first four letters of each word, which identify a BIP39 word
uniquely. A wrong checksum MUST be reported as a typing mistake before
anything else happens.

Each identity has its own words. A vault with several identities has
several sets of words.

## 4.2 Showing the Words

When an identity is created, the client SHOULD show its words and ask
the user to write them down, then ask for three of them back as a
check. With the words the client MUST say, in plain language, that they
bring back the identity but not access to closed groups (section 4.5). The user MAY skip this; the client then reminds them later,
gently and not more than once a week, until it is done.

The words can be shown again at any time with *Show recovery words…*,
which MUST ask for the vault passphrase (or PIN) first, even when the
vault is unlocked. Clients SHOULD NOT show them while the screen is
being shared or recorded, where the platform tells them so.

## 4.3 Saving and Printing

Writing the words on paper is the recommended way. A client MAY also
offer:

- **Print**: a page with the identity's name, fingerprint, the 24
  words, a QR code of the words, and a short text on how to restore,
  that closed groups do not come back, and why the page must be kept
  safe.
- **Save as file**: a plain text file with the same content.

Both MUST be deliberate choices, behind a warning that whoever has the
page or file *is* the user, in the same way as whoever has the vault
and its passphrase. In addition, a client:

- MUST NOT save the words on its own, in the vault, in the state, in a
  log, or anywhere in the network;
- MUST NOT save them on the same medium as the vault - a seized stick
  would otherwise give everything away - and SHOULD propose another
  stick or a printout instead;
- SHOULD warn when the chosen folder looks synchronised to a cloud
  service (Dropbox, OneDrive, iCloud Drive, Google Drive and the like);
- SHOULD NOT offer saving or printing on the bootable client, whose users
  are those who most need to hide (only showing the words, to write
  down).

## 4.4 Restoring

At first start, or from the palette, *Restore from recovery words*:

1. The user types the words; the client checks the checksum and
   rebuilds the key.
2. The client shows the fingerprint and, once found, the identity's
   name and profile, so the user sees it is the right one.
3. It asks for a passphrase (or PIN) for the vault on this device.
4. It fetches the state, `state@<fp>` (UN-RFC 0044 section 7.3), and
   with it subscriptions, contacts, read marks, settings and where the
   copies of sent private posts are. The inbox (UN-RFC 0009) still
   holds what others sent, as long as it lives.

What is bound to the key comes back with it: names (UN-RFC 0019),
profiles (UN-RFC 0022), groups the identity owns, and key ripening
(UN-RFC 0025), since `ripe@<fp>` belongs to the same key.

If no state is found - a new key, or one whose state has expired - the
client says so plainly and starts with the default groups.

## 4.5 What Does Not Come Back

- **Access to closed groups.** Their group secrets are kept only in
  the vault (UN-RFC 0044 section 2) and are never put in the network,
  not even sealed to the identity's own key. This is the price of
  recovery words, and it is deliberate: if the words also opened closed
  groups, whoever finds the words would have every closed group too.
  After a restore the client MUST say plainly that closed groups do not
  come back, list the closed groups the state says the user follows,
  and offer to ask each group's owner, by private post, to invite the
  user again. A copy from another device (section 3) does bring them.
- **The cache**, which nodes provide again.
- Anything older than the network keeps (UN-RFC 0012).

# 5. PINs on a Device

A PIN is short enough to type on a phone, and too short to protect a
file someone else can get hold of. A client MAY let a user unlock a
vault with a PIN only where the device itself limits guesses:

- The vault key (UN-RFC 0007 section 2.1) is wrapped by a key held in
  the device's secure hardware - Android Keystore (StrongBox where
  available), the Secure Enclave on Apple devices, a TPM, or a passkey
  with the WebAuthn PRF extension in a browser - which releases it only
  after the PIN or the device's own unlock, and limits attempts.
- The vault still has a passphrase, set by the user or generated and
  shown once, so it can be opened elsewhere and so a copy of the file
  alone is protected by Argon2id as before.

Elsewhere - a stick, the bootable client, a device without such
hardware - the vault is opened with its passphrase only. A client MUST
NOT store or send a vault anywhere protected only by a PIN.

# 6. Changes to Nodes

The meeting point (section 3.3) is the only change to nodes. A node that
offers it advertises the `XUNMEET` capability (UN-RFC 0005). Nodes
SHOULD offer it; it costs little memory and nothing on disk. The name
keeps the experimental prefix (UN-RFC 0000 section 5) until this
document is accepted.

# 7. Security and Privacy Considerations

- **Recovery words are the key.** Anyone who reads them can be the
  user, read their private posts and inbox, and post in their name.
  Clients say so whenever the words are shown, printed or saved.
- **More copies, more risk.** Every device with a copy is one more that
  can be lost, stolen or seized. Clients make it easy to copy only some
  identities, and a user who needs to hide should keep an identity on
  the stick or bootable client only.
- **A seen code.** Someone who sees the code during its 10 minutes and
  connects first gets mismatched check words (section 3.5); nothing is
  sent unless the user confirms a match. The worst they can do is make
  the user start again.
- **The meeting point** learns that a copy happens, at what time, and a
  one-time onion address. It learns no identity, no key and no code.
  Because the tag covers only 22 bits, a node could find the two words
  by trying them, but the words are useless without connecting to the
  onion service in time, and the check words still stop it there.
- **No service holds vaults.** There is nothing central to seize, force
  or break into. A legal demand for a passphrase or for the words
  remains possible, as in UN-RFC 0007 section 1.
- **Devices.** Copying puts keys on devices with their own risks
  (backups made by the phone's system, screenshots, keyboards that
  learn words). Clients SHOULD keep the vault out of system backups
  where the platform allows it, and SHOULD ask for a keyboard without
  learning when the words are typed.

# 8. Rationale

- **No vault in the cloud.** Section 1: a stored vault protected by a
  PIN is broken by whoever stores it, and making it safe needs a
  trusted central party. A stored vault protected by a strong
  passphrase is safe but adds little over recovery words, which need no
  storage at all.
- **A PAKE, not a code used as a key.** Using the short code to encrypt
  the vault directly would let anyone who captured the traffic try all
  four million codes offline. SPAKE2 makes every guess an online one.
- **An onion service on the old device.** The copy goes straight from
  device to device. Carrying the vault through a node, even encrypted,
  would put it on a third machine; the meeting point carries only an
  address.
- **BIP39's word list.** It is well known, chosen so words are easy to
  tell apart, and has libraries everywhere. Using its encoding but not
  its PBKDF2 step lets the words be the existing seed.
- **Closed groups do not come back.** One secret - the words - opening
  the identity, its state and every closed group would make the words
  worth far more to whoever finds them. Losing closed groups on a
  restore is the price, and clients say so up front.
- **24 words.** The seed is 256 bits. Fewer words would mean a weaker
  key or a different key than the one users already have.

# 9. Open Questions

- **Browser clients as the old device.** An entrance could relay the
  copy stream (it would see only SPAKE2 messages and ciphertext). Is
  that worth the extra load and trust?
- **Word lists in other languages**, such as Danish. BIP39 has lists for
  some languages, not Danish; a list of our own would need care so that
  words are easy to tell apart.
- **The meeting point's node.** Is the first reachable node in the
  project's list right, or should the code name a node?

# 10. Changes to Other Documents

- UN-RFC 0005: the `XUNMEET` capability and commands (section 3.3).
- UN-RFC 0007 section 2.1: a vault may be copied to another device
  (section 3), its identities may be shown as recovery words (section
  4), and a PIN may unlock it only as in section 5.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
