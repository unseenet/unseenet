```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0020                                              October 2026
Category: Standards Track
Status: Draft
Implemented: -
Updates: 0010, 0018

          Unseenet: Keeping Lists from Inside the Network
```

# Abstract

Node lists (UN-RFC 0010) and root lists (UN-RFC 0018) already travel in
the network as signed articles, and clients trust only the keys they
have pinned. But the *process* behind the project's lists does not:
requests are GitHub issues, checks run in GitHub Actions, the lists are
files in a repository, and the key that posts them is a GitHub secret.
This document moves that process into Unseenet. Requests are sent to an
inbox and signed by the key they concern; replicas check them
automatically; people with **approver keys** post signed, numbered
**decisions** in a public **ledger**; and every replica computes the
lists from the ledger and publishes the same result. The lists and the
way clients read them do not change. Anybody can see who decided what,
when, and why, without asking GitHub.

# 1. Motivation

The project's lists depend on one company's service in four ways:

1. A node operator or a would-be hierarchy maintainer must have a GitHub
   account, which links the request to a person outside the network.
   UN-RFC 0018 section 7.1 offers the project's inbox as an alternative,
   but nothing processes it.
2. The checks (reaching a node over Tor, checking a signature over a
   challenge) run only in GitHub Actions.
3. The source of truth is `nodes.json` and `hierarchies.json` in the
   repository. If the repository or the organization is lost, so is the
   process, and the history of decisions lives in a place that can be
   force-pushed.
4. The key that posts the lists is stored by GitHub.

UN-RFC 0019 section 6.8 has shown that a service can run as replicas
that need nothing but the network. This document uses the same pattern
for the project's lists, and adds the one thing the registrar does not
need: a person who decides, in public.

# 2. Terms

- **Steward:** the publisher of one or more lists (UN-RFC 0010 section 3)
  whose content is computed from a ledger. The project is a steward.
- **Ledger:** a channel group owned by the steward, holding decisions,
  check results and health reports (section 4).
- **Request:** a signed inbox article asking for a change (section 5).
- **Replica:** a program with its own key that checks requests, reports
  node health and publishes lists. Replica keys are posters of the
  ledger and of the list groups.
- **Approver:** a key that may post decisions (section 7). Approvers are
  people; replicas are not approvers.
- **Decision:** a numbered, signed statement that a request is accepted
  or refused, or that something is changed or removed.

# 3. What Does Not Change

- The formats of node lists (UN-RFC 0010 section 2), root lists and
  hierarchy lists (UN-RFC 0018 sections 4 and 5).
- How clients and nodes read and pin lists (UN-RFC 0010 section 4,
  UN-RFC 0018 section 6). **Clients need no change** for this document:
  they still read the newest valid list from the pinned list group.
- What a root list or an endorsement means, and what it cannot do
  (UN-RFC 0018 section 3).
- Hierarchy lists are still published by each hierarchy's maintainer,
  not by the steward.

# 4. The Ledger

A steward has one ledger: a channel group (UN-RFC 0004) owned by the
steward's owner key. Its manifest has, besides the usual fields:

| Field       | Type          | Req. | Meaning                                        |
|-------------|---------------|------|------------------------------------------------|
| `requests`  | Group ID      | yes  | The request inbox (section 5)                  |
| `approvers` | array of keys | yes  | Keys that may post decisions (section 7)       |
| `quorum`    | integer       | no   | Approvals needed for a decision; default `1`   |
| `lists`     | object        | yes  | Which list group holds which list, e.g. `{"nodes": "unseenet.nodes@…", "root": "unseenet.hierarchies@…"}` |

The manifest's `posters` are the replica keys. Approvers are posters as
well, so that nodes accept their decisions under the channel rule.

Every article in the ledger has `Content-Type: application/json`, a
canonical JSON body (UN-RFC 0003), and one of these subjects:

| Subject             | Body                         | Posted by  | Section |
|---------------------|------------------------------|------------|---------|
| `decision <seq>`    | a decision                   | approver   | 7       |
| `check <Message-ID>`| a check result for a request | replica    | 6       |
| `health <date>`     | a health report for a day    | replica    | 9       |

