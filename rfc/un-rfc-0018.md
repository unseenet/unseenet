```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0018                                              October 2026
Category: Standards Track
Status: Draft
Implemented: unseenet 0.3.0
Updates: 0004, 0010

          Unseenet: Hierarchies and Authority over Group Names
```

# Abstract

Anybody can create a group with any name (UN-RFC 0004), and the
founder's fingerprint in the Group ID keeps groups apart. But a name
alone, such as `unseenet.announce`, means nothing: ten different people
can each own a group by that name. This document lets a hierarchy have a
**maintainer** who says which Group ID is meant by each name in it, as
the hierarchy maintainers and `checkgroups` of Usenet did. It defines a
**root list**, signed by the project, naming the hierarchies and their
maintainers; **hierarchy lists**, signed by each maintainer, naming the
endorsed groups; and **free** hierarchies such as `alt.*` and the
country hierarchies, where anybody may create groups and nobody owns the
names. Nothing in this document stops anybody from creating a group. It
changes what clients show and what nodes may choose to carry.

# 1. Motivation

UN-RFC 0004 section 1 makes hierarchies a pure browsing convention. That
was enough to keep groups apart, but not to tell readers which group is
the real one. A user who finds `unseenet.important@k2x9...` next to
`unseenet.announce@ph5f...` has no way to know that the first was not
made by the project. Display names, fingerprints and warnings help a
careful reader, but the network should be able to say plainly: *in this
hierarchy, this name means this group.*

Usenet solved this socially and then cryptographically: each hierarchy
had a maintainer, who signed `newgroup` and `checkgroups` messages, and
servers acted only on the maintainer's signature. `alt.*` was left open
on purpose. National hierarchies (`dk.*`, `de.*`) had their own
maintainers. This document brings that model to Unseenet without giving
anybody the power to stop groups from existing.

# 2. Terms

- **Hierarchy:** a name and everything under it. `dk` is the hierarchy of
  `dk.snak` and `dk.snak.marsvin`. A **top-level hierarchy** is a single
  name component.
- **Maintainer:** an identity that endorses groups in a hierarchy.
- **Endorsement:** a maintainer's statement that a name in its hierarchy
  means a particular Group ID.
- **Governed hierarchy:** one with a maintainer whose endorsements count.
- **Free hierarchy:** one where nobody endorses names.
- **Reserved hierarchy:** one that has no maintainer yet and is not free.
- **Root list:** the list of top-level hierarchies (section 4).
- **Hierarchy list:** a maintainer's list of endorsed groups (section 5).
- **Root anchor:** the publisher of a root list that a client or node
  trusts (section 6).

# 3. What Does Not Change

- Group IDs, manifests, group types and posting rules (UN-RFC 0004) are
  unchanged. A Group ID still names exactly one group.
- Anybody can still create any group. Nodes still decide what they carry
  (UN-RFC 0004 section 3.3).
- An endorsement does not give a maintainer any power over the group
  itself: it cannot post, moderate, cancel, change or remove it. Only the
  group's owner can.
- Withdrawing an endorsement does not remove the group. It only changes
  how the group is shown, and whether nodes with the policy in section 8
  carry it.

# 4. The Root List

## 4.1 Format

The root list is a JSON object, UTF-8:

| Field         | Type    | Req. | Meaning                                         |
|---------------|---------|------|-------------------------------------------------|
| `v`           | integer | yes  | `1`                                             |
| `updated`     | string  | no   | When the publisher last changed it (free text)   |
| `hierarchies` | array   | yes  | Entries, at most 200                            |

An entry:

| Field         | Type       | Req. | Meaning                                          |
|---------------|------------|------|--------------------------------------------------|
| `name`        | string     | yes  | A single name component (UN-RFC 0004 section 1)  |
| `policy`      | string     | yes  | `governed`, `free` or `reserved`                 |
| `maintainer`  | key string | if governed | The maintainer's identity key             |
| `list`        | Group ID   | if governed | The channel group of its hierarchy list   |
| `title`       | string     | no   | Short title, at most 64 characters               |
| `description` | string     | no   | At most 200 characters, shown to users           |
| `contact`     | Group ID   | no   | An inbox where the maintainer is reached (governed only) |

