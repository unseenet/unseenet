```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0054                                              October 2026
Category: Standards Track
Status: Draft
Implemented: unseenet main (unreleased); partly - sections 5 and 6 in nodes; clients (#688), Part II (#689, #690)
Updates: 0003, 0004, 0015, 0019

        Unseenet: Councils, and a Registrar Without an Owner
```

# Abstract

Every group has one owner key, pinned by its Group ID. For the project's
registrar (UN-RFC 0019) that key is the project key, which alone decides
which registrar keys are trusted: whoever holds or steals it can give
away any name, and no replica can join without it. This document adds
groups owned by a **council** - a set of member keys that changes only
when a majority of its members post the same signed manifest - and uses
one for a registrar that runs by itself. Claims become public, in two
steps (commit, then reveal), so that anybody can check every decision.
A new replica first runs as a **shadow**; once it has made the same
decisions as the council for 60 days, the members' replicas admit it
automatically. A member whose certificates no claim can explain, or that
has fallen silent, is removed the same way. After the council is
founded, no single key - the project's included - can change who the
replicas are.

# 1. Motivation

UN-RFC 0019 section 6.8 lets a registrar run as several replicas that
reach the same decisions without talking to each other. But the list of
replicas is the `posters` of a manifest that one owner key signs, so:

1. a stolen owner key lists the thief's key as a replica, which can then
   issue any name;
2. a replica run by somebody else can only join through the owner;
3. the replicas share an **inbox key** that somebody has to hand over by
   hand, and a newcomer cannot check the registrar's work before it is
   trusted, because the claims it would need are encrypted.

UN-RFC 0020 has the same shape: approvers have a quorum, but the owner
picks the approvers. A network that nobody controls needs lists that no
single key controls either.

# 2. Terms

- **Council:** the set of member keys that owns a council group.
- **Member:** a key in the council. A **full** member counts for the
  quorum; a member **on probation** does not yet (section 11).
- **Council manifest:** a manifest (UN-RFC 0004 section 3) of a council
  group. It **counts** when enough members have posted the same body
  (section 5).
- **Genesis:** the council manifest with `seq` 1.
- **Quorum:** the number of members whose identical manifests make a new
  council manifest count (section 5).
- **Shadow:** a replica that is not a member, runs the registrar's rules
  on the public claims and publishes what it would have decided
  (section 10).

The key words "MUST", "SHOULD" and "MAY" are as in UN-RFC 0000
section 2.

# Part I - Council Groups

# 3. Council Group IDs

A council group's ID has the form of UN-RFC 0004 section 1, but its
fingerprint is that of the genesis body, not of a key:

```
fp-council = first 16 characters of
             b32( H( DS("UNSEENET-COUNCIL-1") || genesis-body ) )
```

where `genesis-body` is the canonical JSON body of the genesis manifest
(UN-RFC 0004 section 3), without its trailing CRLF. The domain
separation keeps a council fingerprint from ever being a key's.

Clients SHOULD show a council group's owner as "council of N" and let
the reader see its members.

# 4. Council Manifests

A council manifest is a manifest of UN-RFC 0004 section 3 with these
changes:

- it has no `owner` field; its `Author-Key` is the member who posted it;
- `type` is `open` or `channel`;
- it has a field `council`:

| Field       | Type             | Req.          | Meaning                                           |
|-------------|------------------|---------------|---------------------------------------------------|
| `seq`       | integer          | yes           | `1` for the genesis, then one more each time      |
| `prev`      | b64 string       | from `seq` 2  | `H(DS("UNSEENET-COUNCIL-1") || body)` of the counted manifest with `seq - 1` |
| `date`      | date             | yes           | RFC 3339 UTC; not earlier than the previous `date` |
| `members`   | array of objects | yes           | At most 16; see below                             |
| `min_level` | integer          | no            | Ripening level a candidate's key needs (UN-RFC 0025); default `4` |
| `max_probation` | integer      | no            | How many members may be on probation at once; default `1` |
| `sponsors`  | integer          | no            | How many full members must sponsor a candidate (section 11.1); default `0` |
| `succeeds`  | object           | no            | Genesis only: the council this one leaves (section 13.2) |

Each member is an object:

| Field    | Type       | Meaning                                          |
|----------|------------|--------------------------------------------------|
| `key`    | key string | The member's key                                 |
| `joined` | date       | When it was admitted (the `date` of that manifest) |
| `full`   | boolean    | `true` for a full member, `false` on probation   |

A council manifest's `serial` equals `council.seq`. Every other field of
UN-RFC 0004 section 3.1 (`title`, `posters`, `min_pow`, ...) and fields
other documents add (such as `claims`, section 8) work as usual, but
change only through a new council manifest.