Articles with another subject, or by another author, are ignored.

The ledger's `retention_days` SHOULD be `0` (keep forever) on nodes that
support it, and replicas SHOULD post the whole decision chain again,
unchanged, when it would otherwise expire (section 7.3).

# 5. Requests

## 5.1 Sending

A request is an inbox article (UN-RFC 0009) to the group named in the
ledger's `requests`, whose inner article has
`Content-Type: application/json`, a `Sender-Key` and `Sender-Signature`,
a `Reply-Inbox`, and a canonical JSON body with `v` = `1` and an
`action`:

| Action              | Further fields                              | `Sender-Key` MUST be |
|---------------------|---------------------------------------------|----------------------|
| `node-add`          | `address`, `name`, `description`, `operator` (optional) | the node key |
| `node-change`       | as `node-add`; changes a listed node        | the node key         |
| `node-remove`       | `node_key`                                  | the node key, or its listed operator |
| `hierarchy-claim`   | `name`, `list`, `title`, `charter`, `existing` (optional) | the maintainer key |
| `hierarchy-change`  | `name`, and the fields to change, or `maintainer` (a new key) | the current maintainer key |
| `hierarchy-release` | `name`                                      | the current maintainer key |
| `complaint`         | `about` (a name or key), `text`             | any key              |

Field limits are those of the list entries the request would create
(UN-RFC 0010 section 2, UN-RFC 0018 section 4.1). `charter` is at most
2000 characters; its first 200 become the description.

Because the request is signed by the key it concerns, it replaces the
challenges of UN-RFC 0010 section 6 and UN-RFC 0018 section 7.1: the
`Sender-Signature` already shows that the request comes from whoever
holds the key. A request whose `Date` is more than 7 days old when a
replica first sees it is refused as stale.

The request inbox SHOULD have a `min_pow` of at least 20 (UN-RFC 0006).

## 5.2 Front Doors (Informative)

Any program can send a request. The reference node offers
`unseenet-node --request-listing`, signing with the node key; the
reference client offers hierarchy requests in its command palette.

A web form, such as a GitHub issue form, can act as a front door: the
user pastes a request made by their own software, and a bridge posts it
to the inbox unchanged. The bridge needs no key, because the request is
already signed and anybody may post to an inbox. A front door has no
authority; it only carries requests.

# 6. Checks

Every replica checks each request it sees and posts the result as a
`check` article:

| Field     | Type    | Req. | Meaning                                        |
|-----------|---------|------|------------------------------------------------|
| `v`       | integer | yes  | `1`                                            |
| `request` | string  | yes  | The request's Message-ID                       |
| `ok`      | boolean | yes  | Whether every check passed                     |
| `notes`   | array of strings | yes | What was checked and found, for people  |

A replica checks that the request is well-formed and signed by the right
key (section 5.1), and:

- **for nodes:** that the address answers over Tor as an Unseenet node
  and authenticates with the node key (UN-RFC 0016);
- **for hierarchies:** that the name is valid and not reserved as "never
  granted" (UN-RFC 0018 section 9), that the fingerprint in `list` is the
  maintainer's, and that the list group exists with that owner.

A replica also replies to the request's `Reply-Inbox` saying that the
request has been received and checked. Only the replica whose key sorts
first among those that posted a check for the request sends this reply.

Checks inform the approvers; they decide nothing.

# 7. Decisions

## 7.1 Format

A decision is the body of a `decision <seq>` article:

| Field      | Type    | Req. | Meaning                                         |
|------------|---------|------|-------------------------------------------------|
| `v`        | integer | yes  | `1`                                             |
| `seq`      | integer | yes  | 1 for the first decision, then one more each time |
| `prev`     | string  | if `seq` > 1 | SHA-256, base32, of the canonical body of decision `seq - 1` |
| `action`   | string  | yes  | `accept`, `refuse`, `set`, `remove` or `import` |
| `request`  | string  | for `accept`, `refuse` | The request's Message-ID   |
| `entry`    | object  | for `set` | A node or root list entry, as it shall be |
| `key`      | string  | for `remove` | `node:<node key>` or `hierarchy:<name>` |
| `lists`    | object  | for `import` | Complete lists to start from (section 10) |
| `reason`   | string  | yes  | Why, at most 1000 characters, shown to everybody |

