```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0029                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0009, 0017, 0019, 0022

            Unseenet: Key-bound Groups, Lifetime and Renewal
```

# Abstract

Some groups follow from a key: an identity's personal inbox, its
profile and picture, and an issuer's list of revoked sub-names. There
is one of each per key, and their manifests are group state, which
nodes otherwise keep for ever. This document gives every such
**key-bound group** a lifetime of at most two years. The owner's client
renews it without asking whenever it runs, so nobody who uses their key
loses anything, while the groups of keys nobody uses any more disappear
from the network by themselves, with nothing for anybody to clean up.

# 1. Motivation

UN-RFC 0017 section 2 keeps group state for ever, so that a group
survives while its owner is away. For an ordinary group that is the
right choice: other people use it. A key-bound group is different. It
exists because a key exists, it is used by that key's holder, and there
is one per identity. Keys are cheap and often thrown away - UN-RFC 0003
section 2 recommends a separate identity per closed group - so after some decades
almost every key-bound group in the network would belong to a key that
nobody holds any more.

UN-RFC 0019 met the same problem for names with certificates that
expire and are renewed. This document applies that principle to
key-bound groups, once, so that every document that defines one
inherits it. Ordinary groups are not covered (section 10).

# 2. Key-bound Groups

A **key-bound group** is a group whose name is reserved by an
Unseenet document for one purpose, and whose Group ID therefore follows
from the key of its owner alone. They are:

| Group                 | Purpose                          | Defined in              |
|-----------------------|----------------------------------|-------------------------|
| `inbox@<fp>`          | Personal inbox                   | UN-RFC 0009 section 2.2 |
| `names@<fp>`          | Revocation list of an issuer of sub-names | UN-RFC 0019 section 6.6 |
| `profile@<fp>`        | Public profile                   | UN-RFC 0022 section 5.1 |
| `avatar@<fp>`         | Public picture                   | UN-RFC 0022 section 8.2 |
| `ripe@<fp>`           | Key ripening chain               | UN-RFC 0025 section 3.3 |
| `feed@<fp>`           | Personal feed (personal group)   | UN-RFC 0034 section 5   |
| `site@<fp>`           | Personal site (personal group)   | UN-RFC 0035 section 7   |
| `state@<fp>`          | The owner's state, encrypted     | UN-RFC 0044 section 3   |

where `<fp>` is the fingerprint of the owner's key (UN-RFC 0003
section 2). A later document that reserves a group name for a key adds
it to this table, and the group is key-bound from then on.

A group with another name is an ordinary group, even if it is owned by
the same key.

## 2.1 Personal Groups

Most key-bound groups exist because the identity does: a client makes
the inbox, the ripening chain and, when asked, the profile and picture,
and nobody reads them as groups. A **personal group** is a key-bound
group that an identity publishes content in for others to read, and
that exists only because its owner chose to start it: today the
personal feed (UN-RFC 0034) and the personal site (UN-RFC 0035). They
share these rules; their own documents only add what is particular to
them (the view, comments, pages).

- **Manifest.** `name` is the reserved name; `type` is `channel`; the
  owner MAY list `posters`, for example a key of their own on another
  device, and SHOULD NOT list other people, since readers take a
  personal group to be one person's; `view` is the one the group's
  document gives; `expires` as for every key-bound group (section 3).
  A node MUST reject a manifest for a personal group whose `type` is not
  `channel` or whose `view` is not that one.
- **Starting.** A personal group is public and ties everything in it to
  the identity. A client MUST NOT create one without the user asking
  for it (it MAY offer to when an identity is created), and MUST tell the
  user, as for a public profile (UN-RFC 0022 section 5.3), that what is
  published can be kept by others and cannot be recalled, also after it
  is changed or removed.
- **Ending.** The owner ends one by removing the group (UN-RFC 0013) or
  by letting it expire. Unlike the inbox, it is not renewed once removed.
