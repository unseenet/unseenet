```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0038                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0023

                 Gateway Cooperation and the Gateway Directory
```

# Abstract

UN-RFC 0023 lets anybody run a gateway, but a gatewayed group is served
by one gateway: if it stops, the group stops. This document lets several
gateways serve one gatewayed group. People decide once which gateways
may take part; after that the gateways share the work and take over for
one another without any coordination beyond reading the group. It also
defines the gateway directory, where gateways announce themselves so that
people on other networks can find one to invite, and which keeps a
gatewayed group active only while one of its gateways announces it.

# 1. Overview

Two things are kept apart:

- **Admission** is decided by people. Most networks do not sign messages
  per author (Matrix, IRC, Usenet without Cancel-Lock), so a gateway can
  put words in the mouths of people there. Only gateways that both the
  other side and the group's owner have accepted may write in the group
  (section 3).
- **Cooperation** is automatic. The admitted gateways are the moderators
  in the group's manifest. Each takes a rank from its key, imports and
  exports in turns, and fills in when one with a lower rank has not
  acted within its time (sections 4 and 5). There are no heartbeats,
  no election and no central coordinator; a gateway only reads the group
  it serves.

# 2. Terms

**Gateways of a group**: the keys in the `moderators` field of a
gatewayed group's current manifest.

**Rank**: the position of a gateway's key among the gateways of a group
when sorted by fingerprint (UN-RFC 0003), counting from 0.

**Stagger**: the time each rank waits longer than the one before it. It
is 300 seconds unless the manifest's `gateway` object has a
`stagger` field (an integer, 60 to 3600).

**Origin pair**: the values of `Origin-Network` and `Origin-ID` of an
imported article (UN-RFC 0023 section 4.3).

# 3. Several Gateways per Group

## 3.1 The Manifest

A gatewayed group with several gateways lists all their keys in
`moderators`. Its manifest SHOULD NOT have a `submissions` field, so that
clients send submissions to every gateway's personal inbox
(UN-RFC 0009 section 3). The `gateway` object describes the gateway that
published the manifest; the others are described in the directory
(section 6).

The group is owned by the key that created it, normally the group key of
the first gateway. Its owner MAY hand it over to the hierarchy's
maintainer (UN-RFC 0015), after which the maintainer adds and removes
gateways.

## 3.2 Admission

A gateway joins a group that already exists in two steps:

1. **The other side agrees**, as its network profile defines for any
   gateway (UN-RFC 0023 section 6.1). For Matrix: the room's moderators
   invite the new gateway's account (UN-RFC 0037 section 6).
2. **The group's owner agrees.** The new gateway sends a **join request**
   to the personal inbox of one of the group's gateways: an inbox article
   (UN-RFC 0009) with a verified sender (the new gateway's key), the
   inner header `Gateway-Request: join`, and a JSON body:

   | Field      | Meaning                                                    |
   |------------|------------------------------------------------------------|
   | `group`    | The Group ID                                               |
   | `network`  | As in the manifest's `gateway` object                      |
   | `source`   | As in the manifest's `gateway` object                      |
   | `account`  | The new gateway's identity on the other network            |
   | `operator` | The new gateway's operator key                             |
   | `contact`  | The new gateway's operator's inbox                         |

   A gateway that holds the group key, or can ask its holder, presents
   the request to the owner (for example as in its operator's request
   desk), with what it can check itself: whether `account` is a member
   of the source on the other network. On approval it publishes a new
   manifest with the new key added to `moderators`. On refusal it
   answers the requesting gateway's inbox with the reason.

Removing a gateway is a new manifest without its key. A removed gateway
MUST stop writing in the group at its next pass.

# 4. Import by Turns

A gateway of rank *k* MUST NOT import a foreign message until it is at
least *k* × stagger old (by the time the other network gives it) and
MUST NOT import it if the group already holds an article with the same
origin pair written by one of the group's gateways. To know this, every
gateway reads the articles of the groups it serves and remembers their
origin pairs.

So the gateway of rank 0 imports everything at once; if it is down, the
gateway of rank 1 imports what is missing after one stagger, and so on.
When rank 0 comes back it imports first again. Threading uses the origin
pairs remembered from all gateways' articles, so a reply imported by one
gateway refers to a message imported by another (UN-RFC 0023 section
4.4).

The random forwarding delay of UN-RFC 0023 section 5.2 is not replaced:
the stagger comes on top of it for export, and import has none.

# 5. Export by Turns

A submission reaches every gateway of the group (section 3.1). A gateway
of rank *k* draws its random delay as before (UN-RFC 0023 section 5.2),
keeps the resulting due time, and adds *k* × stagger to it. When that
time has come it MUST NOT send the submission if

- the group already holds the approved article (same Message-ID), or
- the other network already has a message carrying the article's
  Message-ID, as the network's profile defines it (Matrix:
  `org.unseenet.message_id`, UN-RFC 0037 section 5.2; Nostr: the
  `unseenet` tag, UN-RFC 0026 section 5.2).

