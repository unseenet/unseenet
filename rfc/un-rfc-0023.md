```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0023                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0018

                    Gateways to Other Networks
```

# Abstract

This document defines **gateways** between Unseenet and other discussion
networks, such as Usenet, FidoNet or Matrix. A gateway imports messages
from chosen groups, rooms or areas of another network into Unseenet, and
MAY send messages written in Unseenet back. Groups from another network
live under a top-level hierarchy named after it (`usenet.*`, `fido.*`,
`matrix.*`), as moderated groups whose moderator is the gateway. Import
reuses ordinary posting and export reuses the submission queue of
moderated groups (UN-RFC 0009 section 3), so nodes and clients need no new
protocol to carry gatewayed groups. Every imported article carries the
same `Origin-*` headers whatever network it came from.

What is specific to one network (how names map, how messages convert,
what the other side expects of the gateway) is left to a **network
profile** in a UN-RFC of its own. UN-RFC 0024 is the profile for Usenet.

# 1. Motivation

Unseenet borrows Usenet's model, and older and newer discussion networks
are still alive: Usenet's text groups, FidoNet's echomail, the public
rooms of Matrix. Letting Unseenet users follow them, and in some places
take part, gives the network content from day one and gives people on
those networks a way in.

But every network differs from Unseenet in ways a gateway must bridge
deliberately rather than by copying bytes. Messages elsewhere are
usually unsigned and can be edited, retracted or forged; they may carry
routing information (Usenet's `Path`, FidoNet's SEEN-BY) that Unseenet
deliberately leaves out; they may carry files, images or reactions; and
names collide with Unseenet's own (`alt.*`, `dk.*`). Above all, other
networks expect someone to be responsible for what enters them, while
Unseenet knows only signing keys, never people.

The design goals are:

1. A gatewayed group is an ordinary Unseenet group to every node and
   client that does not know this document.
2. Nothing about a gateway weakens the anonymity of nodes or users who
   never touch it, and a gateway never learns who an Unseenet author is.
3. The rules are the same for every network, so that a client that knows
   this document can show gatewayed articles from networks it has never
   heard of.

# 2. Terms

- **Other network:** a discussion network that is not Unseenet.
- **Gateway:** software, with its operator, that moves messages between
  an other network and an Unseenet node.
- **Network profile:** the UN-RFC that specifies gateways to one other
  network (section 9).
- **Source:** the group, room or area in the other network that a
  gatewayed group mirrors.
- **Gatewayed group:** an Unseenet group that mirrors one source.
- **Import:** taking a message from the other network into a gatewayed
  group. **Export:** sending an Unseenet article to the other network.
- **Group key:** the identity that owns a gatewayed group.
- **Gateway key:** the identity the gateway posts and approves with.
- **Gateway host:** the machine the gateway runs on. It has a presence on
  the other network.
- **Other side:** whoever runs the part of the other network the gateway
  connects to: Usenet peer administrators, a FidoNet hub, the moderators
  of a Matrix room.

# 3. Gatewayed Groups

## 3.1 One Hierarchy per Network

Groups from an other network live under a top-level hierarchy named
after that network. Unseenet's own groups never carry a prefix: Unseenet
is the home network and its groups get the short names (`dk.snak`, not
`unseenet.dk.snak`); groups from elsewhere are guests, and their prefix
says where they come from.

| Network | Hierarchy | Example                                   | Profile   |
|---------|-----------|-------------------------------------------|-----------|
| Usenet  | `usenet`  | `dk.politik` → `usenet.dk.politik`         | UN-RFC 0024 |
| FidoNet | `fido`    | an echo area such as `LINUX` → `fido.linux` | not yet |
| Matrix  | `matrix`  | a public room → a name under `matrix.*`    | not yet |

The network profile defines how a source's name maps to a valid group
name (UN-RFC 0004 section 1). A source whose name cannot be mapped MUST
NOT be gatewayed. When two sources map to the same name, a gateway MUST
gateway at most one of them.