# 5. When a Council Manifest Counts

**Genesis.** A manifest with `seq` 1 counts when every key in its
`members` has posted an article with exactly that body, every member is
`full` with `joined` equal to the genesis `date`, there are at least 2
members, and the fingerprint of section 3 equals the one in the Group
ID.

**Later manifests.** A manifest *M* with `seq` *n* > 1 counts when

1. the manifest with `seq` *n* - 1 counts, and *M*'s `prev` is its hash;
2. *M* changes the council in at most one of these ways, and keeps the
   other fields of each member unchanged:
   - **admission:** one new member with `full` false and `joined` equal
     to *M*'s `date`, at least 30 days after the `date` of the last
     admission (or of the genesis, if there was none), and only if
     manifest *n* - 1 has fewer members on probation than its
     `max_probation`;
   - **promotion:** one member's `full` becomes `true`, at least 180
     days after its `joined`;
   - **removal:** one member is left out;
   - no change of members (other fields only);
3. *M* leaves at least 2 full members; and
4. at least *Q* different full members of manifest *n* - 1 that are still
   members in *M* have each posted an article with exactly *M*'s body,
   where *Q* is the larger of 2 and a majority (more than half) of those
   members.

A removed member does not count towards *Q*, so a council cannot be held
by the one it removes. Nodes and clients check only these rules; the
reasons for an admission or removal (Part II) are checked by the members
who sign it.

**Current manifest.** The counted manifest with the highest `seq` is
current. Its members hold the group's powers.

**Fork.** If two different bodies count for the same `seq`, a quorum of
keys has signed both, so keys are stolen or misused. Nodes and clients
MUST then keep the last council manifest before the fork as current,
MUST NOT apply any council manifest from that `seq` on, and clients
SHOULD show the group as **disputed**.

# 6. Rules for Council Groups

- **Posting.** In a `channel` council group, an ordinary article is
  accepted when its `Author-Key` is a member (full or on probation) or a
  poster of the current manifest. Council manifests themselves are
  accepted from any member of the manifest before them, and are carried
  even before they count, so that the identical copies can come
  together.
- **Not available.** Cancels (UN-RFC 0004 section 7), removing the group
  (UN-RFC 0013), closed council groups and transfer (UN-RFC 0015) are not
  defined for council groups in this document.
- **Keeping the chain.** For every council manifest that counts, nodes
  MUST keep, whatever the group's `retention_days`, enough of the
  identical copies to make it count, since a copy alone proves nothing:
  a node or client catching up (UN-RFC 0017) checks the chain back to
  the genesis from them.

# Part II - A Registrar Without an Owner

# 7. Overview

A **council registrar** is a registrar (UN-RFC 0019) whose group is a
`channel` council group. Its registrar keys (UN-RFC 0019 section 7.1)
are the members of the current council manifest, full or on probation;
its `posters` SHOULD be empty. Each member runs a replica as in UN-RFC
0019 section 6.8, with its member key as the registrar key. Everything a
replica needs to decide - claims, certificates, revocations, the
council - is public, so a replica holds no secret but its own key, and
anybody can repeat its work.

# 8. Public Claims

The council manifest names, in the field `claims`, an **open** council
group, the **claims group**, whose `min_pow` is the one UN-RFC 0019
section 6.2 asks of the claim inbox. Its council is kept the same as the
registrar group's: every change is posted as a council manifest in both,
and a replica follows the registrar group's council if the two differ.

A claim is made in two steps, both ordinary articles in the claims group
by the claiming identity (its `Author-Key`), with
`Content-Type: application/json` and a canonical JSON body:

1. **Commit.** `Subject: commit`, body `{"commit": c, "v": 1}`, where

   ```
   c = b64( H( DS("UNSEENET-NAME-COMMIT-1") || nonce || claim ) )
   ```

   `nonce` is 32 random octets and `claim` is the canonical JSON of the
   claim body of UN-RFC 0019 section 6.1.
2. **Reveal.** `Subject: reveal <commit Message-ID>`, body
   `{"claim": {...}, "nonce": b64, "reply_inbox": group-id, "v": 1}`,
   posted no earlier than one hour and no later than seven days after the
   commit's `Date`. A reveal counts only if its `Author-Key` is the
   commit's and its `claim` and `nonce` give the commit's `c`.

UN-RFC 0019 section 6.8 applies with these changes:

- **Order** (rule 1) is that of the commits: by the commit's `Date`, then
  its Message-ID. A replica handles a claim once its reveal has arrived
  and every earlier commit has been revealed or has lapsed. A commit
  without a counting reveal within seven days lapses.
