```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0020                                              October 2026
Category: Standards Track
Status: Draft
Implemented: -
Updates: 0010, 0018, 0043, 0055

               Unseenet: Lists Kept by Councils
```

# Abstract

The network has lists that tell clients where to start: the known nodes
(UN-RFC 0010), the root list of hierarchies (UN-RFC 0018) and the known
web entrances (UN-RFC 0043) - and, new here, the known scribes, which
keep the network's source code. Today one key - the project's - decides
what is on them, through a process that runs on GitHub. This document
gives the lists to a **council** (UN-RFC 0054) whose replicas compute
them from public data by rules anybody can check:

- a node is listed when it announces itself, carries what it must and is
  measured as connected;
- a free top-level hierarchy goes to the first claim, and one named
  after a domain or a country code only to whoever proves it in DNS;
- an entrance is listed like a node;
- a scribe is listed when it serves the source of the current signed
  releases (section 6.4).

What no rule can decide - removing an entry for abuse, changing a rule's
parameter - goes through a proposal with a public hearing (UN-RFC 0061).
No single key, the project's included, decides what is listed.

# 1. Motivation

The project's lists depend on one key and one company:

1. the project key decides every entry, and whoever holds or steals it
   can list or delist anything;
2. requests are GitHub issues, checks run in GitHub Actions, and the
   source of truth is files in a repository whose history can be
   force-pushed;
3. if the project or its account disappears, nobody can get a node
   listed or a hierarchy granted.

An earlier draft of this document moved the process into the network
but kept people with approver keys, chosen by the owner, deciding each
request. That still leaves the lists one owner's. Nearly every decision
is a fact that can be measured or a rule that can be applied: does the
node answer, does it carry the network's groups, was this the first
claim, does DNS say so. This document makes those the rules, and leaves
only the rest to people, in public.

# 2. Terms

- **List council:** the council (UN-RFC 0054) that keeps a set of lists.
- **Entry:** one item of a list: a node, a hierarchy, an entrance, a
  scribe.
- **Scribe:** a service, reached over Tor, that keeps the releases of
  one or more publishers (UN-RFC 0062) together with all the source code
  they are built from, and serves them to anyone (section 6.4).
- **Announcement:** an article in which a node or entrance describes
  itself, signed with its own key.
- **Hierarchy claim:** a commit and reveal (UN-RFC 0054 section 8) that
  asks for a top-level hierarchy.
- **Measurement:** what a replica found when it tried to reach an entry.

The key words "MUST", "SHOULD" and "MAY" are as in UN-RFC 0000
section 2.

# 3. What Does Not Change

- The formats of node lists (UN-RFC 0010 section 2), root lists and
  hierarchy lists (UN-RFC 0018 sections 4 and 5) and entrance lists
  (UN-RFC 0043 section 8.1).
- How clients read lists: the newest valid list from the pinned list
  group. Clients pin the new list groups (section 10) instead of the
  old ones; otherwise they need no change.
- What an entry means and what it cannot do. The root list does not
  decide whether a hierarchy exists or is carried (UN-RFC 0018
  section 3); the node list says which nodes this council vouches for,
  not which nodes exist (UN-RFC 0055 section 8).
- Hierarchy lists are still published by each hierarchy's maintainer -
  except `unseenet.*`, whose maintainer is the list council (section 6.2).
- The directory of gateways (UN-RFC 0038 section 6) is already an open
  group where gateways announce themselves; it stays as it is.

# 4. The List Council

A list council is a `channel` council group (UN-RFC 0054 Part I). Its
council manifest has, besides the fields of UN-RFC 0054 and 0061:

| Field     | Type     | Req. | Meaning                                              |
|-----------|----------|------|------------------------------------------------------|
| `lists`   | object   | yes  | Which list group holds which list, e.g. `{"nodes": …, "root": …, "entrances": …, "scribes": …}` |
| `claims`  | Group ID | yes  | The open claims group for hierarchy claims (section 5.2) |
| `reports` | Group ID | yes  | Where replicas post measurements (section 7)         |
| `min_software` | object | no | The lowest version of each implementation that may be listed, e.g. `{"unseenet": "0.7.2"}` (section 6.5) |
| `publishers` | array of Group IDs | for `scribes` | The releases channels (UN-RFC 0062) whose releases a listed scribe keeps |
| `import`  | string   | no   | Message-ID of the import (section 9); genesis only   |

Each list group is a `channel` council group with the same council, so
that the members' replicas, and nobody else, post the lists. Everything
the rules use is public: announcements, claims, measurements, passed
proposals and the council itself. A replica holds no secret but its own
key, and anybody can repeat its work - and, as a shadow, prove it can
(UN-RFC 0054 section 10).

# 5. Inputs

## 5.1 Announcements

Nodes announce themselves as UN-RFC 0055 section 5 says, signed with
their node key, in `unseenet.nodes.announce`. Entrances announce
themselves the same way in `unseenet.entrances.announce`, with the
entrance's information (UN-RFC 0043 section 4.3), its open-web and onion
addresses and its operator's promise of UN-RFC 0043 section 5, signed
with the entrance's key. Scribes announce themselves in
`unseenet.scribes.announce` with their onion address, the publishers
they keep and, optionally, `name`, `operator` and `contact` as for
entrances, signed with the scribe's key. An announcement is current for
30 days; an entry renews it by announcing again.

## 5.2 Hierarchy Claims

A top-level hierarchy is claimed as names are (UN-RFC 0054 section 8): a
commit and, between one hour and seven days later, a reveal, both in the
council's claims group, by the claiming key. The claim body is

| Field     | Type     | Req. | Meaning                                        |
|-----------|----------|------|------------------------------------------------|
| `v`       | integer  | yes  | `1`                                            |
| `action`  | string   | yes  | `claim`, `renew`, `change` or `release`        |
| `name`    | string   | yes  | The top-level name, e.g. `games`               |
| `list`    | Group ID | for `claim`, `change` | The hierarchy list group; its fingerprint is the claiming key's |
| `title`   | string   | for `claim` | Up to 100 characters                     |
| `charter` | string   | no   | Up to 2000 characters                          |
| `maintainer` | key string | for `change` | A new maintainer key            |

The claiming key MUST be ripened to the council's `min_level` (UN-RFC
0025), and a key holds at most 3 top-level hierarchies.

## 5.3 Measurements

Each replica tries to reach every announced node, entrance and scribe at
least once a day and posts its findings (section 7).

## 5.4 Passed Proposals

Proposals that passed their hearing (UN-RFC 0061) and change a list:
removing an entry for abuse, adding a name to the reserved names, or
changing a parameter of section 6.

# 6. The Rules

## 6.1 Nodes

A node is on the node list when

1. its announcement is current (section 5.1);
2. its `carries` (UN-RFC 0055 section 3.1) includes the infrastructure
   groups and the endorsed groups of `unseenet.*` (UN-RFC 0055 section 4);
3. at least one replica reached it and it authenticated with its node key
   (UN-RFC 0016) on at least 5 of the last 7 completed UTC days; and
4. it is connected in the sense of UN-RFC 0021, counted over the groups
   it carries.

It leaves the list when one of these stops holding, with one grace: a
listed node is only taken off for item 3 when, for each of the last 10
completed days, at least one replica reported on it and none reached it
(section 7). It comes back by itself when the rules hold again.

## 6.2 Hierarchies

The root list follows from the claims, in the order of their commits:

- **Reserved names** are never granted by a claim: those of UN-RFC 0018
  section 9 and any a passed proposal adds.
- **`unseenet`** has the list council itself as maintainer. Its
  hierarchy list is posted by the replicas, and endorsing or retiring a
  group in it is a proposal with a hearing (UN-RFC 0061); every node
  carries the endorsed groups (UN-RFC 0055 section 4.1).