The fingerprint in `list` MUST be the fingerprint of `maintainer`.

`contact` names an inbox (UN-RFC 0009), typically a team inbox (UN-RFC
0047 section 10), so that the maintainer key can stay offline while
reports and questions are read. A client that reports a post or writes to
a hierarchy's maintainer sends to `contact` when there is one, and to the
maintainer key's personal inbox otherwise. An entry in a hierarchy list's
`sub` (section 5.3) MAY have `contact` the same way.
A name MUST NOT appear twice. A root list that is not JSON, has `v` other
than 1, or has a duplicate name is invalid as a whole; an entry that is
otherwise malformed is ignored, and its name is treated as `reserved`.

The root list MUST fit in one article (UN-RFC 0002 section 2: at most
32 768 octets are guaranteed to be carried).

## 4.2 Names Not in the List

So that the list stays small, three groups of names have a policy
without being listed:

1. **Two-letter names** that are assigned country codes in ISO 3166-1
   alpha-2 (`dk`, `de`, `se`, ...) are **regional** hierarchies: they are
   `free`, and the root list's publisher is their maintainer-in-waiting
   (section 7.3). Other two-letter names are `reserved`.
2. Names listed in section 9 are `reserved` as described there.
3. Any other name that is not in the list is **unclaimed**. An unclaimed
   hierarchy behaves as `free` until somebody claims it (section 7).

An entry in the list overrides rules 1 and 3. Country codes are ISO
3166-1 alpha-2, not language codes (ISO 639-1), as on Usenet: `se` is
Sweden, not Northern Sami. A regional hierarchy is for the people of a
region or speakers of its languages; the protocol does not check either.

## 4.3 Publishing

A root list is published like a node list (UN-RFC 0010 section 3): as the
whole body of an ordinary article in a channel group owned by its
publisher. The owner and the manifest's `posters` may publish. The newest
valid post by `Date` counts. The publisher SHOULD post it again at least
monthly so that it never expires.

# 5. Hierarchy Lists

## 5.1 Format

A maintainer publishes a hierarchy list, a JSON object, UTF-8, in the
channel group named in its root list entry (`list`), the same way:

| Field       | Type    | Req. | Meaning                                        |
|-------------|---------|------|------------------------------------------------|
| `v`         | integer | yes  | `1`                                            |
| `hierarchy` | string  | yes  | The hierarchy it covers, e.g. `unseenet`       |
| `updated`   | string  | no   | Free text                                      |
| `groups`    | array   | yes  | Endorsed groups (may be empty)                 |
| `sub`       | array   | no   | Sub-hierarchies (section 5.3)                  |
| `blocked`   | array   | no   | Blocked identities (section 5.4)               |
| `report_issuers` | array | no | Spam report issuers its readers follow by default, at most 16 keys (UN-RFC 0045 section 7.1) |

An entry in `groups`:

| Field   | Type     | Req. | Meaning                                         |
|---------|----------|------|-------------------------------------------------|
| `group` | Group ID | yes  | The endorsed group                              |
| `note`  | string   | no   | At most 200 characters, for maintainers' records |

An entry is valid only if the name part of `group` is the hierarchy or
lies under it (`unseenet` or `unseenet.*`), and is not inside a
sub-hierarchy listed in `sub`. A name MUST NOT be endorsed twice in the
same list; if it is, neither entry counts.

A list whose `hierarchy` differs from what the reader expected is
invalid. A list MUST fit in one article; a maintainer with more groups
than fit SHOULD delegate sub-hierarchies.

## 5.2 Meaning

For every valid entry, the hierarchy's maintainer says: *the name
`unseenet.announce` means the group `unseenet.announce@ph5fc5hop5232qsz`.*
Every other group with the same name, and every group in the hierarchy
that is not listed, is **unendorsed**.

The endorsement is of the Group ID. When a group changes owner (UN-RFC
0015) its Group ID stays the same, and so does its endorsement. A
maintainer that does not want to endorse the new owner removes the entry.

## 5.3 Sub-hierarchies

An entry in `sub` has the fields of a root list entry (section 4.1), but
`name` is a full name under the hierarchy (`dk.foreninger`), and the
policy is one of:

- `governed`: delegated to another maintainer and list, which publishes a
  hierarchy list for that name in turn;
- `free`: nobody endorses names under it, even though the parent is
  governed.

A sub-hierarchy covers its name and everything under it. A reader
follows delegations at most 4 levels deep below the root list and treats
anything deeper as unendorsed.

## 5.4 Blocked Identities

A maintainer can block identities across its hierarchy, for example
someone who posts threats in group after group. An entry in `blocked`:

| Field    | Type       | Req. | Meaning                                         |
|----------|------------|------|-------------------------------------------------|
| `key`    | key string | yes  | The blocked identity key                        |
| `reason` | string     | yes  | A public reason, 1 to 200 characters            |
| `since`  | string     | no   | When the block was made (RFC 3339)              |
| `until`  | string     | no   | When it ends (RFC 3339); without it, it lasts   |

An entry without a valid `key` or without a `reason` is ignored, as is
one whose `until` has passed. A key MUST NOT be listed twice.

A block applies to every group whose name is the hierarchy or lies under
it, **including delegated sub-hierarchies**: the maintainer of `dk` blocks
in all of `dk.*`, and the maintainer of a sub-hierarchy `dk.snak` it
delegated (section 5.3) blocks in `dk.snak` and `dk.snak.*` only. For a
group, the blocks that count are those of every maintainer on the way
from the root list down to the hierarchy that decides its name (section
8.1); a maintainer further down cannot lift a block made higher up. In a
`free` sub-hierarchy nobody below blocks, but the blocks of the
maintainers above still apply.

A block is about an identity, not a group: it does not give the
maintainer any power over groups (section 3). It cannot remove, change or
cancel anything; it only tells nodes and readers, in public and with a
reason, that the maintainer does not want this identity in its part of
the network. What happens then is each node's and each reader's choice
(section 8).

# 6. Trust Anchors

## 6.1 Pinning

A client or node has zero or more **root anchors**: a publisher key and
the Group ID of its root list, exactly as for node lists (UN-RFC 0010
section 4). It reads root lists and hierarchy lists the way UN-RFC 0010
section 4 reads node lists: through a node it already uses, checking the
manifest's owner, the signatures and authors, keeping the newest valid
list, and keeping the last good one when it cannot read a new one.

If a client has several root anchors, it uses them in the order the user
chose; the first anchor that lists a name decides it.

## 6.2 The Project's Root

The reference client and node pin the Unseenet project as their root
anchor, using the project key of UN-RFC 0010 section 6:

- owner key `ed25519:det5dxevwbk36eds2indrzlazyri3fq3bgdzw6kx4ems3o267sya`
- root list group `unseenet.hierarchies@ph5fc5hop5232qsz`

Its root list is kept in the project's repository and changed by pull
request; an automated poster publishes it when it changes and every
month. Users and operators MAY pin other roots, or none. A client with no
root anchor treats every hierarchy as unclaimed.

# 7. Claiming a Hierarchy (Informative)

This section describes the project's own process. Other roots may work
differently.

## 7.1 Requests

A top-level hierarchy is requested in one of two ways:

- an issue in the project's repository, using the "Request a
  hierarchy" form;
- a message to the project's inbox (`inbox@ph5fc5hop5232qsz`, UN-RFC
  0009), for those who do not want a GitHub account linked to them.

A request gives:

1. the name;
2. the maintainer key and the Group ID of the channel group for its
   hierarchy list, already created;
3. a title and description, and a charter: what the hierarchy is for and
   how the maintainer will decide which groups to endorse;
4. a signature by the maintainer key over a challenge given by the
   project, purpose `UNSEENET-HIERARCHY-CLAIM-1`, showing that the
   request comes from the key's holder.

## 7.2 Criteria

The project grants a hierarchy when:

- the name has at least three characters (two-letter names are regional,
  section 4.2) and is not confusingly like an existing hierarchy;
- the charter describes a real purpose, not the reservation of a name
  for later;
- for an **unclaimed** name already in use, the request says how the
  existing groups will be handled. The maintainer SHOULD endorse the
  groups that are already in use under that name, unless they are
  abandoned or abusive. Taking over a busy free namespace to push its
  users aside is a reason to refuse.