- **Late claims** (rule 2) are late commits: a commit that reaches a
  replica when its `Date` is more than an hour old is refused.
- `claim` in a certificate is the commit's Message-ID, and `claimed` and
  `issued` are the commit's `Date`.

Because nobody can read a claim before its commit is an hour old, and a
commit older than an hour is refused, nobody can see a claim and get in
ahead of it. A replica answers through `reply_inbox` as in UN-RFC 0019
section 6.1, signing with its member key. There is no inbox key.

# 9. Heartbeats

Each member's replica posts in the registrar's group, at a random time
at least once in every 30 days, an article with `Subject: alive <date>`
and an empty JSON object. It shows the council that the replica runs.

# 10. Shadows

Anybody MAY run a shadow: a replica with a key of its own, ripened to at
least the council's `min_level` (UN-RFC 0025), that handles the public
claims by the rules of section 8 and UN-RFC 0019 but issues nothing.
Once a day it posts in the claims group an article with
`Subject: shadow <date>` and the body

| Field       | Type    | Meaning                                                    |
|-------------|---------|------------------------------------------------------------|
| `v`         | integer | `1`                                                        |
| `date`      | date    | The UTC day it covers                                      |
| `decisions` | array   | `[commit Message-ID, outcome hash]` for each claim it handled that day, in order |

where the **outcome hash** is
`b64( H( DS("UNSEENET-NAME-OUTCOME-1") || outcome ) )` and `outcome` is
the canonical JSON of `{"issue": [name, key, serial, expires]}`,
`{"revoke": serial}` or `{"refuse": true}`. Reasons for refusing are
left out, so wording cannot make two equal decisions differ.

A decision **depends on DNS** when it concerns a domain name (UN-RFC
0019 section 6.4).

# 11. Admission and Promotion

A shadow is **eligible** when

1. its key is ripened to the council's `min_level`;
2. it has posted a shadow report on at least 55 of the last 60 days;
3. on each day it reported, it reported every claim the council handled
   that day; and
4. none of its reports in those 60 days disagrees with the council on a
   decision that does not depend on DNS.

Each full member's replica computes the same next manifest: the eligible
shadow whose first report is the oldest is admitted, on probation, with
`date` set to 00:00 UTC of the later of the day it became eligible and
the day 30 days after the last admission. The replica posts that
manifest unless its operator holds it (section 13); the manifest counts
once a quorum of replicas has computed and posted the same body.
Removals (section 12) come before admissions and promotions: a replica
that has a removal to post posts that first.

## 11.1. Sponsors

If the council's `sponsors` is more than 0, a shadow is eligible only
if, in addition, that many full members have each posted in the claims
group an article with `Subject: sponsor <shadow key>` and the body
`{"sponsor": key, "v": 1}`, and none of them has withdrawn it
(`Subject: unsponsor <shadow key>`). A full member's sponsorship counts
only if it is the only one that member has posted in the last 180 days
for a shadow that is not yet a member. Sponsorships are public, so
anybody can see who let a member in.

Sponsoring is a promise, not a vote: it does not admit anybody by
itself, and a stolen member key can sponsor at most one candidate in
180 days. A council that wants anybody to be able to join leaves
`sponsors` at 0.

A member on probation is a registrar key from the moment the manifest
counts. After 180 days, if it is not to be removed (section 12), each
full member's replica posts the manifest that makes it full, with
`date` 00:00 UTC of the day the 180 days end.

# 12. Removal

Each full member's replica posts a manifest that removes a member *M*
when one of these holds. Its `date` is 00:00 UTC of the day the reason
arose, taken from the articles themselves - the `Date` of the
certificate in item 1, 48 hours after the third certificate in item 2,
90 days after *M*'s last article in item 3, or the previous manifest's
`date` if that is later - not from when a replica noticed, so that every
replica computes the same body:

1. **A certificate no claim explains.** *M* signed a certificate that
   the rules of section 8 and UN-RFC 0019 cannot give for any counting
   claim, leaving DNS aside: its `claim` is not a counting commit, the
   claim's action does not give that name to that key in the order of
   section 8 (UN-RFC 0019 section 6), or its `serial`, `issued` or
   `expires` is not the one the rules give. One such certificate is
   enough. A monthly renewal of a domain name, which has no `claim`,
   depends on DNS and falls under item 2.
2. **Repeatedly on its own.** At least 3 certificates by *M* in 30 days,
   on decisions that depend on DNS, lost under UN-RFC 0019 section 5.3,
   and *M* did not sign the winning decision within 48 hours (UN-RFC 0019
   section 6.8, rule 4).