On test nodes a gateway MAY put `test.` in front of the hierarchy
(`test.usenet.comp.misc`), so that the groups expire with the `test`
hierarchy (UN-RFC 0018 section 9).

## 3.2 Manifest

A gatewayed group:

- MUST be of type `moderated` (UN-RFC 0004 section 2);
- MUST be owned by a group key, and SHOULD list the gateway key as its
  only moderator. The group key SHOULD be kept offline, so that a
  compromised gateway host can be replaced by a new manifest naming a
  new gateway key (UN-RFC 0004 section 3.2);
- MUST carry a `gateway` object in its manifest (below);
- for export, MUST name a `submissions` inbox owned by the gateway key
  (UN-RFC 0009 section 3).

The `gateway` field:

| Field       | Type       | Req. | Meaning                                              |
|-------------|------------|------|------------------------------------------------------|
| `network`   | string     | yes  | The network's name: the hierarchy name of section 3.1 (`usenet`) |
| `source`    | string     | yes  | The source, exactly as the other network names it   |
| `direction` | string     | yes  | `import` or `both`                                   |
| `host`      | string     | yes  | The gateway's own identity in the other network, as the profile defines it (a Usenet path identity, a FidoNet address, a Matrix server name) |
| `operator`  | key string | yes  | The operator's identity key                          |
| `contact`   | Group ID   | yes  | The operator's contact inbox (UN-RFC 0011 section 5) |
| `abuse`     | string     | if `both` | Where people on the other network can complain, as the profile defines it |
| `policy`    | string     | no   | Free text, at most 2048 characters: what is filtered, kept and logged |

Nodes that do not know this field preserve and ignore it (UN-RFC 0004
section 3.1), so they carry gatewayed groups like any moderated group.

## 3.3 Endorsement

Each network's hierarchy is `reserved` in the root list until the first
gateway for that network is endorsed, and then becomes `governed`
(UN-RFC 0018), with the project or a delegate as maintainer. The
maintainer endorses at most one gatewayed group per source (UN-RFC 0018
section 5).
Anybody may still run their own gateway for the same source; their group
has the same name with a different fingerprint and is shown as
unendorsed (UN-RFC 0018 section 8.1).

A maintainer SHOULD endorse a gateway only when its operator has agreed
to the duties in section 6 and the other side has agreed to the gateway
(section 6.1).

## 3.4 Names Already in Use

The hierarchies of section 3.1 are in the root list from the start
(section 11), before any group exists in them, so that nobody builds a
community under a name a gateway will later need.

Nothing in this document removes a group (UN-RFC 0018 section 3). If
groups exist under a network's hierarchy before it is governed, for
example created while the name was unclaimed, they stay where they are.
Once the hierarchy is governed they are unendorsed, and clients show
their fingerprint and warn on subscribing as for any unendorsed group.

A name, or a `gateway` field in a manifest, does not make a group a
gateway: anybody can create `usenet.comp.misc@<their key>` and write a
`gateway` field into its manifest. A client MUST NOT present a group as
gatewayed (section 8) unless it is endorsed by the maintainer of the
network's hierarchy. A group that carries a `gateway` field but is not
endorsed SHOULD be shown with a warning that it claims to be a gateway
and is not recognised as one.

When a new network is added and the name that would naturally be its
hierarchy is already in active use by an Unseenet community, the project
SHOULD choose another name for the network rather than take the
community's (UN-RFC 0018 section 7.2).

# 4. Import

## 4.1 What Is Never Imported

Whatever the network, a gateway MUST NOT import:

1. messages that control the other network (group creation, removal,
   cancels, administrative messages); the profile names them;
2. messages that came from Unseenet through the same or another gateway
   (the profile says how they are recognised), so there are no loops;
3. files, images and other non-text content. The profile says whether a
   short text placeholder (such as "[image omitted]") is written instead;
   a placeholder MUST NOT be a link;
4. messages larger than 64 KiB after conversion (UN-RFC 0002 section 1),
   or larger than the receiving node accepts;
