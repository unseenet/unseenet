```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0020                                              October 2026
Category: Standards Track
Status: Draft
Implemented: unseenet main (unreleased); partly - the node list (sections 5.1, 5.3, 6.1, 7, 8): replicas measure, report and post it, and apply `list` decisions (6.7); a list council and its import are made with `unseenet council create --lists` (9), and clients follow the node list's `moved_to` (10); hierarchy claims and the root list (5.2, 6.2): replicas keep it, a list is added with `unseenet council add-list` and clients and nodes follow the root list's `moved_to`; the entrance list (5.1, 6.3): replicas fetch entrances over Tor, check their files against the publisher's signed release and post the list, a list is added with `unseenet council add-list ... entrances` and an entrance announced with `unseenet council announce-entrance`, and DNS answers are decided by the replicas together (6.2, 7); entrances naming their key (UN-RFC 0043 4.3, in unseenet-entrance), the council as maintainer of `unseenet`, scribes (6.4) and the sources list (6.8) follow (#56, #861)
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
  after a top-level domain (`dk`, `com`) only to whoever its registry
  names in DNS;
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
| `lists`   | object   | yes  | Which list group holds which list, e.g. `{"nodes": …, "root": …, "entrances": …, "scribes": …, "sources": …}` |
| `claims`  | Group ID | yes  | The open claims group for hierarchy claims (section 5.2) |
| `reports` | Group ID | yes  | Where replicas post measurements (section 7)         |
| `announce` | object  | for `entrances` | Where entries announce themselves, by kind, e.g. `{"entrances": …, "gateways": …}`: an `open` council group of the council (section 5.1); `gateways` is the gateway directory (UN-RFC 0038 section 6.1) |
| `min_software` | object | no | The lowest version of each implementation that may be listed, e.g. `{"unseenet": "0.7.2"}` (section 6.5) |
| `publishers` | array of Group IDs | for `scribes`, `sources` | The releases channels (UN-RFC 0062) whose releases a listed scribe keeps, and whose files the sources list says where to find (section 6.8) |
| `import`  | string   | no   | `sha256:` and the hex SHA-256 of the import's body (section 9); genesis only |
| `imports` | object   | no   | For a list added later, its import by kind, e.g. `{"root": "sha256:…"}`; set by the `manifest` proposal that adds the list (section 9) |

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
themselves in the open group the council's `announce` names for
`entrances`, so that the council, not the project key, owns the door.
The announcement has `Subject: entrance <name>`, `Content-Type:
application/json`, is signed with the entrance's key, and has a
canonical JSON body:

| Field         | Req.        | Meaning                                          |
|---------------|-------------|--------------------------------------------------|
| `v`           | yes         | `1`                                              |
| `publisher`   | yes         | The releases channel (UN-RFC 0062) whose web client it serves |
| `date`        | yes         | The article's `Date`, RFC 3339 in UTC            |
| `url`         | one of both | Its open-web address, `https://host/`            |
| `onion`       | one of both | Its onion address, `<56 base32>.onion`           |
| `name`, `operator`, `contact`, `description` | no | As in UN-RFC 0043 section 8.1 |