3. **Silent.** *M* has posted nothing in the registrar's group for 90
   days.

If reasons hold for several members, the replica removes the one whose
reason arose first, then the next, one manifest at a time.
Certificates signed only by a removed key stop counting at once, because
trust follows the current council (UN-RFC 0019 section 7.1).

# 13. Holding

A member's operator MAY configure its replica to **hold**: to not post an
admission, promotion or removal, or any of them, until the operator
agrees. Holding is the only human safeguard; it never needs anybody
else's approval, and with fewer full members posting, the quorum
decides. Replicas SHOULD post by default, so that the registrar runs by
itself.

## 13.1. Objections

A hold is silent; an objection is not. Anybody MAY post in the claims
group an article with `Subject: object <key>` and a plain-text reason,
where `<key>` is a shadow or a member. Objections change nothing that
replicas compute. Replicas SHOULD tell their operator about every
objection by a full member, and clients SHOULD show the objections to
a candidate next to it, so that an operator who might hold has the
reason in front of them.

## 13.2. Leaving a Captured Council

Rules can slow a takeover but not stop one: a quorum that is captured
is the council (section 17). What remains is to leave it. Any 2 or more
keys MAY found a new council whose genesis has

```
"succeeds": {"group": <group-id of the old council>, "seq": <n>}
```

where *n* is the last manifest of the old council they accept. The new
council re-issues every certificate that was valid in the old one at
that manifest's `date`, as in section 14 step 2.

A council that succeeds another gets no power from it. Nodes and clients
MUST NOT follow it by themselves. Clients SHOULD show that a successor
exists, who founded it, and the objections (section 13.1) that came
before it, and let the user, or the node operator for what a node
carries, choose which council to follow. Which councils a release of a
client or node follows by default is decided by whoever publishes that
release.

This is the same right a Usenet administrator always had: to ignore a
control message from somebody they no longer trust. A council has power
only because nodes and clients choose to follow it.

# 14. Founding the Project's Council Registrar (Informative)

The project moves its registrar (UN-RFC 0019 section 7.2) in these steps:

1. The genesis is posted by the replicas that run at the time - at least
   three, on different infrastructure, ideally run by different people -
   for `unseenet.names@<fp>` and `unseenet.names.claims@<fp>`, the
   fingerprint of section 3.
2. The council re-issues, in the new group, every certificate valid in
   the old one at the genesis `date`, with the same `name`, `key`,
   `serial`, `issued` and `expires`, signed with the members' keys.
3. The reference client pins the new group in place of the old one. The
   old group's owner posts a last manifest saying the registrar has
   moved, and the old group is read until its last certificate expires.

From then on the project key has no part in the registrar.

# 15. Domain Separations

UN-RFC 0003 section 3 is extended with these labels. They are used in
hashes, not signatures; every article is still signed as in UN-RFC 0002.

| Label                       | Hashes                                     | Section |
|-----------------------------|--------------------------------------------|---------|
| `UNSEENET-COUNCIL-1`        | a council manifest body (fingerprint, `prev`) | 3, 4 |
| `UNSEENET-NAME-COMMIT-1`    | nonce and claim (commit)                   | 8       |
| `UNSEENET-NAME-OUTCOME-1`   | a decision's outcome (shadow reports)      | 10      |

# 16. Rationale

- **Why not transfer the old group to a council?** UN-RFC 0015 section
  10: a former owner can always sign a second, backdated offer, and then
  decides which of two equal chains wins. A stolen project key could take
  the registrar back. A group whose ID pins its genesis has no former
  owner.
- **Why identical articles instead of threshold signatures?** Threshold
  schemes for Ed25519 need the signers to talk to each other in rounds.
  Replicas never talk to each other (UN-RFC 0019 section 6.8); each one
  posting the body it computed itself keeps that, and the same pattern
  already counts ledger decisions (UN-RFC 0020 section 7.2).
- **Why public claims?** A shadow cannot prove it decides like the
  council without seeing the claims, and nobody outside could check the
  council's work. A claim says little that the certificate does not
  (UN-RFC 0019 section 12). Commit and reveal keep the one thing secrecy
  protected: nobody can see a claim in time to get ahead of it.
- **Why fully automatic?** Any key that approves admissions is a key that
  can be stolen. Rules every replica computes from public data, a quorum
  of replicas that each check them, and a human hold that can only slow
  things down give a registrar that runs alone and that no one key can
  steer.
