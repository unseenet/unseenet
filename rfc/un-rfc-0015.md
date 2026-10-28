```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0015                                              October 2026
Category: Standards Track
Status: Draft
Implemented: unseenet 0.4.0
Updates: 0003, 0004, 0013

              Unseenet: Transferring Group Ownership
```

# Abstract

A group's owner can hand the group over to another identity. The owner
signs an **offer**; the new owner accepts it by signing it too and
publishing a manifest of their own. The manifest carries the whole
**ownership chain** from the founder, so any node can check who owns a
group from the current manifest alone. The Group ID does not change:
links, subscriptions and history keep working, and the fingerprint in
the ID names the group's founder, not its current owner.

# 1. Motivation

A Group ID contains the fingerprint of its owner (UN-RFC 0004 section
1), and UN-RFC 0004 section 4 forbids changing the owner. So a group is
bound to its creator forever. People lose interest, change identities or
want to pass a group on to someone who cares for it, and the only way
today is to create a new group and ask everybody to move, losing the
history. Usenet groups changed moderators as a matter of course.

# 2. Terms

- **Founder:** the key whose fingerprint is in the Group ID.
- **Owner:** the key that currently has the owner's powers: publishing
  manifests, key updates in closed groups (UN-RFC 0004 section 6),
  cancels (UN-RFC 0004 section 7) and removal (UN-RFC 0013).
- **Offer:** a statement signed by the owner that a named key may become
  the next owner.
- **Link:** an offer together with its acceptance, signed by the new
  owner.
- **Chain:** the list of links from the founder to the owner. For a group
  that was never transferred the chain is empty and the founder is the
  owner.

# 3. Manifest Fields

UN-RFC 0004 section 3.1 is extended with:

| Field   | Type            | Meaning                                       |
|---------|-----------------|-----------------------------------------------|
| `chain` | array of links  | The ownership chain, oldest first (section 4) |
| `offer` | offer object    | An open offer by the owner (section 5)        |

UN-RFC 0004 section 4, item 3 ("`owner` equals `Author-Key`") still
holds. Item 2 is changed: the fingerprint in the Group ID MUST equal the
fingerprint of the **founder**, which is `owner` if `chain` is empty and
otherwise the `from` of the first link.

# 4. Links

An **offer** is a JSON object:

| Field     | Type       | Meaning                                              |
|-----------|------------|------------------------------------------------------|
| `group`   | string     | The Group ID                                         |
| `from`    | key string | The owner making the offer                           |
| `to`      | key string | The proposed new owner                               |
| `serial`  | integer    | The serial of the manifest that contains the offer   |
| `expires` | date       | RFC 3339 UTC; at most 30 days after it was made      |
| `sig`     | signature  | By `from`, purpose `UNSEENET-TRANSFER-OFFER-1`       |

The signature covers the canonical JSON (UN-RFC 0004 section 3) of the
object without `sig`.

A **link** is an offer with two more fields:

| Field         | Type      | Meaning                                         |
|---------------|-----------|-------------------------------------------------|
| `accepted`    | date      | RFC 3339 UTC, when `to` accepted                |
| `accept_sig`  | signature | By `to`, purpose `UNSEENET-TRANSFER-ACCEPT-1`   |