- `accept` applies the request as it was sent.
- `refuse` changes nothing; it records the answer and the reason.
- `set` and `remove` let an approver correct or remove an entry without a
  request, for example after a complaint or when a maintainer has not
  published a list for 180 days (UN-RFC 0018 section 7.2).

## 7.2 Which Decisions Count

A decision counts when:

1. its author is in the ledger manifest's `approvers` at the decision's
   `Date`;
2. its `seq` is one more than the last counted decision, and its `prev`
   is the hash of that decision (`seq` 1 has no `prev`); and
3. if `quorum` is more than 1, at least `quorum` different approvers have
   posted the same body for this `seq`.

Two counting candidates with the same `seq` but different bodies are a
**fork**. A reader that sees one MUST stop applying decisions from that
`seq` on, and replicas MUST stop publishing new lists and post a notice
to the steward's announcement channel. A fork means an approver key is
stolen or misused; only the owner can resolve it, by removing the key
from `approvers` and posting nothing that counts at that `seq` from the
removed key.

A gap (decision `seq + 1` seen, `seq` not) means a node is withholding
or has lost a decision. Replicas MUST NOT skip it; they fetch from other
nodes and wait.

## 7.3 The Chain Is the History

Because each decision names the hash of the one before, nobody can
change or remove a decision without breaking every later one. Anybody
who reads the ledger can see every grant, refusal and removal, by which
approver key, and why. This is the public record that UN-RFC 0018
section 7.2 asks for.

Replicas SHOULD keep the whole chain and post any decision again,
unchanged except for its `Date`, when the original would expire. A
reposted decision counts as the same decision because its body is the
same.

# 8. Computing the Lists

A list is a function of the counted decisions and the health reports:

1. Start from the lists in the `import` decision (`seq` 1).
2. Apply every later counted decision in order of `seq`.
3. For the node list, leave out nodes that are **down** (section 9).

Every replica computes the lists this way and posts each list to its list
group when it changes, and again at least monthly (UN-RFC 0010 section
3). The list's `updated` field is `ledger <seq>`, the last decision
applied. Replicas that have seen the same ledger post identical lists,
so it does not matter whose post is newest.

A replica that finds a newer post in a list group that differs from its
own result for the same ledger MUST post its own result again, and SHOULD
warn in the steward's announcement channel: either the replicas have not
yet seen the same ledger, or a replica key is misused.

# 9. Node Health

Each replica tries to reach every accepted node at least once a day and
posts one `health <date>` article per UTC day:

| Field     | Type    | Req. | Meaning                                    |
|-----------|---------|------|--------------------------------------------|
| `v`       | integer | yes  | `1`                                        |
| `date`    | string  | yes  | The UTC day, `YYYY-MM-DD`                  |
| `reached` | array of keys | yes | Node keys that answered and authenticated |
| `missed`  | array of keys | yes | Node keys that did not                     |

A node is **down** when, for each of the last 10 completed UTC days, at
least one replica reported on it and none reported it reached. A node
that has been down for 180 days in a row is treated as removed and must
be requested again. A node that answers again before that is listed
again without a new request.

After 3 days with no replica reaching a node, the replica whose key
sorts first among those reporting sends a notice to the inbox of the
node's `operator`, if one is listed.

Replicas see the network from different places and may disagree for a
day. The rule above only lists a node as down when no replica has
reached it, so one replica with a bad connection cannot take a node off
the list.

# 10. The Project's Steward

The project is the steward of the lists in UN-RFC 0010 section 6 and
UN-RFC 0018 section 6.2:

- ledger `unseenet.ledger@ph5fc5hop5232qsz`, owned by the project key;
- request inbox: the Group ID in the ledger manifest's `requests`;
- lists: `unseenet.nodes@ph5fc5hop5232qsz` and
  `unseenet.hierarchies@ph5fc5hop5232qsz`, as before.

