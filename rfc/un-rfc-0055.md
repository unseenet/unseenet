```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0055                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0004, 0008, 0011, 0013, 0031, 0046

                    Unseenet: A Group's Own Emoji
```

# Abstract

UN-RFC 0031 gives every client the same Unicode emoji and the same
`:shortcodes:`. Communities also want their own: a `:marsvin:` in
`dk.snak.marsvin`, the project's logo in `unseenet`. This document lets
a group's owner give the group a small set of emoji - tiny still
pictures with a name - kept in a data group of their own that follows
from the group, as a key's picture follows from the key (UN-RFC 0022
section 8.2). Graphical clients show the picture where `:name:` is
written in the group; text clients and newsreaders show `:name:` as
written, which is enough. A node can refuse the emoji without refusing
the group.

# 1. Motivation

Own emoji are part of how a community feels at home, and every chat
system people know has them. What makes them hard here:

- They are images, with every problem of UN-RFC 0027: hostile files,
  metadata, abuse, and nodes carrying pictures they did not choose to.
- They must belong to the group and be signed by its owner, so that
  nobody can swap `:marsvin:` for something else.
- A manifest is a control article and cannot reference blobs (UN-RFC
  0027 section 7.1), and blobs expire with their articles, so a set of
  emoji cannot simply be blobs.
- Text clients and newsreaders must still read well.
- Names must not clash with the standard shortcodes (UN-RFC 0031
  section 5.2).

# 2. Terms

- **Group emoji**: a picture with a name, belonging to one group.
- **Emoji group**: the data group that carries a group's emoji
  (section 3).
- **Main group**: the group the emoji belong to.

The key words MUST, SHOULD and MAY are as in RFC 2119.

# 3. The Emoji Group

## 3.1 Its Group ID

The emoji of a group `<name>@<fp>` live in the group

```
<name>.emoji@<fp>
```

owned by the same key. Its Group ID follows from the main group's, so
anyone who reads the group can find its emoji without asking, and only
the main group's owner can publish them (UN-RFC 0004: the fingerprint
pins the owner).

A group name whose last segment is `emoji` is **reserved** for this
from now on:

- A client MUST NOT offer to create an ordinary group whose name ends in
  `.emoji`, and the reference implementation refuses to.
- A node MUST reject a *new* group (a first manifest) whose name ends in
  `.emoji` unless it is a valid emoji group (section 3.2). A group it
  already carries keeps working, so that no existing group breaks.
- A client treats `<name>.emoji@<fp>` as the emoji of `<name>@<fp>` only
  if its manifest is a valid emoji group; otherwise it is an ordinary
  group and has nothing to do with the emoji of the group above it.

## 3.2 Its Manifest

The manifest (UN-RFC 0004 section 3) of an emoji group has:

- `name`: `<name>.emoji`;
- `type`: `channel`, with no `posters`;
- `view`: `data` (UN-RFC 0008 section 3.1.1), so that clients do not
  offer it as a group to join;
- `emoji`: the set of section 4;
- `retention_days`: RECOMMENDED `7`, so that old versions go soon;
- `expires`: only if the main group's manifest has one, and then the
  same date; it is renewed with the main group (UN-RFC 0029).

Ordinary articles in an emoji group mean nothing. The owner SHOULD NOT
post any; nodes MAY reject them, and clients MUST ignore them.

The whole manifest, as an article, MUST NOT exceed 32 768 octets, the
size every node accepts (UN-RFC 0002 section 1). The limits of section
4 keep it below that.

## 3.3 Which Groups Have Emoji

Open, moderated and channel groups MAY have emoji. Closed groups,
inboxes, local groups, data groups and groups owned by a council
(UN-RFC 0054) MUST NOT have them in this version: a closed group's
emoji would be public pictures of a private place, and the other kinds
have no use for them. A client MUST ignore an emoji group of such a
group.

## 3.4 Changing and Removing

The owner changes the set by posting a new manifest with a higher
`serial`; the newest wins on every node (UN-RFC 0004 section 3.2). The
owner removes the emoji by posting a manifest with an empty `emoji`
object, and MAY then remove the emoji group (UN-RFC 0013).