`accept_sig` covers the canonical JSON of the whole link without
`accept_sig` (so it includes the offer's `sig`).

A chain `[L1, ..., Ln]` is **valid** for a Group ID if:

1. the fingerprint of `L1.from` is the fingerprint in the Group ID;
2. for each `i > 1`, `Li.from` equals `L(i-1).to`;
3. every `Li.group` is the Group ID;
4. every `sig` and `accept_sig` is valid;
5. for every link, `accepted` is not later than `expires`;
6. no key appears as `to` more than once in the chain;
7. `n` is at most 64.

The owner of a manifest with a non-empty valid chain is `Ln.to`, and
`owner` and `Author-Key` MUST be that key.

Links are self-contained. A node that has never seen the earlier
manifests can still check the chain, and the expiry is checked against
the acceptance date recorded in the link, not against the time the node
happens to see it.

# 5. Offering and Accepting

**Offering.** The owner publishes a new manifest (serial `N`) with an
`offer` whose `serial` is `N` and whose `from` is the owner. At most one
offer can be open; a newer manifest from the owner may replace it with
another offer or drop it.

An offer cannot be withdrawn: once signed and published, the named key
can accept it until it expires, even if the owner publishes newer
manifests without it. Owners SHOULD use short expiry times. Clients MUST
make this clear before signing an offer.

The offer is public, so the new owner learns about it from the manifest.
Clients SHOULD show "X offers you ownership of G" to the identity in
`to`, and MAY also send a private message (UN-RFC 0009).

**Accepting.** The new owner publishes a manifest:

- `serial` greater than the highest serial it knows for the group;
- `owner` and `Author-Key` the new owner's key;
- `chain` the previous chain followed by the offer turned into a link;
- no `offer`;
- the other fields as the new owner wishes, except that `name` and
  `type` MUST NOT change (UN-RFC 0004 section 4).

An identity cannot be offered a group it already owns, and an inbox
group (UN-RFC 0009) MUST NOT be offered or transferred: it belongs to the
identity it was made for.

# 6. Which Manifest Is Current

UN-RFC 0004 section 3.2 is replaced. Of all valid manifests for a Group
ID, the current one is the one with

1. the **longest** chain; then
2. the highest `serial`; then
3. the lexicographically lowest Message-ID.

Because a longer chain always wins, a former owner cannot take a group
back by publishing manifests of its own, whatever serial it uses: its
own manifests have a shorter chain. (It can sign a *conflicting offer*;
see section 10.)

A manifest whose author is not the owner its chain implies is invalid
and MUST be rejected, like any other invalid manifest.

# 7. Effects of a Transfer

From the moment a manifest with a longer chain is current:

- only the new owner can publish manifests, key updates, cancels and
  removals for the group;
- the former owner has no special rights. The new owner MAY list them as
  a moderator or poster, or invite them to a closed group, like anyone
  else;
- approvals by a former owner (UN-RFC 0004 section 5) of articles not yet
  accepted by a node are no longer valid unless the former owner is a
  moderator;
- articles already accepted are not affected.

**Closed groups.** The group secret is not in the manifest. Before
offering, the owner SHOULD give the new owner the current secret with a
key grant (UN-RFC 0004 section 6.3), so that the new owner can read the
group and manage it. After accepting, the new owner SHOULD start a new
epoch (UN-RFC 0004 section 6.2) for the members it wants, so that a
former owner who is not a member can no longer read new articles.
Private information in `sealed` (UN-RFC 0004 section 6.6) is re-sealed by
the new owner.

**Removal.** UN-RFC 0013 is updated: `rmgroup` MUST be signed by the
current owner, not by the founder.

# 8. Signature Purposes

UN-RFC 0003 section 3 is extended with:

| Purpose label                  | Signs                         | Defined in |
|--------------------------------|-------------------------------|------------|
| `UNSEENET-TRANSFER-OFFER-1`    | an offer (section 4)          | 0015       |
| `UNSEENET-TRANSFER-ACCEPT-1`   | a link (section 4)            | 0015       |

# 9. Clients

A client:

- MUST show a group's current owner, and SHOULD show "founded by" when
  it differs, so that readers are not misled by the fingerprint in the
  Group ID;
- MUST warn before signing an offer that it cannot be taken back and
  that the owner's rights pass to the other key when it is accepted;
- SHOULD let the identity named in an open offer accept or ignore it;
- SHOULD tell the reader when a group they follow changes owner.

# 10. Security Considerations

- **Double transfer.** An owner can sign offers to two different keys.
  Worse, because offers carry their own serial and dates, a former owner
  can sign a second, *backdated* offer at any later time, and the
  protocol cannot tell it from an honest one. If it is accepted, there
  are two valid chains of the same length; section 6 picks one the same
  way on every node, so the network stays consistent, but the former
  owner chooses the outcome. Nothing in a network without central
  coordination can prevent this. It is, however, visible and signed: two
  valid links with the same `from` at the same position are proof that
  that key gave the group away twice. A node that sees this SHOULD log it,
  and a client SHOULD show the group as **disputed** and name the key.
  The same applies to every earlier owner in a chain. Take over a group
  only from someone you trust; a transfer protects you against everybody
  except the owners before you.
- **Stolen keys.** A thief of an owner's key can offer the group to
  themself. This is no worse than today, where the thief can already
  replace the manifest, cancel posts and remove the group. Expiry limits
  how long a stolen offer is useful only if the offer was made before the
  theft.
- **Unwanted groups.** Nobody becomes an owner without signing an
  acceptance, so groups cannot be dumped on people.
- **Founder fingerprint.** After a transfer the fingerprint in the Group
  ID no longer identifies the owner. Clients that show owners by the ID
  alone would mislead; section 9 requires showing the current owner.
- **Size.** Each link is a few hundred octets; 64 links fit well within
  the article size limit (UN-RFC 0002).

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
