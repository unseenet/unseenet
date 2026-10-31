```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0061                                              October 2026
Category: Standards Track
Status: Draft
Implemented: -
Updates: 0054, 0055

       Unseenet: Council Proposals, Hearings and Objections
```

# Abstract

A council (UN-RFC 0054) runs by rules its replicas compute alike from
public data. Some decisions cannot be computed that way: changing the
council's own parameters, removing a node from a list for abuse,
endorsing a group in `unseenet.*`, extending a founding period. This
document lets a council decide those in public: a **proposal** that a
quorum of its full members has posted stands for a **hearing** of at
least 14 days, during which anybody with a ripened key can post an
**objection**. Enough objections stop the proposal or extend its
hearing; otherwise every replica applies it on the same day. Objections
are a brake, not a steering wheel: they can stop or delay, never force
anything through. It also gives every council four groups to talk in -
a closed room for the members, and open groups for proposals, talk and
a log the replicas keep by themselves.

# 1. Motivation

UN-RFC 0054 makes a council fully automatic on purpose: any key that
approves things by hand is a key that can be stolen. The only human
safeguard there is that an operator can hold its replica, which slows
the council down but cannot say no to anything in particular.

A network nobody controls still needs decisions that no rule can make
alone, and the people who use the network should have a say in them -
in public, and without trusting any one key. Anonymously, one person one
vote cannot be guaranteed: whoever can make many keys can make many
votes. So this document does not let users steer. It lets them **stop**:
a proposal needs the council's quorum to start, and anybody whose key
has cost real work (UN-RFC 0025) can object to it. The most an attacker
with many keys can do is delay.

# 2. Terms

- **Proposal:** a change a council's full members want to make, posted
  in the council's proposals group (section 4).
- **Hearing:** the time a proposal stands in public before it takes
  effect (section 5).
- **Objection:** a signed statement against a proposal, by any ripened
  key (section 6).
- **Objector:** a key whose objection counts.
- **Active member:** a full member whose key has posted an article in the
  council's proposals group or talk group (section 3) in the last 90 days.
  Heartbeats, the log and the room do not count: replicas post those by
  themselves, so they show that a machine runs, not that a person is
  there.

Objections to a proposal differ from objections to a shadow or member
(UN-RFC 0054 section 13.1): those change nothing the replicas compute and
are there for operators who might hold; these are counted, and enough
of them stop a proposal.

The key words "MUST", "SHOULD" and "MAY" are as in UN-RFC 0000
section 2.

# 3. The Council's Groups

A council manifest (UN-RFC 0054 section 4) gains these fields, each a
Group ID of a council group whose council is kept the same as the
council group's own, as for the claims group (UN-RFC 0054 section 8):

| Field       | Type     | Kind            | What it holds                                  |
|-------------|----------|-----------------|------------------------------------------------|
| `proposals` | Group ID | open            | Proposals and objections (sections 4-6)        |
| `talk`      | Group ID | open            | Discussion of anything about the council       |
| `log`       | Group ID | channel         | What the replicas did, posted by them alone (section 8) |

and the closed `room` of UN-RFC 0054 section 21, for the members.

The proposals group's `min_pow` SHOULD be that of the claims group, so
that an objection costs postage. Anybody may post in `talk` and
`proposals`; only members post in `log` and `room`.

The project's councils name their groups under `unseenet.council.*`
(`unseenet.council.proposals`, `.talk`, `.log`, `.room` for the council
that holds the lists, UN-RFC 0020), and those groups are endorsed groups
of `unseenet.*` that every node carries (UN-RFC 0055 section 4).

# 4. Proposals

A proposal is an article in the proposals group with
`Subject: proposal <id>`, `Content-Type: application/json` and a
canonical JSON body:

| Field     | Type    | Req. | Meaning                                         |
|-----------|---------|------|-------------------------------------------------|
| `v`       | integer | yes  | `1`                                             |
| `council` | Group ID| yes  | The council group it changes                     |
| `seq`     | integer | yes  | The `seq` of the current council manifest when proposed |
| `change`  | object  | yes  | What it does (below)                            |
| `days`    | integer | no   | Length of the hearing; at least 14, at most 60; default 14 |
| `urgent`  | boolean | no   | A short hearing (section 7)                     |
| `reason`  | string  | yes  | Why, at most 2000 characters, shown to everybody |

and `id` is the first 16 characters of
`b32( H( DS("UNSEENET-PROPOSAL-1") || body ) )`.

`change` is one of:

- `{"manifest": {...}}` - the next council manifest body, for changes
  UN-RFC 0054 leaves to the council: its parameters (`min_level`,
  `posters`, the groups of section 3), and an extension of the founding
  period (UN-RFC 0054 section 19);
- `{"list": {...}}` - a decision on a list the council keeps (UN-RFC
  0020), such as removing an entry for abuse or changing a rule's
  parameter;
- `{"endorse": {...}}` or `{"retire": {...}}` - a group in a hierarchy
  the council maintains, as a hierarchy list entry (UN-RFC 0018
  section 5);
- `{"rfc": {...}}` - publishing, replacing or obsoleting a UN-RFC, for a
  council that keeps the series (UN-RFC 0063 section 5).

A proposal **counts** when, within 7 days, at least *Q* different active
members have each posted an article with exactly that body, where *Q* is
the larger of 2 and a majority of the active members on the day the
proposal was first posted. Members who are not active remain members,
and their replicas go on doing what UN-RFC 0054 and 0020 compute; they
only do not count when people decide. Posting in the talk or proposals
group makes a member active again at once. A proposal whose `seq` is no longer the
current council manifest's when it would count does not count; it must
be proposed again.

What the rules of UN-RFC 0054 and 0020 decide by themselves - admissions
of shadows, removals, list entries by measured rules - needs no proposal
and has no hearing.

# 5. The Hearing

A counting proposal's hearing begins at the `Date` of the article that
made it count and lasts `days` days. Each full member's replica posts
in the log `Subject: hearing <id> open` with the proposal's id, its
`change`, its `reason` and when the hearing ends. Clients SHOULD show
open hearings of the councils the user's client relies on.

# 6. Objections

An objection is an article in the proposals group with
`Subject: objection <id>`, `References:` the proposal's Message-ID, and
a canonical JSON body `{"proposal": id, "reason": string, "v": 1}`; the
reason is optional, at most 1000 characters. It counts when

1. its `Date` is within the hearing;
2. its `Author-Key` is ripened to at least the council's `min_level`
   (UN-RFC 0025), as its `Key-Ripening` header shows (UN-RFC 0025
   section 3.4); and
3. it is the newest objection by that key to that proposal and does not
   withdraw (a body with `"withdrawn": true` takes it back).

Members may object like anybody else. Each key counts once, however
often it posts.

# 7. The Outcome

When the hearing ends, each full member's replica waits 24 hours for
late arrivals, then counts *O*, the keys whose objections count, and
compares it with *F*, the active members of the council when the
hearing began:

- *O* > *F*: the proposal **fails**.
- *O* > *F* / 2: the hearing is **extended** once, by its `days` again;
  after the extension, *O* > *F* fails it and anything less passes it.
- otherwise: the proposal **passes**.

A passed proposal is applied by every replica, dated 00:00 UTC of the day
after the hearing ended (with the 24 hours): a `manifest` change by
posting that manifest, which counts as UN-RFC 0054 section 5 says; a
`list` change as a decision of UN-RFC 0020; `endorse` and `retire` in
the council's hierarchy list. Each replica posts
`Subject: hearing <id> closed` in the log with *O*, *F* and the outcome.

**Urgent proposals.** A proposal marked `urgent` that counts with at
least two thirds of the active members has a hearing of 3 days and cannot
be extended. It is meant for removing an entry that harms people now. An
urgent removal can be undone by an ordinary proposal like any other.

**Holding.** An operator MAY hold its replica from posting any applied
proposal (UN-RFC 0054 section 13). With fewer replicas posting, the
quorum decides.