- **Why so slow?** One admission per 30 days and 180 days of probation
  make taking over the council take most of a year (section 17), long
  enough for people to notice and hold. A registrar has no reason to
  grow fast.
- **Why one member on probation at a time?** It ties the pace of
  admissions to the length of probation, so a takeover cannot be
  pipelined: an attacker cannot have several keys maturing at once.
  A council that has a reason to grow faster can raise `max_probation`
  through a council manifest, which needs the quorum.
- **Why are sponsors optional?** Sponsors make membership less open, and
  an open council is a goal. They are there for a council that finds
  itself flooded by shadows; it can turn them on with one manifest.
- **Why is leaving not automatic?** Any rule that let a successor take
  over by itself would be a rule an attacker could meet too. Choosing
  which council to follow is the one decision that has to stay with
  people.
- **Why nodes check only the counting?** Nodes must agree on who may post
  without running the registrar. The reasons for a change are the
  members' business; a quorum is needed exactly because one member's
  judgement is not enough.

# 17. Security and Privacy Considerations

- **Stolen project key.** After the genesis it has no power over a
  council group. Until the move (section 14) the old registrar is as
  before.
- **Stolen member key.** The thief can sign certificates until the
  others remove the key; a certificate no claim explains removes it within
  a day of being seen (section 12). A client that requires two registrar
  keys (UN-RFC 0019 section 5.3) is not fooled even for that day. The
  thief cannot change the council alone.
- **A stolen quorum** can do anything a group owner can today. If it
  signs a second history, the fork shows (section 5). Spreading members
  over different people and infrastructure is the only defence; a
  council of two run by one person gains nothing over an owner key.
- **A patient attacker** can run perfect shadows to win a majority. With
  *h* honest full members it needs *h* + 1 full members of its own.
  With one member on probation at a time (`max_probation` 1), each
  admission waits for the previous member's 180 days, so a takeover
  takes at least 180(*h* + 1) days - two years against a council of
  three - while honest candidates compete for the same admissions.
- **Many shadows are cheap.** A shadow only repeats public work, and
  ripening (UN-RFC 0025) can run for many keys at once on many
  machines, so neither stops one operator from running dozens of
  shadows. What they cost is time, not money. Because admission is by
  the oldest first report, shadows started early - even before the
  council is founded - hold the front of the queue. The defences
  against this are, in order: the pace of admissions, sponsors (section
  11.1) where a council uses them, operators who see objections and
  hold (section 13), and, if all of these fail, leaving the council
  (section 13.2). Raising `min_level` makes each shadow dearer but does
  not change this.
- **A council that dies.** If too few members remain to reach a quorum,
  the council cannot change: its members keep issuing certificates, but
  nobody can be admitted or removed. If all stop, certificates expire
  (at most a year) and users claim names from another registrar. There
  is no owner to restart it; that is the point.
- **Withholding.** A node can hide articles from a replica, so that it
  sees a member as silent or a shadow as missing. Replicas SHOULD read
  through several nodes, and the 90-day silence rule is long on purpose.
- **Claims are public.** Anybody can now see which key claimed which
  name, including claims that were refused or lapsed. Clients MUST say so
  before sending a claim.
- **Who runs a replica** is not published: a member is a key, and its
  replica reaches the network over Tor like any client. Heartbeats are
  posted at random times so that they do not mark a schedule.
- **Scale.** Council groups are few. A council manifest is at most about
  4 KiB (16 members), and a council changes at most a few times a month,
  so the chain nodes keep grows by well under 100 KiB a year per council
  group. A claim is two small articles with postage instead of one; the
  limit of 3 registered names per key (UN-RFC 0019 section 6.2) and the
  postage bound what one identity can cost. A shadow posts one report a
  day, a few dozen octets per claim handled; heartbeats are one article
  per member a month. Nothing is added per identity beyond its own
  claims.

# 18. Changes to Other Documents

- UN-RFC 0003 section 3: the labels of section 15 are added.
- UN-RFC 0004 section 1: the fingerprint in a Group ID is a key's
  fingerprint or a council fingerprint (section 3).
- UN-RFC 0004 sections 3.1 and 4: `owner` and the check that it equals
  `Author-Key` do not apply to council manifests (section 4); which
  manifest counts and is current is decided by section 5.
- UN-RFC 0015: council groups cannot be offered or transferred.
- UN-RFC 0019 section 6.1: a registrar whose manifest has a council takes
  claims as in section 8; the claim inbox and the inbox key of section
  6.8 are not used.
- UN-RFC 0019 section 7.1: the registrar keys of a council registrar are
  the members of its current council manifest.
- UN-RFC 0000 section 6: 0054 is added to the index.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