5. messages the gateway's spam filter rejects;
6. messages from encrypted rooms or areas of the other network. Only
   sources that are public there can be gatewayed, just as only open
   Unseenet groups can be exported (section 5.4).

A gateway imports only from sources it has gatewayed groups for. It MAY
import only messages newer than the time the gatewayed group was
created.

## 4.2 Conversion

For each imported message the gateway builds a new Unseenet article
(UN-RFC 0002):

| Unseenet header  | Value                                                          |
|------------------|----------------------------------------------------------------|
| `Newsgroups`     | The gatewayed group's Group ID                                 |
| `Date`           | Time of import, rounded down to 10 minutes (UN-RFC 0002 section 2.5) |
| `From`           | The author's display name in the other network, at most 128 characters |
| `Subject`        | The subject, if the other network has one, at most 256 characters; otherwise as the profile defines |
| `Author-Key`     | The gateway key                                                |
| `References`     | Section 4.4                                                    |
| `Content-Type`   | `text/plain; charset=utf-8`                                    |
| `Origin-*`       | Section 4.3                                                    |

Header values are unfolded and stripped of control characters. The body
is converted to UTF-8 plain text; if it cannot be, the message is not
imported. The profile adds network-specific headers and rules.

The gateway signs the article with the gateway key and pays its postage
(UN-RFC 0006). Because the gateway key is the group's moderator, the
article is accepted without `Approved-By` (UN-RFC 0004 section 5).

The time of import is used for `Date` because dates in other networks are
unchecked and often outside the window nodes accept. The original date is
kept in `Origin-Date`.

## 4.3 Origin Headers

Every imported article MUST carry:

| Header           | Value                                                          |
|------------------|----------------------------------------------------------------|
| `Origin-Network` | The network's name, the same as `network` in the manifest      |
| `Origin-ID`      | The message's identifier in that network, as text              |
| `Origin-Date`    | The message's date as that network gives it, as text           |
| `Origin-From`    | The author as that network names them, as text                 |

`Origin-Date` and `Origin-From` MAY be left out when the other network
gives no such value. Values are copied as the other network gives them
and are not checked; they are information for the reader, not facts the
gateway vouches for.

Headers that only make sense for one network carry that network's name
as a prefix (`Usenet-Newsgroups`) and are defined in its profile.

A client that knows the origin headers can show any gatewayed article,
from any network, without knowing the profile for that network.

## 4.4 Threads

The gateway keeps a table from identifiers of imported messages to the
Unseenet Message-IDs it created, and from Unseenet Message-IDs it has
exported to their identifiers in the other network.

When an imported message replies to or refers to others, the gateway
puts the mapped Unseenet Message-IDs into `References`, oldest first.
References that cannot be mapped are left out; the profile MAY keep the
original in a network-specific header, so that later imports can still
thread correctly.

## 4.5 Changes, Retractions and Removal

Many networks let authors edit or retract messages; Unseenet articles
are signed and cannot change. A gateway therefore:

- imports an edit as a new article that refers to the old one in
  `References`, or not at all, as the profile says;
- MAY act on a retraction or cancel according to its stated policy, by
  posting an Unseenet cancel (UN-RFC 0004 section 7) for the imported
  article as moderator, but only when the other network authenticates
  the retraction or the profile gives another reason to trust it;
- MUST honour a request in the other network not to archive a message
  (the profile names it) by not importing it or by giving it `Expires`
  at most 7 days after import. Archive nodes (UN-RFC 0012) MUST NOT keep
  a gatewayed article past its `Expires`;
- SHOULD act on requests by the author of an imported message to remove
  it, by posting a cancel. Such requests reach the operator's `contact`
  inbox or `abuse` address.

# 5. Export

Export is OPTIONAL and happens only in groups whose manifest says
`"direction": "both"`.

## 5.1 Submitting

A user posts to a gatewayed group exactly as to any moderated group: the
client builds and signs the article and sends it to the `submissions`
inbox (UN-RFC 0009 section 3). The article keeps the author's own key
and signature.

