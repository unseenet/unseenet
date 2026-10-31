```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0062                                              October 2026
Category: Standards Track
Status: Draft
Implemented: -
Updates: 0043

        Unseenet: Update Channels, Publishers and Signatures
```

# Abstract

Unseenet is its protocol, not one project's code: anybody may build
nodes and clients that follow the UN-RFCs. What one project's key can
still do is send an update to every stick that updates from that
project. If that key is stolen, the thief can send anything. This
document makes a stable release valid only with signatures from several
of a **publisher**'s keys - two of three for the project - lets the
publisher change its keys only with the same number of signatures, and
lets each user choose which publishers their stick takes updates from.
A stolen key alone can then send nothing, and nobody is bound to one
publisher.

# 1. Motivation

A stick updates itself (`unseenet.update`) when `SHA256SUMS.txt` of a
release is signed by a key it trusts, and today the stable channel
trusts one key: the project key. That is not a single point of
*failure* for the network - nodes and clients keep running if the
project disappears, and anyone can build their own - but it is a single
point of *takeover* for every stick that updates from the project.

Three things fix that without a council (a builder council is a later
step, section 8):

1. more than one signature on a release, from keys kept apart;
2. the set of keys changes only with as many signatures as a release
   needs, so a stolen key cannot swap in its own;
3. users choose their publishers, so a publisher that goes bad or goes
   away can be replaced from the stick itself.

# 2. Terms

- **Publisher:** whoever builds and signs releases of a client or
  bundle, identified by its **releases channel**: a channel group where
  it posts its releases (UN-RFC 0043), and by its key list.
- **Key list:** the publisher's release keys and how many of them a
  release needs (`threshold`).
- **Signer:** a key in the key list.

The key words "MUST", "SHOULD" and "MAY" are as in UN-RFC 0000
section 2.

# 3. The Key List

A publisher's key list is a chain of articles in its releases channel,
each with `Subject: release-keys <seq>`, `Content-Type:
application/json` and a canonical JSON body:

| Field       | Type          | Req.          | Meaning                                    |
|-------------|---------------|---------------|--------------------------------------------|
| `v`         | integer       | yes           | `1`                                        |
| `seq`       | integer       | yes           | `1`, then one more each time               |
| `prev`      | b64 string    | from `seq` 2  | `H(DS("UNSEENET-RELEASE-KEYS-1") || body)` of the list with `seq - 1` |
| `keys`      | array of keys | yes           | The signers; at most 8                     |
| `threshold` | integer       | yes           | Signatures a stable release needs; at least 1, at most the number of `keys` |
| `channels`  | object        | no            | Thresholds per channel, e.g. `{"dev": 1}`; others use `threshold` |

The list with `seq` 1 is pinned by the client that trusts the publisher
(section 6). A later list **counts** when the one before it counts, its
`prev` is that list's hash, and at least that list's `threshold`
different signers of it have each posted an article with exactly its
body. This is the pattern of UN-RFC 0054 section 5 and of TUF's root
keys: the old keys vote the new ones in. The owner of the releases
channel cannot change the key list; the channel only carries it.

Two counting lists with the same `seq` are a **fork**. A client that sees
one MUST NOT take updates from that publisher until the user acts, and
SHOULD tell the user.

# 4. Signing a Release

`SHA256SUMS.txt.sig` holds one or more signature blocks, each as today:

```
Unseenet release signature
key: ed25519:...
signature: ...
```

separated by an empty line. Each signs the same `SHA256SUMS.txt` with
the purpose `UNSEENET-RELEASE-1`. A release is valid for a channel when
at least that channel's threshold of **different** signers of the
current key list have signed it, and the files match the checksums.
Signers sign one after another; the publisher's tool adds a block to the
file and uploads it again until the threshold is reached.

A file with a single block, as before this document, is valid exactly
when the threshold is 1.

# 5. The Project's Publisher

The project publishes the reference client and bundles in
`unseenet.releases` (UN-RFC 0043). Its first key list is

- `keys`: the project key and two reserve keys, kept offline on
  separate media, by the maintainer at first;
- `threshold`: 2;
- `channels`: `{"dev": 1}`, with the CI key that signs development
  builds added for that channel only (section 3, `channels`).

Every release of the project names, in its `SHA256SUMS.txt`, a source
bundle `unseenet-source-<version>.tar.gz`: the source, at the release's
tags, of every repository the release is built from, of every Python
package it installs, and of the Tor it ships, each with its licence.
Systems a bundle is built on but does not write itself (the operating
system of a bootable image) are named by version, not included. The
bundle is what scribes keep (UN-RFC 0020 section 6.4): with it, anybody
can rebuild the release, and continue it, without the project.