- **A name equal to a country-code top-level domain, or to a domain
  name's first label where that domain is registered** (`dk`,
  `torproject`) goes only to a claim whose key the domain names in DNS,
  as UN-RFC 0019 section 6.4 proves a domain for a name. Such a grant is
  renewed when the DNS record is checked again, monthly; it lapses when
  the record is gone for 30 days.
- **Any other free name** goes to the first counting claim. The grant
  lasts one year from its commit and is renewed by a `renew` claim from
  the maintainer; it lapses when it is not renewed, or when the
  maintainer has not published a hierarchy list for 180 days (UN-RFC
  0018 section 7.2).
- **`change`** moves a hierarchy to a new maintainer key and must come
  from the current maintainer; **`release`** gives it up.
- **No maintainer:** a name without a grant is free, like `alt.*`: no
  blocks across it, only each group owner's rules (UN-RFC 0018
  section 8.3).

Decisions that depend on DNS are handled as UN-RFC 0054 section 12,
item 2, handles them for names.

## 6.3 Entrances

An entrance is on the entrance list under the rules of section 6.1, with
"reached" meaning that a replica fetched its page over Tor and the
release it serves matches a valid signed release (UN-RFC 0043 section
7.6, UN-RFC 0062).

## 6.4 Scribes

A scribe keeps code alive where no company can delete it. It serves,
over its onion service and plain HTTP:

- `/scribe.json`: `{"v": 1, "key": …, "software": …, "publishers":
  {<releases channel>: [<version>, …]}, "git": [<repository>, …]}` - what it holds - with a
  detached signature by its key in `/scribe.json.sig`;
- for each release it holds, under `/<releases channel>/<version>/`:
  `SHA256SUMS.txt`, `SHA256SUMS.txt.sig` and every file the checksums
  name, the release's source bundle (UN-RFC 0062 section 5) included;
- MAY: full mirrors of the publisher's repositories under
  `/git/<repository>.git`, so that `git clone` works over Tor.

A scribe MUST NOT serve a file under a release unless it matches a
valid signed release of that publisher (UN-RFC 0062 section 4). It MAY
fetch releases from anywhere - the publisher, a web entrance, another
scribe - since only the signatures count. It SHOULD keep at least the
last 5 releases of each publisher it keeps.

A scribe is on the scribe list when

1. its announcement is current (section 5.1);
2. its `/scribe.json` names every publisher of the council's
   `publishers`, and holds the newest valid release of each within 7
   days of that release appearing in its releases channel;
3. at least one replica fetched its `/scribe.json` over Tor, with a
   valid signature by the announced key, and the signed `SHA256SUMS.txt`
   of each newest release, on at least 5 of the last 7 completed UTC
   days; and
4. in the last 7 days, at least one replica fetched one whole file of a
   release the scribe holds, chosen at random, and it matched its
   checksum.

It leaves and comes back as a node does, with the same grace (section
6.1). The scribe list is a JSON object `{"v": 1, "updated": "...",
"scribes": [...]}`, at most 200 entries, each with `onion`, `key` and
`publishers`, and `name`, `operator`, `contact` and `description` as in
UN-RFC 0043 section 8.1.

The list says who keeps the code, not who is honest: a client uses only
what matches the signatures, whoever served it.

## 6.5 Minimum Versions

Nodes (UN-RFC 0011), entrances (UN-RFC 0043 section 4.3, in a field
`software` this document adds) and scribes (section 6.4) state their
software as `"<implementation> <version>"`. An
entry whose implementation is named in the council's `min_software`,
and whose version is lower, is not on the list, whatever else holds; it
comes back by itself when it is updated. An implementation the field
does not name is not affected.

The council sets `min_software` by proposal (UN-RFC 0061), when a
version has a known flaw that harms the network or its users - not to
favour one implementation. The field says nothing about servers that
are not listed, and nobody is cut off by it: a server below the minimum
still works, but is no longer recommended to new clients. Clients
SHOULD warn their user when the node they use is below the minimum.

