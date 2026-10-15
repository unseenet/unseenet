```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0013                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0004, 0005

                   Unseenet: Removing Groups
```

# Abstract

This document lets a group's owner remove the group from the network
with a signed `rmgroup` control article, and lets a node operator drop
a group from their own node. Both leave a **tombstone**, so a removed
group cannot come back through replication.

# 1. Motivation

UN-RFC 0004 lets anybody create groups but offers no way to remove one.
Owners make mistakes (a typo in a name cannot be fixed, because the name
is part of the Group ID), groups fall out of use, and operators need to
be able to stop carrying something. Usenet had `rmgroup`, but anyone
could forge it. Here only the owner can.

# 2. Removal by the Owner

## 2.1 The Control Article

```
Control: rmgroup
Newsgroups: <group-id>
```

The article is signed by the owner (its `Author-Key` MUST be the owner
of the current manifest). The body MAY contain a short reason in plain
text. Like a manifest, it is exempt from the group's own `min_pow`, but
not from the node's.

## 2.2 Node Behaviour

A node that accepts a valid `rmgroup`:

1. records a **tombstone** for the Group ID (section 4), keeping the
   `rmgroup` article itself;
2. deletes the manifest and all articles of the group;
3. forwards the `rmgroup` article to its peers like any article, unless
   the group was local (UN-RFC 0009 section 4).

A node that receives an `rmgroup` for a group it does not carry SHOULD
still record the tombstone and forward the article, so that the group
cannot later arrive through another path. It cannot check the owner
without the manifest; it MUST then at least check that the fingerprint
of `Author-Key` equals the fingerprint in the Group ID, which proves the
article comes from the owner.

## 2.3 Finality

Removal is final. A Group ID with a tombstone can never be used again:
a new manifest for it is rejected, even from the owner. An owner who
wants the group back creates a group with a new name.

# 3. Removal by the Operator

An operator MAY drop any group from their own node. The node records a
tombstone with the reason `operator` and deletes the group's articles
as in section 2.2, but sends nothing to its peers: the decision is about
this node only. Such a tombstone MAY later be lifted by the operator.

# 4. Tombstones

A tombstone consists of the Group ID, the time, the reason (`owner` or
`operator`) and, for `owner`, the `rmgroup` article. While a tombstone
exists, a node:

- rejects the group's manifest and articles, with reason `group`;
- answers `GROUP` and `LISTGROUP` for it with
  `411 no such group (removed by its owner)` or
  `411 no such group (dropped by this node)`;
- does not list it in `LIST ACTIVE` or `LIST NEWSGROUPS`.

Owner tombstones SHOULD be kept indefinitely; they are small.

# 5. Clients

A client that gets `411 ... removed by its owner` for a subscribed group
SHOULD tell the user and offer to unsubscribe and delete its local copy.

# 6. Security Considerations

- Only the owner's key can remove a group from the network. Losing the
  owner key means losing the ability to remove the group.
- A tombstone without a manifest (section 2.2, last paragraph) is
  accepted on the strength of the fingerprint alone. An attacker would
  need a key with the same 80-bit fingerprint, which is infeasible.
- Removal deletes copies on well-behaved nodes. It cannot remove what
  readers, archives or misbehaving nodes have already stored.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