Removing the main group (UN-RFC 0013) SHOULD remove its emoji group in
the same step. A client MUST ignore the emoji of a removed group, and a
node that holds the tombstone of a main group MAY remove its emoji
group.

As for profiles (UN-RFC 0022 section 5.3), nothing published can be
recalled from those who kept it.

# 4. The Set

`emoji` is a JSON object, in canonical JSON, from names to pictures:

```json
{"marsvin": {"v": 1, "type": "image/png", "px": 32, "data": "...", "alt": "A guinea pig"}}
```

## 4.1 Names

A name is 2 to 32 characters of lowercase letters, digits, `_`, `+` and
`-`, as a shortcode is (UN-RFC 0031 section 5.2), and

- MUST NOT be a name of the standard table (gemoji 4.1.0). A client
  MUST NOT let the owner choose one, and a client that reads one MUST
  ignore that entry;
- is unique within the set (JSON object keys are).

If a later version of the standard table adds a name a group already
uses, the standard emoji wins and the group's is ignored; the owner's
client SHOULD say so and offer to rename it.

## 4.2 Pictures

Each value is a picture object as in UN-RFC 0022 section 8.1, with these
limits instead:

| Field  | Type    | Req. | Meaning                                          |
|--------|---------|------|--------------------------------------------------|
| `v`    | integer | yes  | `1`                                              |
| `type` | string  | yes  | `image/png` or `image/webp`                      |
| `px`   | integer | yes  | `32`                                             |
| `data` | string  | yes  | b64 of the image, at most 1 024 octets before encoding |
| `alt`  | string  | no   | A short description, at most 64 characters       |

The image MUST be square, 32 by 32 pixels, and one still frame. The
owner's client produces it as UN-RFC 0027 section 9.1 requires - decoded
and encoded anew from its pixels, with no metadata - and scales it
itself; it MUST NOT send the user's file. A reader's client treats it as
UN-RFC 0027 section 9.2 requires, and treats an entry as absent if the
content does not match `type`, is not 32 by 32 or has more than one
frame.

## 4.3 How Many

A set holds at most **16** emoji. A manifest with more is invalid
(UN-RFC 0004 section 4, step 3). Sixteen pictures of at most 1 KiB, in
b64, keep the manifest well inside 32 768 octets.

Unknown fields of a picture MUST be preserved and ignored.

# 5. Nodes

A node carries emoji groups like any other group; it needs nothing new
to do so beyond section 3.1. Emoji groups carry images, and no node
should carry images it has not chosen to (UN-RFC 0027 section 1). A node
says whether it does in its node information (UN-RFC 0011 section 4):

| Field   | Type   | Meaning                                            |
|---------|--------|----------------------------------------------------|
| `emoji` | string | `accept`: carries emoji groups; `refuse`: does not |

An implementation MUST ship with `emoji` set to `refuse`; the operator
turns it on. A node that does not state `emoji` is taken to refuse them.
Refusing them never means refusing the main group.

A node that follows refusal lists (UN-RFC 0027 section 7.3) MUST apply
them to each picture: it computes the blob ID of each decoded `data`
(UN-RFC 0027 section 3.1) and refuses the manifest if one is listed.

A node whose `new_groups` policy is `trusted` or `manual` (UN-RFC 0004
section 3.3) SHOULD still accept the emoji group of a group it carries,
when `emoji` is `accept`.

# 6. Clients

## 6.1 Showing

- Where the text of an article is Markdown (UN-RFC 0031), a graphical
  client shows `:name:` as the group's picture when `name` is in the set
  of **the group the article is read in**, at the height of the text,
  with `alt` (or `:name:`) as its text alternative. Everywhere else -
  another group, a subject, a plain-text article, inside code - it stays
  text.
- A terminal client shows `:name:` as written. It MAY mark it as a group
  emoji.
- A newsreader and a gateway (UN-RFC 0015) pass `:name:` on as text.
- A client SHOULD read the emoji group in the background when the user
  opens the group, without subscribing (UN-RFC 0008 section 3.1.1), and
  SHOULD cache the set until the next manifest.
- A client that lets the user turn pictures off (UN-RFC 0022 section
  8.5) MUST then show group emoji as `:name:` too, and MUST NOT decode
  them.