Before submitting to a gatewayed group, a client that knows this
document MUST tell the user, once per group, that:

- the article will be published on the other network, outside Tor, where
  it may be kept for years and copied to servers the user cannot ask to
  delete it from;
- it will carry the display name, the key fingerprint and the text;
- the gateway operator, not the user, decides whether it is sent.

## 5.2 Checking and Sending

For each submission the gateway:

1. performs the checks a moderator's client must perform (UN-RFC 0009
   section 3);
2. applies its export policy (section 6.2); a refused submission is
   dropped, and the gateway MAY reply to the submitter's `Reply-Inbox`
   with a short reason;
3. converts the article as the profile says, and sends it to the other
   network;
4. only after the other network has accepted it, approves the original
   article and posts it to the gatewayed group (UN-RFC 0004 section 5).
   Its Message-ID is unchanged.

If the other network refuses the article, the gateway MUST NOT approve
it, so that an article never appears in a gatewayed group without also
being on the other network. A gateway SHOULD wait a random time before
step 3 (RECOMMENDED: uniformly 0 to 10 minutes), so that the time of
sending says little about when the author submitted.

The exported message SHOULD carry the author's display name and the
first characters of the key fingerprint, so that readers on the other
network can tell Unseenet authors apart, and SHOULD carry the full key
where the other network has room for it. It MUST NOT carry anything else
about the author.

## 5.3 No Timing Signals

Some networks show when a user is typing, has read a message, or is
online. A gateway MUST NOT generate such signals for Unseenet authors, or
anything else that changes with an author's activity apart from the
exported message itself. They would reveal when an author is active and
undo the random delays of UN-RFC 0005 section 5.5 and section 5.2 above.

## 5.4 What Is Never Exported

A gateway MUST NOT export:

- articles from any group other than the gatewayed group they were
  submitted to;
- articles from closed groups, inbox groups or local groups, or any
  encrypted article;
- control articles, including cancels: a cancel in Unseenet does not
  reach the other network (but see section 6.2 for the operator's own
  retractions);
- articles whose body is not plain text, or that exceed the other
  network's size limit.

# 6. Duties of a Gateway Operator

## 6.1 Consent of the Other Side

A gateway connects to the other network with the agreement of whoever
runs the part it connects to:

| Network | Who agrees                                                    |
|---------|---------------------------------------------------------------|
| Usenet  | the administrators of the peer servers                        |
| FidoNet | the hub or net coordinator the gateway's system is linked to   |
| Matrix  | the moderators of each room, by inviting the gateway           |

An operator:

- MUST NOT import from or export to the other network against its
  terms or the other side's wishes, and MUST stop when asked;
- SHOULD tell the other side plainly that the gateway leads to Unseenet,
  and point them to this document and the profile;
- MUST keep the `contact` inbox read and act on removal requests
  (section 4.5);
- MUST state in `policy` what is filtered and what is logged.

## 6.2 Export

To the other network, the gateway is responsible for everything it
exports, much as an injecting server is on Usenet. Unseenet gives the
gateway no address or account to act on, only the author's key. An
operator that exports therefore:

- MUST publish a working `abuse` contact and answer complaints;
- MUST be able to stop an author: by banning the key in the group's
  manifest (UN-RFC 0004 section 5.1), which is public and stops all
  gateways using that manifest, or by refusing the key's submissions
  locally;
- MUST keep, for as long as exported messages are likely to be kept on
  the other network, which key wrote each exported message. This record
  is pseudonymous: it says which key wrote a message, never who holds
  the key or where the article came from;
- MUST NOT try to learn more about authors than their key, for example
  by asking for contact details or by logging anything about the node
  or circuit a submission arrived through. A gateway that did would
  undo the anonymity Unseenet exists to give;
- MUST make this plain to the other side before exporting: the gateway
  can stop a key, but cannot identify or trace a person;
- MAY retract on the other network a message it exported, for example
  after a complaint or at the author's request;