By announcing, the operator promises UN-RFC 0043 section 5. The
entrance's information (UN-RFC 0043 section 4.3) names the same key in
`key`, so that nobody can announce somebody else's entrance. Any
publisher may be named: the council does not choose which clients are
served, only checks that what is served is what its publisher signed;
a council that names `publishers` lists only entrances serving one of
them. Scribes announce themselves in
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
| `title`   | string   | for `claim` | Up to 64 characters (the root list's title, UN-RFC 0018 section 4.1) |
| `charter` | string   | no   | Up to 200 characters (the root list's description) |
| `maintainer` | key string | for `change` | A new maintainer key            |

The claiming key MUST be ripened to the council's `min_level` (UN-RFC
0025), and a key holds at most 3 top-level hierarchies. A name is
lowercase letters, digits and hyphens, at most 32 characters. The commit
is made as a name's (UN-RFC 0054 section 8), with the domain separation
`UNSEENET-HIERARCHY-COMMIT-1` in place of the names', so that a commit
for a hierarchy can never count as one for a name.

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
4. on the last day a replica reached it, at least one replica found it
   connected and complete (UN-RFC 0021 sections 5 and 6), counted over
   the groups it carries.

Its list entry takes `address` and `addresses` from the announcement
(UN-RFC 0064 section 4). Replicas reach it on its `onion:` address: while
`onion` is the only hiding transport, other addresses are listed as the
node gives them but not measured, and a node whose `address` is not an
`onion:` address is not listed. A `test:` address (UN-RFC 0064 section
2.2) is never listed.

It leaves the list when one of these stops holding, with one grace: a
listed node is only taken off for items 3 and 4 when, for each of the
last 10 completed days, at least one replica reported on it and none
reached it connected and complete (section 7, UN-RFC 0021 section 7). A
day no replica reported on does not count either way. It comes back by
itself when the rules hold again. Of the entries that meet the rules,
those already listed come first when a limit applies (at most 200,
UN-RFC 0010 section 2, and any per-operator limit, section 12).

## 6.2 Hierarchies

The root list follows from the claims, in the order of their commits:

- **Reserved names** are never granted by a claim: those of UN-RFC 0018
  section 9 and any a passed proposal adds.
- **`unseenet`** has the list council itself as maintainer. Its
  hierarchy list is posted by the replicas, and endorsing or retiring a
  group in it is a proposal with a hearing (UN-RFC 0061); every node
  carries the endorsed groups (UN-RFC 0055 section 4.1). (Until the root
  list can name a council as maintainer, `unseenet` keeps its imported
  entry, held as any imported hierarchy.)
- **A name equal to a top-level domain** (`dk`, `com`, `microsoft`) goes
  only to a claim whose key the TLD's registry names in DNS, at
  `_unseenet.nic.<tld>`, as for names (UN-RFC 0019 section 4.5). Such a
  grant does not expire by time; it is checked again monthly and lapses
  when the record has been gone for 30 days. Other names - also those
  equal to the first label of a registered domain, which nearly every
  word is - go to the first claim; a name that belongs to somebody
  outside the network (`torproject`) is protected by being reserved, by
  a `reserve` decision (section 6.7).
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

Decisions that depend on DNS are made by the replicas together, not by
one replica's answer. Every day each replica asks DNS for every
top-level domain that a revealed claim waits on and every hierarchy
granted by DNS, and puts what it found in its report (`dns`, section 7).
A record **names** a key on a day when more than half of the members
that asked that day found it. A `claim` or `change` that needs DNS is
decided by the first day, from the day of its reveal, on which any
member asked; until then it waits, and so does every later claim on the
name. A grant by DNS lapses when no day in the last 30 found its record
naming the maintainer. Only settled days count - the root list is for
the day before yesterday - so every replica decides alike.

## 6.3 Entrances

A replica reaches an entrance over Tor, at its onion address if it has
one, else at its open-web address. It counts as reached when its
`/.well-known/unseenet-entrance` names the announced key, and as
**serving** version `v` when, in addition, its `version.json` says `v`,
`v` is a release post of the announced publisher (UN-RFC 0043 section
7.2) - read by the replica from the network, signed by the channel's
owner or a poster it lists - and every file the post names has the
SHA-256 the post gives. The report says so in `served` (section 7).

A **good day** for an entrance is a completed UTC day on which at least
one replica found it serving a release no older than the publisher's
newest release that had been out for 7 days (`release_days`) by the end
of that day: an entrance must follow its publisher, but has a week to do
so.

An entrance is on the entrance list when

1. its announcement is current (section 5.1);
2. its publisher has at least one release, and is one of the council's
   `publishers` if the council names any;
3. its software is not below the minimum (section 6.5); and
4. each of the last 14 completed UTC days (`entrance_days`) was a good
   day - all of them, not 5 of 7 as for a node, since a visitor trusts
   an entrance with the code they run.

A listed entrance leaves after `grace_days` reported days without a good
day, as a node does (section 6.1), and only a decision of the council
removes it otherwise (section 6.7). At most `max_per_operator` per
operator, and at most 200, those already listed first. The entrance
list is a JSON object `{"v": 1, "updated": "...", "entrances": [...]}`;
each entry has the fields of UN-RFC 0043 section 8.1 and the entrance's
`key` and `publisher`, which clients that do not know them ignore.
Imported entries (section 9), which have no key, stay for `import_days`
unless the same entrance (by `url` or `onion`) is listed by the rules,
and a decision removes one by its `url` or `onion`.

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

## 6.7 List Decisions

The `list` change of a proposal (UN-RFC 0061 section 4) is an object
with exactly one of:

| Change      | Value                                    | Effect                                   |
|-------------|------------------------------------------|------------------------------------------|
| `remove`    | `{"list": <kind>, "entry": <key or name>}` | The entry is not on that list, whatever the rules say |
| `restore`   | the same                                 | Undoes a `remove`; the rules decide again |
| `reserve`   | a top-level name                         | Adds it to the reserved names (section 6.2) |
| `unreserve` | a top-level name                         | Takes it off them again                  |
| `set`       | `{<parameter>: <number>, ...}`           | Changes parameters of this section       |
| `sources`   | `{"files": [...], "index": [...]}`       | Replaces the release sources (section 6.8) |

`<kind>` is `nodes`, `root`, `entrances`, `scribes` or `sources`; the entry is the
entry's key, for `root` the top-level name, and for an imported
entrance its `url` or `onion`. The parameters, with
their values until a decision sets them, and the values allowed:

| Parameter          | Value | Allowed | Meaning                                   |
|--------------------|-------|---------|-------------------------------------------|
| `announce_days`    | 30    | 7-90    | How long an announcement is current (5.1) |
| `window_days`      | 7     | 3-30    | The days item 3 of section 6.1 looks at   |
| `need_days`        | 5     | 1-30    | On how many of them a replica must have reached it |
| `grace_days`       | 10    | 3-60    | Days down before a listed entry leaves    |
| `import_days`      | 180   | 0-730   | How long an imported entry stays (section 9) |
| `max_per_operator` | 0     | 0-200   | Entries per operator key; 0 is no limit (section 12) |
| `entrance_days`    | 14    | 3-60    | Good days in a row before an entrance is listed (6.3) |
| `release_days`     | 7     | 1-60    | How soon an entrance must serve a new release (6.3) |

Decisions apply in the order of the day they apply on and then of the
proposal's id. `min_software` is a field of the council manifest and is
changed by a `manifest` proposal.

## 6.8 Release Sources

Release files and package indexes live on outside sites - GitHub, PyPI,
GitLab, Codeberg. If one is taken down, blocked or used against the
network, somebody must be able to say where to look instead, and that
must not be one key. The **sources list** says, for the publishers in
the council's `publishers`, where their release files and the package
index are:

```
{"v": 1, "updated": "council <seq> day <date>",
 "files": ["https://github.com/unseenet/{repo}/releases/download/{tag}/{name}", ...],
 "index": ["https://pypi.org/simple/", ...]}
```

`files` and `index` are as in UN-RFC 0062 section 6.3: templates with
`{repo}`, `{tag}` and `{name}`, in the order to try, each `https://` or
`http://` to an onion address, at most 16 of each. Several sites at once
are the point: when one falls away, the next is already there.

Nothing is measured. The list is the import (section 9) with the passed
`sources` decisions applied (section 6.7), the newest last; every
replica computes and posts it as any list (section 8). A source is added
or taken away only by a proposal with a hearing (UN-RFC 0061). When a
source is taken down, an urgent proposal (UN-RFC 0061 section 7) puts
another in its place within three days; until then the scribes and the
mirroring entrances carry the releases (UN-RFC 0062 section 6.3).

The list grants nothing over *what* is installed: every file must match
the publisher's signed checksums (UN-RFC 0062 section 4), wherever it
came from. It only decides where clients and servers look - which is
why it is the council's and not one key's: a stolen key that sent every
update past a site that logs who fetches would undo what fetching over
Tor protects (UN-RFC 0062 section 6.1).

# 7. Measurements

Each replica posts one `report <date>` article per UTC day in the
`reports` group:

| Field     | Type          | Req. | Meaning                                   |
|-----------|---------------|------|-------------------------------------------|
| `v`       | integer       | yes  | `1`                                       |
| `date`    | string        | yes  | The UTC day, `YYYY-MM-DD`                 |
| `reached` | array of keys | yes  | Node, entrance and scribe keys that answered and authenticated |
| `missed`  | array of keys | yes  | Those that did not                        |
| `disconnected` | array of keys | no | Reached but not connected (UN-RFC 0021 section 7) |
| `incomplete` | array of keys | no | Connected but not complete (UN-RFC 0021 section 7) |
| `software` | object       | no   | For keys it reached, the software they stated (section 6.5) |
| `files`   | array         | no   | Whole files fetched from scribes: `{"scribe": key, "file": path, "ok": bool}` |
| `served`  | object        | no   | For entrances it reached, the signed version it found each serving unchanged (section 6.3) |
| `dns`     | object        | no   | For each top-level domain it asked that day (section 6.2), the keys `_unseenet.nic.<tld>` named, at most 8; `[]` when it named none. At most 64 domains |

A report is about a completed UTC day and is posted on that day or the
next; of one replica's reports for one day, the newest counts. Only the
reports of the council's members count. Where replicas heard different
software from one entry on one day, the highest version counts, so that
one replica cannot take an entry off by misreporting it.

Replicas see the network from different places and may disagree for a
day. Rule 6.1 item 3 needs one replica to have reached a node, and the
grace takes a node off only when none has, so one replica with a bad
connection can neither keep a dead node on nor take a live one off.

**Canaries.** A replica judges "connected" and "complete" as UN-RFC 0021
sections 5 and 6 say, with its own canaries: once a day it posts a
canary (UN-RFC 0021 section 4) to each node it reached, to that node
alone, in the council's `reports` group - a channel council group, so
only members post there - and the next day reads which canaries of the
day before each node has. The nodes it judges among are the announced
nodes that answered it, not only the listed ones. A node is complete
when it lists every group carried by the network that its `carries`
names, and every one of the network's own groups (UN-RFC 0055
section 4).