The project starts the ledger with an `import` decision holding the
current `nodes.json` and `hierarchies.json`. From then on, the files in
the repository are snapshots, refreshed from the network before each
release, so that a new client has something to start with before it
can read the ledger. Changes go through decisions, not pull requests.

The project's replicas run as at least two programs on machines that are
not the project's nodes, like the registrar's (UN-RFC 0019 section 7.2).
The project's approver keys are held by people, offline, and are not the
project's owner key. The project's discussion of requests stays public,
in `unseenet.admin` or in a linked issue.

The project's own `checkgroups` list and release announcements are not
covered by this document.

# 11. Signature Purposes

No new purposes. The purposes `UNSEENET-NODE-CLAIM-1` (UN-RFC 0010) and
`UNSEENET-HIERARCHY-CLAIM-1` (UN-RFC 0018) are no longer needed by the
project's process; they remain defined for other stewards.

# 12. Rationale

- **Why keep a person in the loop?** Whether `games.*` should go to this
  maintainer, or whether a charter is a real purpose (UN-RFC 0018
  section 7.2), is a judgement. A replica can check facts; it should not
  pretend to decide. Moving the process into the network changes where
  decisions are made and recorded, not who makes them.
- **Does anybody know who holds a hierarchy?** Yes, better than before.
  The holder is the maintainer key in the root list, which is the only
  definition of ownership that can be checked. The ledger shows who
  granted it, when and why. Whether a person is behind the key is theirs
  to say, for example with a registered name (UN-RFC 0019); pseudonymous
  maintainers are allowed, as pseudonymous posters are.
- **Why a hash chain?** A list says what is true now; the chain says how
  it came to be, and makes rewriting history visible. A repository's
  history can be force-pushed; a chain spread over many nodes cannot be
  changed quietly.
- **Why not let replicas post decisions?** Replicas run unattended and
  their keys are online. Only offline keys held by people should be able
  to change who is listed. Health is the exception, and it never removes
  a node for good on the word of one replica (section 9).
- **Why do clients not read the ledger?** They could, but they do not
  need to: the lists are what they use, and keeping them unchanged means
  this document can be adopted without a client release. A client MAY
  read the ledger to show users why a hierarchy is held by whom.

# 13. Security Considerations

- **Stolen approver key.** The thief can accept or refuse anything until
  the owner removes the key from `approvers`; every decision is public
  and names the key. Later decisions can undo the damage, but cannot
  delete the record. A `quorum` of 2 or more makes one stolen key
  harmless.
- **Stolen replica key.** The thief can post a list that differs from
  the ledger, with a late `Date`, so that clients take it. Honest
  replicas notice and repost (section 8), but a forged `Date` far in the
  future wins on clients until the owner removes the key. This is the
  same risk as a stolen poster key today (UN-RFC 0010 section 7), spread
  over more keys; owners SHOULD keep few replicas and watch the
  warnings. A future version MAY let clients prefer the list with the
  highest `ledger` sequence over the newest `Date`.
- **Withheld decisions.** A node can withhold the ledger or part of it;
  section 7.2 makes replicas wait rather than skip, and they read through
  several nodes.
- **Spam requests.** Postage on the inbox, and approvers ignoring
  requests whose checks failed.
- **Privacy.** Requests travel over Tor and need no outside account.
  Requests and checks are public in the ledger, and so is the
  `Sender-Key` of every request; that is the point. A request does not
  reveal more than the list entry it asks for would.

# 14. Changes to Other Documents

- UN-RFC 0010 section 6: "kept in the project's repository and changed
  by pull request" is replaced by: kept in the project's ledger (UN-RFC
  0020); the challenge is replaced by a request signed by the node key;
  "removed" after 10 days becomes "down" as in UN-RFC 0020 section 9.
- UN-RFC 0018 section 6.2: as for UN-RFC 0010 section 6.
- UN-RFC 0018 section 7.1: requests are sent as in UN-RFC 0020 section
  5; a GitHub issue is one possible front door.
- UN-RFC 0000 section 6: 0020 is added to the index.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