- **Lifetime.** It is renewed with the identity's other key-bound groups
  (section 4) and expires with them (section 5); its articles expire
  with its `retention_days`, except what is kept (UN-RFC 0017 section
  2.1).
- **Finding.** Wherever a client shows an identity (its profile, an
  author's name, a mention), it SHOULD offer the identity's personal
  groups that are current, and nothing for those that are not. It
  learns this as it reads a profile (UN-RFC 0022 section 5.2): by asking
  a node it uses for the group's current manifest. A node that does not
  carry it means there is none to show, and is not an error.
- **Following.** To follow a personal group is to subscribe to it, as to
  any group (UN-RFC 0034 section 6): the list is kept in the user's
  vault, never published, and followed groups are read like the others
  so that following does not stand out. A user can also follow a
  person, which follows all of that identity's personal groups and the
  feeds its profile lists (UN-RFC 0034 section 6.1).

A personal group for a closed circle of people is not a key-bound
group: it is an ordinary closed group, for example with `"view": "feed"`
(UN-RFC 0034 section 3.2). A private profile shared there (UN-RFC 0022
section 6) is how an identity tells only that circle who it is.

# 3. Lifetime

The manifest of a key-bound group (UN-RFC 0004 section 3) MUST have
the field

| Field     | Type | Meaning                                                       |
|-----------|------|---------------------------------------------------------------|
| `expires` | date | RFC 3339 UTC, at most 730 days after the manifest's `Date`    |

where `Date` is the header of the manifest article (UN-RFC 0002 section
2.5). A node MUST reject (`441 syntax`) the manifest of a key-bound
group without `expires` or with `expires` later than that, and a client
MUST ignore one.

# 4. Renewal

The owner's client renews a key-bound group by posting the same
manifest with a higher `serial`, a new `Date` and a new `expires`.

- It SHOULD renew, without asking the user, once fewer than 545 days
  remain - that is, once the manifest is about six months old.
- It SHOULD choose a random moment within the next 30 days that it is
  running, and MUST renew **all** the key-bound groups of one key at
  that moment, not each on its own schedule (section 11).
- It SHOULD tell the user, in its list of identities, when an
  identity's key-bound groups will expire, so that a user who keeps an
  identity on a stick that is rarely used can see it.

An identity whose client runs at least once a year and a half therefore
never loses anything.

## 4.1 A New Identity's First Lifetime

Many people open a client a few times to look around before they settle
on one identity, and each time the client makes an inbox (section 6).
So that these do not stay on every full node for two years, a client
SHOULD give a new identity's key-bound groups a short first lifetime:

- When it first posts them, `expires` is 60 days after `Date`.
- It counts, where it keeps the identity's keys, the different days it
  was opened with that identity. The identity is **in use** from the
  third such day, or at its first real use: a post, a chat, a private
  post, a contact added, a group created, a profile or picture
  published. Following groups is not use.
- Once the identity is in use, the client renews all its key-bound
  groups at once, with the full lifetime, and from then on as above.
- Until then it renews them when fewer than 30 days remain, again for
  60 days - not by the 545-day rule, which would give a first lifetime
  the full one at the next start.

An identity whose key-bound groups already have a longer lifetime is in
use. A visitor who never comes back is removed from the nodes about
90 days after the last visit (60 days, and section 5). Nodes see nothing
of this: every `expires` is within section 3.

# 5. Expiry

When the current time passes the `expires` of a key-bound group's
current manifest, the group has **expired**.

Clients:

- MUST treat an expired group as absent: no profile, no picture, no
  revocation list, no inbox (section 6, 7).

Nodes:

- MUST NOT offer the expired manifest, or any article of the group, to
  peers or readers;
- MUST reject (`441 group`) new ordinary articles in the group, as for a
  group they do not carry;
- MUST remove the group, with everything in it, within 30 days of
  expiry, unless a valid manifest with a higher `serial` and a later
  `expires` arrives first, which makes the group current again.

This is an exception to UN-RFC 0017 section 2: the state of a
key-bound group ends when its manifest expires. Archive nodes (UN-RFC
0012) MAY keep what they hold of a key-bound group longer, but MUST NOT
serve it as current.

# 6. Inboxes

A message to an expired inbox cannot be delivered.

- Before sending, the sender's client SHOULD read the current manifest
  of the receiver's inbox. If it is absent or expired, the client tells
  the user that the receiver has no inbox it can reach, and does not
  send. It MUST NOT say whether the inbox expired or never existed; it
  cannot know, and it should not guess.
- A node answers a post to an expired inbox with `441 group`, the same
  answer as for an inbox it does not carry.

Messages still waiting in an inbox when it is removed are lost with
it. That is acceptable: their receiver has not run a client for two
years, and they would otherwise expire with the inbox's retention.

# 7. Sub-name Revocation Lists

A missing revocation list means that no revocations are known, which
would make revoked sub-names look valid. This cannot happen through
expiry: a sub-name counts only while the issuer holds its parent name (UN-RFC
0019 section 5.4), and a `registered` name lasts at most one year, so an
issuer who does not renew within two years has no valid sub-names left
to revoke. A client MUST NOT accept a sub-name whose issuer's `names`
group it has seen expire, even if the sub-name's own certificate has
not.

# 8. Coming Back

Only the owner's key can sign a key-bound group's manifest, so nobody
else can take the group over, before or after it expires. An owner who
returns after expiry simply renews: the client posts a manifest with a
`serial` higher than the last one it posted, and nodes that removed the
group accept it as a new group. A client MUST therefore remember the
highest `serial` it has used for each key-bound group, in the vault.

# 9. Changes to Other Documents

- **UN-RFC 0004** section 3.1: the manifest field `expires` (date,
  required in key-bound groups).
- **UN-RFC 0009** section 2.2: the personal inbox is a key-bound group;
  a client that creates one renews it (section 4).
- **UN-RFC 0017** section 2: the state of a key-bound group ends when
  its manifest expires (section 5).
- **UN-RFC 0019** section 6.6: the `names` group of an issuer of
  sub-names is a key-bound group, with section 7.
- **UN-RFC 0022** section 5.4: replaced by a reference to this
  document.
- **UN-RFC 0034** section 5 and **UN-RFC 0035** section 7: personal
  feeds and sites follow the common rules of section 2.1.
- **UN-RFC 0000** section 6: 0029 is added to the index.

# 10. Rationale

- **Why two years?** Long enough that nobody loses an inbox or a
  profile by being away for a year, short enough that dead keys
  disappear in reasonable time. Renewal is automatic, so the length
  costs users nothing.
- **Why only key-bound groups?** Ordinary groups are used by others
  than their owner, carry names people care about inside hierarchies,
  and may be worth keeping for their content. They need a different
  rule, and that question is open (issue #158).
- **Why one document?** Inboxes, profiles, pictures and revocation
  lists had the same problem. Writing the rule once means the next
  key-bound group cannot forget it.
- **Why may a client not say "expired"?** It cannot tell an expired
  inbox from one its node never carried, and claiming to know would
  invite guesses about when somebody was last active.

# 11. Security and Privacy Considerations

- **Renewal shows activity.** Each renewal tells every node that the
  key's holder ran a client at about that time. A random moment within
  30 days, the rounded `Date`, and renewing all of a key's groups
  together keep this to one event per half year, saying no more than
  "was active some time that month". Any post says more.
- **Linking identities.** A user with several identities on one stick
  would renew them all when the client starts, which links them by
  timing. A client MUST choose the renewal moment for each identity
  independently.
- **Replay.** An old manifest can be posted again by anybody who kept
  it, but only until its own `expires`, and it only restores something
  the owner once published. The owner's next renewal, with a higher
  `serial`, replaces it everywhere.
- **Lost inboxes.** An attacker cannot make an inbox expire: only the
  owner's key renews it, and nodes count from the manifest the owner
  signed.
- **Lost keys.** A key that is lost cannot renew. Its inbox and profile
  disappear after at most two years, which is the intended effect.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