After 3 days with no replica reaching a listed node, the replica whose
key sorts first among those reporting sends a notice to the inbox of the
node's operator, if its announcement names one.

# 8. Computing and Publishing the Lists

Each list is a function of the inputs of section 5 up to the end of a
UTC day, and of the council's own list of the day before, which says
who keeps a place under the grace of section 6.1. Every replica computes it once a day, and posts it to its list
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

A list council starts from the lists as they are. The import is an
article in the council group with `Subject: import` whose body is
canonical JSON `{"v": 1, "nodes": <node list>, ...}` - the lists by kind
as they are (for the project: `nodes.json`, `hierarchies.json` and the
entrance list). The genesis manifest's `import` names it by the SHA-256
of its body, not by Message-ID: the group exists only once the genesis
counts, so the import is posted after it, and any founding member's copy
with that body is the import.

A list the council takes on later is added by a `manifest` proposal
(UN-RFC 0061) that sets `lists` with the new list group - a council
group of the same members - and `imports` with the hash of that list's
import, posted in the council group by a member. Its import is held as
the genesis import is, from the date of the manifest that added it.

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
  and `unseenet.entrances`, and new list groups `unseenet.scribes` and
  `unseenet.sources`, whose `publishers` is the project's releases
  channel; the import of `sources` is the reference client's built-in
  sources (GitHub and PyPI);