- MUST limit the rate of exports per key, and SHOULD limit it per group;
- SHOULD require more postage on submissions than the group's `min_pow`
  (RECOMMENDED: at least 24 bits), and MAY refuse keys it has not seen
  in the network for some time, since keys cost nothing to make;
- SHOULD apply the same spam filter to exports as to imports.

## 6.3 The Gateway Host

The gateway host has a presence on the other network, normally on the
open Internet and often under a stable name in `host`. It is not hidden,
and nothing in this document tries to hide it.

- A gateway host MUST NOT also run an Unseenet node whose location is
  meant to be hidden. Exchanging traffic between the two on one machine,
  or one operator running both with matching uptime, links the hidden
  node to a public address.
- The gateway talks to Unseenet like a client: over Tor, to one or more
  nodes, with no special status. Nodes need not know which of their
  clients is a gateway.
- A public "backbone" node whose operator does not need location hiding
  (for example one using single onion service mode) MAY share a host
  with a gateway.

# 7. Nodes

A node carries a gatewayed group like any moderated group and needs no
support for this document. A node operator MAY decide not to carry some
or all networks' hierarchies, for example because the operator does not
want to store content from outside the network; this is the ordinary
choice of what to carry (UN-RFC 0004 section 3.3).

# 8. Clients

For an endorsed gatewayed group (section 3.4), a client that knows this
document SHOULD:

- mark it as gatewayed, with the network, the source and the gateway's
  `host`;
- show `Origin-From` and `Origin-Date` for imported articles, and make
  clear that their author has no Unseenet identity and that the gateway
  key, not the author, signed them;
- for `"direction": "import"`, not offer to post;
- for `"direction": "both"`, give the warning of section 5.1 before the
  first submission.

A client that does not know this document shows imported articles as
posts by the gateway key with the original author's name in `From`. That
is misleading but not wrong, which is why the gateway key's profile
(UN-RFC 0022) SHOULD make the situation plain, for example by naming
itself "Usenet gateway".

# 9. Network Profiles

Each other network is specified in a profile, a Standards Track UN-RFC
that updates this one. A profile MUST specify:

1. the network's name and hierarchy (section 3.1), and the meaning of
   `source`, `host` and `abuse` in the manifest;
2. how a source's name maps to a group name;
3. what `Origin-ID`, `Origin-Date` and `Origin-From` contain;
4. how messages convert in both directions, including subjects, replies
   and threads, edits and retractions, and any network-specific headers;
5. what is never imported or exported beyond section 4.1 and 5.4, and how
   messages that came from Unseenet are recognised (section 4.1 item 2);
6. how the gateway reaches the other network and who the other side is
   (section 6.1);
7. the network's own timing signals and any other way it could reveal
   when an author is active (section 5.3).

| Network | Profile                     |
|---------|-----------------------------|
| Usenet  | UN-RFC 0024                 |
| FidoNet | reserved, not yet written   |
| Matrix  | reserved, not yet written   |

# 10. Headers Defined Here

| Header           | Defined in  |
|------------------|-------------|
| `Origin-Network` | section 4.3 |
| `Origin-ID`      | section 4.3 |
| `Origin-Date`    | section 4.3 |
| `Origin-From`    | section 4.3 |

They are ordinary optional headers (UN-RFC 0002 section 2.3), covered by
the gateway's signature. Nodes preserve them without knowing this
document.

# 11. Changes to Other Documents

- UN-RFC 0018 section 9: the root list gains `usenet`, `fido` and
  `matrix`, all `reserved`, for gateways to Usenet, FidoNet and Matrix.
  Each becomes `governed`, with the project key as maintainer, when the
  first gateway for that network is endorsed (section 3.3); the project
  MAY later delegate it. Names for further networks are added to the
  root list when they are first proposed.
- UN-RFC 0004 section 3.1: manifests of gatewayed groups carry the
  `gateway` field of section 3.2. No change is needed in nodes, which
  already preserve unknown fields.
- UN-RFC 0012: archive nodes honour `Expires` on gatewayed articles
  (section 4.5).

