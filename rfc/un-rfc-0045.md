```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0045                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0018, 0025, 0029, 0040

                    Unseenet: Spam Reports
```

# Abstract

Ripening (UN-RFC 0025) makes every key cost real time, so that bans and
blocks against a key mean something again. This document gives nodes and
readers a way to act on spam together without giving anybody power over
anybody else. Any key can be an **issuer**: it publishes signed reports,
naming posts or keys and why, in a group of its own. Nobody has to listen.
A node operator chooses which issuers its node follows; a hierarchy
maintainer names issuers that readers of its hierarchy follow by default;
every reader can follow others or none. A report never removes anything
from a node or a reader that does not follow its issuer. It is NoCeM
(Usenet, 1990s) on Unseenet's terms.

# 1. Motivation

A spam campaign posts many articles, each valid on its own: postage paid,
a ripe enough key, a unique Message-ID. Postage and ripening make it
costly, not impossible. Today every node operator and every reader has to
spot each spam article alone, and a group owner can only ban in its own
group (UN-RFC 0004).

Usenet answered this with NoCeM: third parties published signed notices
("these articles are spam"), and each server and each reader decided whose
notices to act on. That fits Unseenet: no central list, no authority, and
the choice of whom to trust stays with each node and each reader.

# 2. Terms

Issuer
: A key that publishes reports. Any key may be one.

Report
: A signed statement by an issuer that a post or a key is spam or abuse,
  with a reason.

Following
: Acting on an issuer's reports. A node follows the issuers its operator
  names (section 6); a reader follows the issuers its hierarchy names and
  those it chooses (section 7).

# 3. The Reports Group

An issuer publishes in the key-bound group (UN-RFC 0029)

```
reports@<fingerprint of the issuer's key>
```

a `channel` (UN-RFC 0004) in which only the issuer posts. Its manifest MAY
say what the issuer reports and how to reach it:

| Field       | Type    | Meaning                                                  |
|-------------|---------|----------------------------------------------------------|
| `policy`    | string  | What this issuer reports and how, up to 2000 characters  |
| `contact`   | string  | Where to object to a report (an inbox, a URL)             |
| `automatic` | boolean | Reports are made by a program (e.g. duplicate detection, #123), not read by a person |

The group lives, is renewed and expires like the issuer's other key-bound
groups. Its manifest article is at most 4 KiB (UN-RFC 0040 section 9).

# 4. Reports

A report article in `reports@` has `Content-Type: application/json` and a
body in the canonical JSON of UN-RFC 0004:

```
{
  "v": 1,
  "posts": [ {"id": "<message-id>", "group": "<group-id>", "reason": "spam"} ],
  "keys":  [ {"key": "ed25519:...", "reason": "spam", "until": "2027-01-20T00:00:00Z"} ],
  "note":  "a wave of the same text from 300 new keys"
}
```

- `posts`: articles. `group` is where the issuer saw it.
- `keys`: identities. `until` (RFC 3339) is REQUIRED for a key and at most
  365 days after the article's `Date`; a key report without it, or with a
  later one, is ignored.
- `reason`, for each entry: `spam`, `flood`, `phishing`, `malware`,
  `harassment` (threats and harassment of people), `illegal` or `other`.
  A reason is why the issuer *sanctions* a post or a key; what a post
  merely contains (profanity, adult content) is a content label, with
  rules of its own that never sanction (UN-RFC 0053).
- `note`: optional, up to 200 characters, for people.

An article holds at most 1000 entries in all. A post report needs no
expiry: it ends when the post does. An issuer withdraws a report by
withdrawing the article that holds it (UN-RFC 0004 section 7); it can post
the remaining entries again.

An issuer MUST NOT report a sealed post in an inbox (UN-RFC 0009): only
the recipient can read it, and a public report would tell everyone that
this inbox received it. A recipient deals with such posts in its own
client (UN-RFC 0025 section 3.5).

An issuer can only judge what it can read. In closed groups (UN-RFC 0004)
nodes see only ciphertext, so reports there come from members, typically
the owner or the moderators, and nodes act on them by Message-ID as
anywhere else.

# 5. What a Report Does

Nothing, by itself. A node or a reader acts on a report only when it
follows its issuer (sections 6 and 7). What it then does is its own
choice and is never required of anyone else:

- for a post: not serve it to readers, not forward it, or delete it;
- for a key: refuse its new articles, or raise the postage it must pay,
  until `until` (UN-RFC 0025 section 6: anything that raises the price of
  posting is a local choice).

A report MUST NOT lower anything for anybody: no report makes a post or a
key cheaper or more trusted.

# 6. Nodes

A node follows the issuers in its configuration, each with what to do:

```toml
[[follow_reports]]
issuer = "ed25519:..."
posts  = "hide"      # "hide" (not served, not forwarded) or "delete"
keys   = "surcharge" # "refuse", "surcharge" (+6 bits) or "ignore"
```

A node follows nobody unless its operator says so. It reads the reports
of the issuers it follows from their `reports@` groups, which it carries
like other key-bound groups, and applies them as they arrive, also to
articles that arrive later. A report about an article the node does not
hold is kept until the report's article expires, in case it comes.

A node MUST NOT act on reports from issuers it does not follow, MUST NOT
present its choices to peers as properties of a post or a key, and MAY
publish which issuers it follows in its node information (UN-RFC 0011).

## 6.1 Looking Up and Expiry

A reader may ask its node which report articles name the posts and keys
it shows, with `XUN-MARKS` (UN-RFC 0053 section 7.1), instead of fetching
whole `reports@` channels. A report of a post counts while the post is
carried; an article whose posts are all gone and whose key reports have
all passed their `until` no longer counts, and a node MAY drop it
(UN-RFC 0053 section 7.2). An issuer SHOULD keep each article's posts
within one top-level hierarchy.

# 7. Readers

## 7.1 Issuers Named by a Hierarchy

A hierarchy maintainer MAY list issuers in its entry of the hierarchy list
(UN-RFC 0018 section 5.1):

| Field            | Type             | Meaning                              |
|------------------|------------------|--------------------------------------|
| `report_issuers` | list of keys     | Issuers its readers follow by default, at most 16 |

A client follows these issuers **for the groups of that hierarchy only**,
by default. The reader can turn any of them off. A maintainer further down
(a delegated sub-hierarchy) adds to the list of those above; it cannot
remove theirs, but the reader can.

## 7.2 Issuers a Reader Chooses

A reader can follow any issuer, for all groups, and stop following any
issuer, also one its hierarchy names. A client keeps this list where it
keeps the reader's other settings (UN-RFC 0007; in the network once
UN-RFC 0044, a draft, is accepted).

## 7.3 Showing

A client that hides a post because of a report SHOULD show that something
is hidden and why, in the place of the post: "Hidden by
*issuer*: spam" with a way to show it anyway, and a way to stop following
that issuer. It SHOULD NOT hide silently. Posts from the reader's
contacts and the reader's own posts are never hidden by reports.

## 7.4 Reporting

The client's report action (#74) MAY offer to send a report to an issuer
the reader follows, as a private post: to the inbox its manifest's
`contact` names when that is an inbox (typically a team inbox, UN-RFC
0047, so that those who read reports read them in their everyday
clients), otherwise to the issuer's personal inbox. The issuer decides
whether to publish it; the reporter's key is not in the published
report.

## 7.5 Issuers Named by a Group's Owner

A group's owner MAY list issuers in the group's manifest (UN-RFC 0004
section 4):

| Field            | Type         | Meaning                                       |
|------------------|--------------|-----------------------------------------------|
| `report_issuers` | list of keys | Issuers its readers follow by default, at most 16 |