The decision and the reasons are public, in the issue or in
`unseenet.admin` (section 9). A hierarchy whose list has not been
published for 180 days, or whose maintainer asks to give it up, MAY be
returned to `reserved` or `free`.

## 7.3 Regional Hierarchies

Regional hierarchies start free: anybody can create `dk.snak.marsvin`.
When a community in a region wants governance, it can ask for its
regional hierarchy to be delegated to a maintainer it has chosen, by the
process in 7.1. The project then lists it as `governed`, and the
maintainer SHOULD endorse the groups already in use. A maintainer MAY
keep parts of a regional hierarchy free with `sub` entries (section 5.3).

# 8. Effects

## 8.1 Clients

For a group with name `N`, a client finds the policy of the hierarchy
that decides `N` (the deepest one known to it) and then:

- **Endorsed** group: the client MAY show `N` without the fingerprint,
  and SHOULD mark it as endorsed, naming the maintainer on request.
- **Unendorsed** group in a governed or reserved hierarchy: the client
  MUST show the fingerprint (`N@abcd`), and SHOULD warn when a user
  subscribes, e.g. "This is not the `unseenet.important` endorsed by the
  maintainer of `unseenet`."
- Group in a **free** or **unclaimed** hierarchy: the client MAY show `N`
  without the fingerprint if it knows of only one group named `N`;
  otherwise it MUST show the fingerprint for all of them. Nobody owns the
  name, and the client MUST NOT pick a winner.

UN-RFC 0004 section 1 (warning on two subscribed groups with the same
name) still applies.