- the claims group `unseenet.lists.claims@<fp>` and the reports group
  `unseenet.lists.reports@<fp>`;
- its groups for proposals, talk, log and its room under
  `unseenet.council.*` (UN-RFC 0061 section 3).

The project's own list of release sources in its releases channel
(UN-RFC 0062 section 6.3) ends with a last list, signed by the project
key, whose `moved_to` names the list council: from then on clients and
servers take the council's sources list, and the project key no longer
says where releases are.

The old groups get a last manifest each, signed by the project key, with
`moved_to` (the list council's Group ID) and `moved_on`, as the
project's registrar moved (UN-RFC 0054 section 14). A client that reads
it takes the council's list from then on - the newest a member posted -
and keeps the old group's list only until the council has one. From then on the project key
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
- **Why DNS for `dk.*`, and only for top-level domains?** A TLD already
  belongs to its registry, and DNS is how the world says who. It is the
  same proof names use (UN-RFC 0019). Almost every word is the first
  label of some registered domain, so asking DNS for those would leave
  no free names; the few that matter, such as `torproject`, are
  reserved instead.
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
  and read wrongly by one replica; decisions depending on DNS go by what
  most replicas found (section 6.2), so one wrong answer changes nothing.
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
  as in UN-RFC 0011 (section 6.5), and `key`, the key it announces
  itself with (section 5.1).
- UN-RFC 0043 section 8.1: entries gain `key` and `publisher`.
- UN-RFC 0055 section 4: `unseenet.scribes.announce` and
  `unseenet.scribes` are infrastructure groups.
- UN-RFC 0062 section 6.3: the council's sources list (section 6.8)
  comes first, for the publishers it names, and replaces the project
  key's list; a list of sources gains `moved_to`.
- UN-RFC 0055 section 4: `unseenet.sources` is an infrastructure group.
- UN-RFC 0000 section 6: the title of 0020 becomes "Lists Kept by
  Councils".

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