A version is self-declared. The rule does not stop a server that lies;
it catches the honest one that nobody updates any more, which is the
common case (UN-RFC 0062 section 6.1).

## 6.6 What Only a Hearing Can Change

A replica never removes an entry, adds a reserved name or changes a
number in this section on its own judgement. Those are proposals with a
hearing (UN-RFC 0061). An urgent proposal (UN-RFC 0061 section 7) can
take an entry off within three days when it harms people.

# 7. Measurements

Each replica posts one `report <date>` article per UTC day in the
`reports` group:

| Field     | Type          | Req. | Meaning                                   |
|-----------|---------------|------|-------------------------------------------|
| `v`       | integer       | yes  | `1`                                       |
| `date`    | string        | yes  | The UTC day, `YYYY-MM-DD`                 |
| `reached` | array of keys | yes  | Node, entrance and scribe keys that answered and authenticated |
| `missed`  | array of keys | yes  | Those that did not                        |
| `files`   | array         | no   | Whole files fetched from scribes: `{"scribe": key, "file": path, "ok": bool}` |

Replicas see the network from different places and may disagree for a
day. Rule 6.1 item 3 needs one replica to have reached a node, and the
grace takes a node off only when none has, so one replica with a bad
connection can neither keep a dead node on nor take a live one off.

After 3 days with no replica reaching a listed node, the replica whose
key sorts first among those reporting sends a notice to the inbox of the
node's operator, if its announcement names one.

# 8. Computing and Publishing the Lists

Each list is a function of the inputs of section 5 up to the end of a
UTC day. Every replica computes it once a day, and posts it to its list
group when it changes and at least monthly (UN-RFC 0010 section 3). The
list's `updated` field is `council <seq> day <date>`: the council
manifest and the day it was computed from. Replicas that have seen the
same inputs post identical lists, so it does not matter whose post is
newest.

A replica that finds a newer post in a list group that differs from its
own result for the same day MUST post its own result again, and SHOULD
post the difference in the council's log (UN-RFC 0061 section 8): either
the replicas have not seen the same inputs yet, or a member key is
misused - which the members' own rules then handle (UN-RFC 0054
section 12).

# 9. Founding a List Council (Informative)

A list council starts from the lists as they are. The genesis manifest's
`import` names an article in the council group holding the current lists
(for the project: `nodes.json`, `hierarchies.json` and the entrance
list), posted with identical bodies by the founding members.

An imported entry stays for 180 days without meeting the rules, so that
operators and maintainers have time to announce and claim. After that
only the rules count. An imported hierarchy is held by its maintainer as
if claimed on the genesis date, and is renewed like any other.

# 10. The Project's List Council

The project founds one list council for its lists, with a founding
period (UN-RFC 0054 section 19), and pins its groups in the reference
client:

- the council group `unseenet.lists@<fp>`;
- the list groups that succeed `unseenet.nodes`, `unseenet.hierarchies`
  and `unseenet.entrances`, and a new list group `unseenet.scribes`,
  whose `publishers` is the project's releases channel;
- the claims group `unseenet.lists.claims@<fp>` and the reports group
  `unseenet.lists.reports@<fp>`;
- its groups for proposals, talk, log and its room under
  `unseenet.council.*` (UN-RFC 0061 section 3).

The old groups get a last list each, saying where the lists went, and are
read until their last list is a year old. From then on the project key
has no part in the lists. The files in the repository become snapshots,
refreshed from the network before each release, so that a new client has
somewhere to start before it reaches the network. Changes go through the
rules, not pull requests.

The project also runs a scribe of its own (`unseenet-scribe`, beside one
of its nodes), so that the scribe list is not empty from the start. It
is one scribe like the others; anybody can run one with the same
software.

A GitHub issue form may stay as a front door: a node operator pastes an
announcement made by their own software, and a bridge posts it. The
bridge needs no key, since the announcement is already signed.