Two of three means that one stolen key sends nothing, and one lost key
does not stop releases: the two others can sign, and can post a new key
list without it.

## 5.1 What Is Signed

Everything a publisher releases is signed this way, not only the core
and the bundles: each client and each service that runs as a server -
a node, a council replica, a gateway, an entrance, a scribe, a bot - is
a release of its own, with its own `SHA256SUMS.txt` naming its packages
and its source bundle. A program that updates itself trusts nothing
else.

# 6. Choosing Publishers

A client keeps a list of the publishers it takes updates from, each as
its releases channel's Group ID and the pinned first key list. The
reference client starts with the project's. A user MAY

- add a publisher from an `unseenet:` address of its releases channel,
  after seeing its key list and its releases;
- choose which publisher the stick follows; a stick follows one
  publisher at a time, since builds of different publishers are
  different files;
- remove the project, or any other publisher.

Switching publishers is an update like any other: it never touches the
user's data (`data/`). A client MUST show which publisher it follows.

Where the files come from does not matter: GitHub, a web entrance, any
mirror (UN-RFC 0043), a scribe (UN-RFC 0020 section 6.4). Only files matching the signed checksums are used.

## 6.1 Updating Servers

A server that nobody looks after is fine as long as it stays up to date.
A program that runs unattended as a service SHOULD therefore update
itself:

1. **On by default.** The publisher's installer turns self-updating on
   unless the operator says no; the operator MAY turn it off at any time.
   For an entrance this is the operator's consent of UN-RFC 0043
   section 7.
2. **Only signed.** At least once a day it looks for a newer stable
   release of its own package from the publisher it follows, valid as
   section 4 says, and installs only files that match the signed
   checksums.
3. **Never older,** as section 11 says for clients.
4. **Not all at once.** It waits a random time of up to 48 hours after a
   release appears, so that a faulty release reaches a few servers
   first and can be followed by a fix before it reaches all.
5. **Back if broken.** If the service does not come up and answer within
   10 minutes after an update, it goes back to the version it ran,
   tells its operator, and does not try that version again.

A server with self-updating turned off SHOULD tell its operator when a
newer release has existed for 30 days, and at once when its version is
below a council's minimum (UN-RFC 0020 section 6.5).

# 7. Building One's Own

A publisher needs nothing from the project: a key list, a releases
channel, and builds that follow the UN-RFCs. Where the reference code
does something the UN-RFCs do not say, that is a fault in the UN-RFCs
and SHOULD be reported as one.

# 8. A Builder Council (Informative)

A later document may let a publisher be a council (UN-RFC 0054): anybody
rebuilds a release reproducibly and posts its checksums, one who has
matched enough releases is admitted, and the key list is the council's
members with its quorum as `threshold`. It needs reproducible builds of
the bundles first.

# 9. Domain Separations

UN-RFC 0003 section 3 is extended with `UNSEENET-RELEASE-KEYS-1`, which
hashes a key list into the next one's `prev`.

# 10. Rationale

- **Why not a council now?** The network does not depend on releases:
  every node and client keeps running without them. What needs
  protecting is the update path, and two of three keys protect it
  without reproducible builds.
- **Why two of three, not two of two?** Two of two turns one lost key
  into a publisher that can never release again. Two of three survives
  one loss and one theft, not both at once.
- **Why chosen publishers?** A network nobody controls should not have
  one place its software must come from. Choosing is also the way out
  when a publisher's keys are lost or misused.

# 11. Security Considerations

- **One stolen key** signs nothing valid and cannot change the key list.
- **A threshold of stolen keys** can do what the publisher can. The fork
  rule shows it if the honest signers post a different list; users can
  switch publishers.
- **Rollback.** A client MUST NOT install a release older than the one
  it runs, whatever its signatures.
- **A malicious publisher** chosen by the user is the user's choice; the
  client shows whom it follows, and adding a publisher asks first.

# 12. What Is Autonomous, and What Is Not Yet (Informative)

Updates no longer hang on one key, and no user is bound to the project.
But while the project's three keys are held by one person, its releases
are as trustworthy as that person - which is why the reserve keys
SHOULD in time be held by other people, and why the builder council of
section 8 is the next step.

# 13. Changes to Other Documents

- UN-RFC 0003 section 3: the label `UNSEENET-RELEASE-KEYS-1` is added.
- UN-RFC 0043 section 7: an entrance's installer asks its operator to
  turn on self-updating of the server software (section 6.1).
- UN-RFC 0043: a release in a releases channel is valid with the
  signatures of section 4; the channel carries the key list of
  section 3.
- UN-RFC 0000 section 6: 0062 is added to the index.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