- A picture is never shown bigger than the text around it, so that a
  group emoji cannot be used to post large pictures.

## 6.2 Writing

- A client's emoji picker SHOULD offer the group's emoji first while the
  user writes in that group, and inserts `:name:`, never the picture.
- The author's client sends what the author wrote (UN-RFC 0031 section
  5.2): the article carries `:name:` only.

## 6.3 The Owner

- A client SHOULD let the owner add, rename, describe and remove the
  group's emoji beside the group's other settings, show each exactly as
  it will be published, and say how many of the 16 are used.
- Before the first emoji is published, it MUST say in plain words that
  the pictures are public and cannot be fully taken back, and that some
  nodes do not carry them, so some readers see `:name:` instead.

## 6.4 Reactions

Group emoji are not reactions in this version: a group's own set of
reactions (UN-RFC 0048 section 4) holds Unicode emoji only. A later
document may allow `:name:` there.

# 7. Signature Purposes

No new purposes. The set is signed as part of the emoji group's manifest
(`UNSEENET-ARTICLE-1`).

# 8. Security and Privacy Considerations

- **Hostile images.** Each picture is decoded on readers' machines.
  Section 4.2 applies the receiving rules of UN-RFC 0027 section 9.2,
  and the size and pixel limits leave little room for decompression
  attacks or hidden data.
- **Abuse.** A picture can be offensive or illegal. It is small, shown
  only at text size and only in its own group; nodes can refuse emoji
  groups altogether (section 5) or one picture through refusal lists,
  and readers can turn pictures off.
- **Swapping.** Only the owner's key can publish the set, because the
  Group ID pins the owner. A reader sees the same `:marsvin:` as the
  owner published, or none.
- **Look-alikes.** A group emoji can look like a standard emoji or like
  another group's. It is shown only in its own group, and never in
  place of a standard name (section 4.1).
- **What nodes learn.** A node sees that a client reads a group's emoji
  group when it opens the group - which it learns anyway from reading
  the group.
- **Scale.** At most one emoji group per group, of at most 32 768
  octets, holding one manifest; a node that carries every emoji group
  of N groups stores at most 32 KiB × N, and only if its operator turned
  `emoji` on. A client fetches one manifest per group it opens, once
  until it changes; nothing grows with the number of identities.

# 9. Rationale

- **Why a group of its own?** So that a node can carry the group without
  its pictures, and the main group's manifest stays small. The images in
  the main manifest (up to ~35 KB more on every group, and a node that
  carries no pictures would have to refuse the group) was rejected
  (unseenet#156, 24 October).
- **Why `<name>.emoji`?** It is a valid group name, readable, and sits
  next to the group it belongs to. Reserving the last segment costs
  very little: a new ordinary group cannot end in `.emoji`, and groups
  that already do keep working.
- **Why inline, and not blobs?** As for pictures (UN-RFC 0022 section
  12): a manifest is the only thing nodes keep for as long as the group
  lives, and manifests cannot reference blobs.
- **Why so few and so small?** Sixteen 32-pixel pictures fit in one
  manifest every node accepts, and are enough for a community's own
  signs. Small pictures limit abuse, storage and decoding risk.
- **Why only in their own group?** So that the name means one thing
  where it is read, cannot be used to impersonate another group's, and
  needs no global registry of names.
- **Why not in closed groups?** The emoji group is public. A closed
  group's pictures would show outsiders something of a private place.
  Encrypted emoji can come later, in the group's own key.

# 10. Changes to Other Documents

- UN-RFC 0004 section 3.1: the manifest field `emoji` (object, only in
  emoji groups); names ending in `.emoji` are reserved (section 3.1).
- UN-RFC 0008 section 3.1.1: emoji groups are data groups.
- UN-RFC 0011 section 4: the policy field `emoji` (section 5).
- UN-RFC 0013: removing a group removes its emoji group (section 3.4).
- UN-RFC 0031 section 5.3: group-owned emoji are this document.
- UN-RFC 0046: the local API gives a group's emoji with the group, and
  lets the owner set them (section 4.7).
- UN-RFC 0000 section 6: 0055 is added to the index.

# 11. Open Issues

- Group emoji as reactions (section 6.4).
- Encrypted emoji for closed groups (section 3.3).

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