# 12. Rationale

- **Why one hierarchy per network instead of mixing groups in?**
  Mixing imported and native groups under one name would give readers two
  groups called `dk.politik` with different rules, authors and lifetimes.
  The prefix says where a group comes from, and one prefix per network
  keeps the rule the same for every gateway.
- **Why reserve names now?** It costs nothing while nobody uses them, and
  later it would mean taking a name from a community (section 3.4).
- **Why `Origin-*` headers instead of one set per network?** The author,
  date and identifier in the other network are what a reader needs for
  every gateway. With shared names a client learns them once and can show
  articles from networks it has never heard of.
- **Why does a `gateway` field not make a group a gateway?** Anybody can
  write one. Endorsement by the hierarchy's maintainer is the only thing
  that says "this group really mirrors that source".
- **Why moderated groups with the gateway as moderator?** It is the only
  existing group type in which one key can post on behalf of others
  while users can still submit. Export then needs no new mechanism, and
  an exported article keeps its author's signature inside Unseenet.
- **Why approve only after the other network accepted?** A gatewayed
  group should show the same conversation as its source. An article
  that exists on only one side splits the thread.
- **Why not sign imported articles with per-author keys?** The gateway
  would hold keys for people who never chose to be in Unseenet, and the
  signatures would claim more than the gateway knows. One gateway key
  says exactly what is true: "this gateway saw this there."
- **Why can't a gateway keep a "log of who posted what"?** Other networks
  trust their servers to know their users so that abuse can be traced. A
  gateway does not know who its authors are and must not: a submission
  reaches it through Tor and an inbox, signed by a key that costs nothing
  to make. What it can offer instead is control: it can refuse a key,
  ban it in public, raise the postage and limit the rate. This is the
  bargain the anonymous mail-to-news gateways offered Usenet, and the
  other side is free to accept or refuse it.

# 13. Security and Privacy Considerations

- **Exported articles leave Tor.** They are copied to servers that may
  keep and index them for years and do not honour Unseenet cancels. The
  author's fingerprint and display name go with them, which links the
  author's posts there to everything else the same key has posted in
  open Unseenet groups. Authors who care SHOULD use a separate identity
  for gatewayed groups (UN-RFC 0003 section 2). Clients MUST warn
  (section 5.1).
- **Timing.** The gateway sends an article some time after the author
  submitted it. The submission travels through Tor to an inbox, and the
  gateway adds a random delay (section 5.2), so the time of sending says
  little about where or when the author was online. It is still a public
  timestamp close to the time of writing. Networks with presence, typing
  or read signals are a further risk, which section 5.3 rules out.
- **The gateway sees every submission in plain text.** Submissions are
  sealed to the gateway key, as to any moderator. The gateway, and anyone
  who seizes the gateway host, can read submissions that were refused.
  Operators SHOULD delete refused submissions.
- **The gateway can lie.** It signs imported articles, so it can alter,
  invent or drop them, and readers can only check them against the
  source. Endorsement (section 3.3) is the defence: readers trust the
  endorsed gateway, and anybody may run a second gateway to compare.
- **Groups pretending to be gateways.** A group can copy a gateway's name
  and `gateway` field. Section 3.4 makes clients rely on endorsement, not
  on either.
- **Imported content is not limited by Unseenet postage.** A gateway pays
  postage for everything it imports, so a flood on the other network
  becomes CPU load on the gateway, but it still fills nodes. Gateways
  MUST filter (section 4.1) and SHOULD cap imports per group per day.
- **Legal exposure.** The gateway operator republishes third-party
  content into Unseenet and, for export, publishes anonymous content on
  the other network under their own name. Gateways are therefore best run
  by people or organisations willing to be publicly responsible. Personal
  data in imported messages is subject to the operator's local law;
  section 4.5 provides removal.
- **Files and media** are excluded in both directions (sections 4.1 and
  5.4). Gatewaying them would turn Unseenet into a file distribution
  network, which UN-RFC 0002 section 8 rules out.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