# 11. Rationale

- **Why no approvers?** Any key that approves is a key that can be
  stolen or pressured, and approvers chosen by an owner make the lists
  that owner's. The judgements left over are few - abuse, the rules
  themselves - and those get a public hearing that anybody can object to
  (UN-RFC 0061).
- **Why first claim for hierarchies?** It is the only rule that needs no
  judgement and that everybody can check. Commit and reveal stop anyone
  from seeing a claim and getting ahead of it; ripened keys, a limit per
  key and yearly renewal make squatting cost something and not last.
- **Why DNS for `dk.*` and `torproject.*`?** Those names already belong
  to somebody outside the network, and DNS is how the world says who.
  It is the same proof names use (UN-RFC 0019).
- **Why measure, not trust?** A node that answers, carries the network's
  own groups and is connected is useful to a new client, whoever runs
  it. A node that does not is not, whatever anybody promises.

# 12. Security Considerations

- **Many announced nodes.** One party can announce many nodes. They
  cost postage and must really answer and carry the network's groups;
  the list is a starting point, not the only one (UN-RFC 0055 section 5),
  and clients mix sources. A council MAY, by proposal, cap entries per
  operator key.
- **Squatting.** Commit and reveal, ripened keys, 3 per key and yearly
  renewal. A squatted name that harms people can be released by an
  urgent proposal.
- **DNS.** A domain's DNS can be changed by whoever controls the domain,
  and read wrongly by one replica; decisions depending on DNS follow the
  registrar's handling (UN-RFC 0054 section 12, item 2).
- **Stolen member key.** The thief can post a list that differs from the
  rules. Honest replicas repost theirs and the difference shows in the
  log; the member's own rules remove the key (UN-RFC 0054 section 12,
  item 1, applied to lists: a list no inputs explain).
- **Withholding.** A node can hide announcements or reports from a
  replica. Replicas read through several nodes; the grace of section 6.1
  is long on purpose.
- **Scribes.** A scribe can serve altered code, or withhold it. Clients
  and scribes use only files that match a valid signed release, so an
  altered file is simply not used; withholding is answered by there
  being many scribes. Git history is not signed: whoever clones a
  scribe's git mirror SHOULD check the tree of a release's tag against
  the release's signed source bundle. A replica's whole-file fetches
  cost Tor bandwidth; one file per scribe a week is the minimum, not a
  target.
- **Privacy.** Announcements and claims are public; that is the point.
  They reveal no more than the entry they ask for.

# 13. What Is Autonomous, and What Is Not Yet (Informative)

The lists follow from public data by rules every replica computes alike,
and no single key can change them. But while the list council's members
are the replicas of the founding project (UN-RFC 0054 section 22), one
hand runs the machinery that applies the rules - it cannot quietly
break them, since anybody can recompute the lists and the log shows any
difference, but it is one hand. The council is alive when others sit in
it.

# 14. Changes to Other Documents

- UN-RFC 0010 section 6: the project's node list is kept by the list
  council by the rules of section 6.1; the challenge and the GitHub
  process are replaced by announcements (UN-RFC 0055 section 5).
- UN-RFC 0018 sections 6.2 and 7: the root list is kept by the list
  council by the rules of section 6.2; requests are claims in its claims
  group; the criteria of section 7.2 are replaced by those rules.
- UN-RFC 0043 section 8.1: the list of known entrances is kept by the
  list council by the rules of section 6.3; entrances announce
  themselves (section 5.1).
- UN-RFC 0055 section 8: the rules left to this document are those of
  section 6.
- UN-RFC 0043 section 4.3: the entrance information gains `software`,
  as in UN-RFC 0011 (section 6.5).
- UN-RFC 0055 section 4: `unseenet.entrances.announce`,
  `unseenet.scribes.announce` and `unseenet.scribes` are infrastructure
  groups.
- UN-RFC 0000 section 6: the title of 0020 becomes "Lists Kept by
  Councils".

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