A client SHOULD by default not show articles whose `Author-Key` is
blocked for the group (section 5.4). It SHOULD say that something is
hidden, by whom and why (for example "2 posts hidden: blocked in `dk.*`:
threats against members"), and MUST let the reader choose to see them
anyway: the reader has the last word. A client reads the hierarchy lists
of delegated sub-hierarchies too, so that their blocks are known.

A client SHOULD show users the hierarchy's title and description when
they browse it, and SHOULD warn when a new name differs only slightly
(e.g. by one character) from an endorsed name the user follows.

## 8.2 Nodes

UN-RFC 0004 section 3.3 is extended: a node SHOULD also support the
policy **"in governed and reserved hierarchies, accept only endorsed
groups"**, combined with any policy for free and unclaimed ones. This is
the operator's choice; it is not required.

A node that drops a group because it is no longer endorsed does so as a
local drop (UN-RFC 0013), not a removal.

A node SHOULD also support the policy **"honour the maintainers'
blocks"**: it then rejects new ordinary articles whose `Author-Key` is
blocked for the group (section 5.4), and MAY delete such articles it
already holds, as a local action that is not passed on to peers. This is
the operator's choice and is off unless the operator turns it on. A node
says whether it honours blocks in its node information (UN-RFC 0011),
field `honours_blocks` in `policy`. Control articles are not affected,
so a blocked identity can still withdraw its own posts.

Nodes MAY require more postage (UN-RFC 0006) for the first manifest
(serial 1) of a group in a free or unclaimed hierarchy than for other
articles, to make mass creation of groups expensive. They MAY drop a
group in a free hierarchy from their own store when it has had no
articles other than its manifests for longer than its retention period.

## 8.3 Free Hierarchies

Creating a group in a free hierarchy gives its owner the group, the same
as anywhere else. It gives no rights to the name or to anything under
it: the owner of `dk.snak.marsvin` has no say over
`dk.snak.marsvin.unger`.

# 9. The Initial Root List

The project's root list initially says:

| Name       | Policy   | Meaning                                                 |
|------------|----------|---------------------------------------------------------|
| `unseenet` | governed | The project's own groups. Maintainer: the project key.  |
| `alt`      | free     | Anything goes, by tradition.                            |
| `test`     | free     | For trying things out. Nodes SHOULD keep it briefly (RECOMMENDED: 7 days). |
| `demo`     | free     | Demonstrations of what Unseenet can do, such as the project's demo village in `demo.unseenet.*`. |
| `comp`, `humanities`, `misc`, `news`, `rec`, `sci`, `soc`, `talk` | reserved | The Usenet "Big 8", held for communities that want to revive them. |
| `control`, `junk`, `local`, `inbox`, `all`, `example`, `invalid` | reserved | Never granted. They have special meanings on Usenet or in Unseenet, or are used in documentation. |

Country codes are regional by section 4.2 and are not listed until one is
delegated.

`local` is reserved but has no special effect: local groups are made
with the `local` field of the manifest (UN-RFC 0009 section 4), whatever
their name. `inbox` is reserved because personal inboxes are named
`inbox@<fingerprint>` (UN-RFC 0009).

The project keeps `unseenet.admin@ph5fc5hop5232qsz` as an open group for
discussing hierarchy requests and decisions.

# 10. Signature Purposes

UN-RFC 0003 section 3 is extended with:

| Purpose label                  | Signs                         | Defined in |
|--------------------------------|-------------------------------|------------|
| `UNSEENET-HIERARCHY-CLAIM-1`   | a challenge (section 7.1)     | 0018       |

Root lists and hierarchy lists need no purpose of their own: they are the
bodies of ordinary signed articles in channel groups.

# 11. Rationale

- **Why not let nodes reject unendorsed groups by protocol?** It would
  give the root list's publisher the power to keep groups off the whole
  network, and it would split the network whenever two nodes trust
  different roots. As written, the worst a dishonest root can do is
  label groups; operators decide what they carry.
- **Why not first-come, first-served in free hierarchies?** Dates are set
  by the poster and cannot be trusted, and nodes see articles in
  different orders. Ordering by proof-of-work was also considered, but
  anybody willing to spend more work later could then take a name from
  its first owner. In a free hierarchy the honest answer is that nobody
  owns the name, and the fingerprint already keeps groups apart.
- **Why a central root at all?** A name only means something if somebody
  says what it means. The root is pinned, not built in: every user and
  operator can replace it, and the lists travel in the network like any
  article.
- **Why lists rather than signed `newgroup` messages?** A list says
  everything at once, so a reader that missed a message is still right,
  and it is the same mechanism as node lists.

# 12. Security Considerations

- **Stolen root or maintainer key.** A thief can endorse its own groups
  and withdraw endorsements until the owner of the list group removes
  the key from the manifest, or the root replaces the maintainer. It
  cannot change, cancel or remove any group. Publishers SHOULD keep owner
  keys offline and give automated posters their own keys (UN-RFC 0010
  section 7).
- **Withheld lists.** A node can withhold the newest list; the reader then
  keeps an older one, which may still endorse a group the maintainer has
  dropped.
- **Censorship.** The root can refuse or withdraw a hierarchy. This
  affects labels and the choices of operators who follow it; the groups
  remain reachable by Group ID, and users can pin another root.
- **Lookalike names.** Group names are restricted to `a-z`, `0-9`, `+`,
  `_` and `-` (UN-RFC 0004), so Unicode lookalikes are impossible. Names
  like `unseenet-announce` or `unseenett` are possible; section 8.1 asks
  clients to warn about near matches, and unendorsed groups always show
  their fingerprint.
- **Blocks** (section 5.4) are public and carry reasons, so they can be
  seen and challenged. Keys are free, so a block stops an identity, not a
  determined person; postage (UN-RFC 0006) makes coming back with new
  keys slower. A block is not law enforcement: threats and crimes belong
  with the police. A stolen maintainer key can block anyone in the
  hierarchy until it is replaced; since readers can show blocked posts
  and nodes opt in, the damage is limited and visible.
- **Privacy.** Lists are read over Tor through the user's node. Reading
  them reveals nothing beyond what reading any group does.

# 13. Changes to Other Documents

- UN-RFC 0004 section 1: "There is no authority over hierarchies" is
  replaced by: hierarchies MAY have maintainers as defined in UN-RFC
  0018; without one, they remain a browsing convention.
- UN-RFC 0004 section 3.3: the node policy in section 8.2 is added.
- UN-RFC 0010 section 6: the project anchor also publishes the root list
  in `unseenet.hierarchies@ph5fc5hop5232qsz`.
- UN-RFC 0011 section 4: the `policy` object of node information MAY
  have `honours_blocks` (boolean), section 8.2.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