# 8. The Log

Only the replicas post in the log, and only what they did or saw:

- hearings opened and closed, with the count (sections 5 and 7);
- admissions, promotions, removals and resignations, with the rule that
  caused them (UN-RFC 0054 sections 11, 12, 19, 20);
- the founding period: its end date, how many full members are still
  missing, a renunciation, an extension;
- forks (UN-RFC 0054 section 5) and gaps in a ledger (UN-RFC 0020);
- members who will stop being active within 14 days, so that they can
  say something in the talk group if they are still there.

Every full member's replica posts each entry; entries that say the same
thing are shown once. Nobody has to write a report: the log is the
council's public record, kept by the machines that do the work.

# 9. Domain Separations

UN-RFC 0003 section 3 is extended with `UNSEENET-PROPOSAL-1`, which
hashes a proposal body into its id (section 4).

# 10. Rationale

- **Why a brake and not a vote?** A vote by keys can be bought with
  keys. A brake that keys can only pull costs an attacker as much and
  wins them at most a delay; the council's quorum still has to want the
  change. Users who see a bad proposal can stop it without anybody
  having to know who they are.
- **Why ripened keys?** Ripening (UN-RFC 0025) is the one cost every key
  pays that cannot be faked: a month of one core for level 4. It is not
  one person one key, but it makes a thousand objections cost a thousand
  months.
- **Why more objections than full members?** It scales with the council:
  a council of three can be stopped by four people who care, one of
  sixteen by seventeen. It is deliberately low; the council can propose
  again with better reasons.
- **Why active members?** Nobody can tell from the network whether a
  person is still behind a replica that runs. A member who no longer
  takes part would still count towards the quorum and never sign, and a
  few of them could stop a council from deciding anything. Counting only
  those who have spoken in 90 days needs no judgement about anybody: the
  machine keeps working, and the people who are there decide. Ninety days
  matches the silence after which a replica is removed (UN-RFC 0054
  section 12, item 3).
- **Why 14 days?** Long enough for people who do not read every day to
  notice, short enough for a council to act. Urgent removals get 3.
- **Why the log?** A decision nobody hears of is not public. The replicas
  already know everything that happened; posting it costs nothing and
  needs no person.

# 11. Security and Privacy Considerations

- **Many keys.** An attacker with many ripened keys can block or delay
  every proposal. It cannot make one pass or change the council: only
  the quorum proposes. A council under such a blockade still runs by its
  rules; what it cannot do is change them. Raising `min_level` raises
  the price, but is itself a proposal.
- **Withholding.** A node can hide objections from a replica. Replicas
  SHOULD read through several nodes, and the 24 hours of grace are for
  that. Replicas that count differently post different log entries; the
  difference shows.
- **A council that ignores the outcome.** A quorum that applies a failed
  proposal can do so: it could as well have signed the manifest without
  any proposal. The log shows it, and the users decide whether to keep
  relying on that council - or to leave it for a successor (UN-RFC 0054
  section 13.2).
- **Objections are public.** An objection shows which key objected and
  why. A key need not be a person's everyday identity; clients SHOULD
  say so before sending one.

# 12. What Is Autonomous, and What Is Not Yet (Informative)

Hearings, counts and the log run by themselves. But a proposal starts
only with the council's quorum, and while a council's members are the
replicas of one founding project (UN-RFC 0054 section 22), that is one
hand. Objections are then the only voice of everybody else - which is
what they are for.

# 13. Changes to Other Documents

- UN-RFC 0003 section 3: the label `UNSEENET-PROPOSAL-1` is added.
- UN-RFC 0054 section 4: council manifests gain `proposals`, `talk` and
  `log` (section 3).
- UN-RFC 0054 section 13: holding also covers applied proposals.
- UN-RFC 0055 section 4: the council groups of section 3 of the
  project's councils are carried by every node, as endorsed groups of
  `unseenet.*`.
- UN-RFC 0000 section 6: 0061 is added to the index.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