A client follows these issuers **for that group only**, by default, in
addition to those its hierarchy names (section 7.1). The reader can turn
any of them off as in section 7.2; turning an issuer off turns it off
wherever it was named for the reader. An inbox (UN-RFC 0009) and a
`reports@` group have no `report_issuers`; a node refuses a manifest
with more than 16, with a key listed twice, or with a key that is not
one.

This is for groups whose hierarchy names no issuers, or none that suit
them - in `alt.*`, which nobody governs, it is the only default there
is. Nodes do not act on it: a node follows the issuers its operator
names (section 6), never those a group's owner names.

# 8. Automatic Issuers

A node or a program MAY issue reports automatically, for example from
detecting near-identical articles from many keys (#123). Its `reports@`
manifest MUST then set `automatic: true`, and clients SHOULD say so when
they show a hidden post. Following an automatic issuer is a choice like
any other.

# 9. Rationale

**Why a group per issuer, not one shared group.** A shared report group
would be one place to flood, and whoever owns it would decide who may
report. With `reports@<fp>` every issuer is just a key, found and followed
like any other channel, and nobody stands between issuers and readers.

**Why reports about keys, not only posts.** A spammer posts many articles
from the same key until it is noticed. Reporting the key once stops the
rest, and with ripening (UN-RFC 0025) a reported key is a real loss. Key
reports expire within a year so that a mistake, or a stolen key given
back, does not follow its owner forever.

**Why a group's owner may name issuers.** Whoever owns a group already
decides who may post and who is banned there. Naming issuers lets the owner
lean on shared work instead of banning each throwaway key alone, and readers
keep the last word, as for a hierarchy's defaults. Nodes are left out on
purpose: what a node carries stays its operator's choice.

**Why hierarchy defaults.** A new reader who has to find issuers before
spam goes away will see spam. The maintainer of `dk.*` already sets the
list of its hierarchy (UN-RFC 0018); naming issuers for it is the same
kind of default, limited to that hierarchy, and every reader can turn it
off. No issuer is named by the project for the whole network.

**Why reports never lower costs.** The rule of UN-RFC 0025 section 6: if
reports could make posting cheaper, whoever issues them would hold the
key to the network.

# 10. Security and Privacy Considerations

- **Silencing by report.** An issuer could report legitimate posts to
  silence someone. Nobody has to follow it; hidden posts are shown as
  hidden, with the issuer and the reason, one click from being shown; and
  readers and operators can stop following an issuer at once.
- **Pressure on issuers.** An issuer named by many hierarchies could be
  pressured to report someone. That hides posts only for those who follow
  it, and only in the hierarchies that name it.
- **Which issuers a reader follows** is as visible to its node as which
  groups it reads. Clients SHOULD fetch `reports@` groups together with
  others, over Tor like everything else.
- **Reports name posts and keys in public.** That is their purpose. They
  never name a reporter (section 7.4) and never name sealed private posts
  (section 4).
- **Floods of reports.** A report article pays postage and, from its
  issuer's key, ripening like any other; a node follows only issuers its
  operator chose, so others cost it nothing beyond carrying their group.

# 11. Changes to Other Documents

- UN-RFC 0029 section 2: `reports@<fp>`, "Spam reports", is a key-bound
  group (this document, section 3).
- UN-RFC 0040 section 9: the manifest article of `reports@` is at most
  4 KiB.
- UN-RFC 0018 section 5.1: a hierarchy's entry may hold `report_issuers`
  (section 7.1).
- UN-RFC 0004 section 4: a group's manifest may hold `report_issuers`
  (section 7.5).
- UN-RFC 0025 section 6: following reports is one of the local choices
  that may raise a key's price.

# 12. Open Issues

- Whether report articles should be batched by hour or day, to keep the
  number of articles in a busy issuer's group down.
- How long a node keeps reports about articles it never received.
- The exact form of automatic reports from near-duplicate detection
  (#123), for example reporting a fingerprint instead of each Message-ID.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