Otherwise it sends and approves as before. Due times SHOULD be kept in
the gateway's state, so that a restart does not draw them again.

# 6. The Gateway Directory

## 6.1 Where

Gateways announce themselves in a **directory**: an open group whose
manifest has `"view": "data"` (UN-RFC 0008 section 3.1.1). The project's
directory is `unseenet.gateways` in the `unseenet` hierarchy; clients
use it unless configured otherwise. Anybody can announce; a directory is
a list, not an endorsement.

## 6.2 Announcement

An announcement is an ordinary article in the directory, signed by the
gateway's key, with `Content-Type: application/json` and a body:

| Field      | Type   | Req. | Meaning                                                  |
|------------|--------|------|----------------------------------------------------------|
| `v`        | int    | yes  | `1`                                                      |
| `name`     | string | yes  | A short name, at most 64 characters                      |
| `operator` | key    | yes  | The operator's own key                                   |
| `contact`  | Group ID | yes | The operator's inbox                                    |
| `policy`   | string | no   | At most 1024 characters                                  |
| `networks` | array  | yes  | One object per network (below)                           |
| `groups`   | array  | no   | Group IDs this gateway serves                            |

A `networks` entry:

| Field       | Type    | Req. | Meaning                                                |
|-------------|---------|------|--------------------------------------------------------|
| `network`   | string  | yes  | As in UN-RFC 0023 section 3.2                          |
| `account`   | string  | yes  | What to invite or contact there, e.g. `@gateway:unseenet.org` |
| `import`    | bool    | yes  | Brings that network's messages into Unseenet           |
| `export`    | bool    | yes  | Sends Unseenet submissions there                       |
| `portals`   | bool    | no   | Runs portals (UN-RFC 0023 section 3.5)                 |
| `requests`  | bool    | no   | Takes requests by invitation (section 3.2, UN-RFC 0037) |

## 6.3 Renewal and Expiry

The newest announcement by `Date` from a key counts. A gateway SHOULD
announce when it starts and something changed, and at least every 7
days. Clients MUST NOT show an announcement older than 30 days, so that
gateways that stop drop out of the directory on their own.

## 6.4 Showing It

A client shows, for each gateway: its name, the accounts to invite per
network, what it does, its operator, how many of the groups it serves
are endorsed, and when it last announced. It MUST NOT present the list as
a recommendation.

# 7. When Gateways Stop

Cooperation is per group: each gatewayed group has its own gateways, and
different gateways can serve different but overlapping sets of groups. A
gateway that stops therefore leaves the groups it shared with others
running and the groups only it served without a gateway.

A gatewayed group is **active** while at least one of its gateways has a
current directory announcement (section 6.3) that lists the group in
`groups`. Its owner's key plays no part in this, so a group the first
gateway created stays active after that gateway is gone, as long as
another gateway of the group announces it.

A group that is not active:

- is shown by clients as stopped, with when it was last served;
- gets no new articles, and its existing articles expire with its
  retention as usual;
- MAY be dropped by nodes once its newest article has expired.

A gateway that comes back, or a new one admitted later (section 3.2),
makes the group active again by announcing it.

# 8. Clients and Duplicates

Two gateways can import the same message at nearly the same time (a race
within the forwarding time between nodes). A client SHOULD show only the
first article (lowest Message-ID) among articles in a group with the same
origin pair whose authors are gateways of the group.

# 9. Changes to Other Documents

- UN-RFC 0023 section 3.2: the `gateway` object MAY have `stagger`;
  a gatewayed group MAY list several gateway keys as moderators, as
  described here.
- UN-RFC 0023 section 3.3: the maintainer endorses a group, not a
  gateway; a group served by several gateways stays endorsed while any of
  them works.

# 10. Rationale

- **Why people decide admission.** A gateway's articles are believed to
  come from the other network. Letting any gateway that shows up write
  in a group would let anybody forge messages there.
- **Why ranks from fingerprints.** Every gateway computes the same order
  from the manifest alone. Nobody has to choose, and nobody can move
  ahead except by being added as a gateway.
- **Why no heartbeats or election.** Each decision is made per message
  from what is visible in the group: a lower rank has had its time and
  did not act. That needs no messages of its own, survives network
  splits, and heals itself when a gateway returns. The cost is that a
  missing rank 0 makes everything one stagger later.
- **Why liveness follows the directory and not the owner.** The owner
  of a group is usually the gateway that created it. Tying a group's life
  to its owner renewing the manifest would end groups other gateways
  still serve. A gateway's weekly announcement already says which groups
  it keeps alive.
- **Why a directory and not a list in the project's hands.** Anybody can
  run a gateway (UN-RFC 0023); the directory only makes them findable.

# 11. Security Considerations

UN-RFC 0023 section 13 applies. In addition:

- An admitted gateway can still forge messages from the other network.
  Admission is the only defence; operators SHOULD admit gateways whose
  operators they know.
- A directory announcement can lie about everything except its key.
  Clients therefore show facts they can check (groups served, their
  endorsement) next to what the announcement claims.
- Taking a gateway down does not stop a group served by others, and does
  not move an endorsement.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
