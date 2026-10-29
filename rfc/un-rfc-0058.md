```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0058                                              October 2026
Category: Standards Track
Status: Draft
Implemented: -
Updates: 0004, 0011, 0018, 0023, 0035, 0052, 0055, 0057

                     Unseenet: Finding Groups
```

# Abstract

Today a group, feed or site can only be found by someone who already
knows its name, or who scrolls past it in the group list of the node
they happen to use. This document lets groups be found by what they say
about themselves: their name, title, description, charter, tags and
languages. A group's owner chooses whether it can be found (`listed`).
Ordinary groups are announced in a **group catalog** per hierarchy,
which every node carries as an infrastructure group, so a user can find
a group even when their own node does not carry it, and open it through
a node that does. Personal feeds and sites are found through the index
of the people directory (UN-RFC 0057). The client searches on the
device; no node learns what was searched for, nothing is ranked, and
no maintainer can make a group unfindable for readers who do not want
that.

# 1. Motivation

Users look for groups in a few typical ways:

- **By subject.** "Is there anything about buses?" The group may be
  called `dk.hobby.busser`, `alt.transport.bus-history` or something
  else entirely, and the user does not know which.
- **By who runs it.** "Does Busshistorisk Selskab have a group?" UN-RFC
  0057 covers this: an organisation's directory entry points at its
  groups.
- **On its own.** "That site about the history of buses by some bus
  enthusiast." The site's owner is not in the people directory and does
  not want to be. The site must be findable by what *it* says, not by
  who made it.

What makes it hard:

- A client learns which groups exist from its node, and since UN-RFC
  0055 a node carries only the hierarchies its operator chooses. A user
  on a node that carries only `alt.*` never learns that `dk.hobby.busser`
  exists. That splits the network into islands, and gives a node a quiet
  power over what its users can discover - not by removing anything, just
  by not carrying it.
- A search sent to a node tells the node what the user is interested in.
- Anybody can create a group with any name (UN-RFC 0004 section 1), so
  look-alikes of real groups are easy to make.
- Personal feeds and sites can number in the millions, one per user.
- Gatewayed groups (UN-RFC 0023) often have little more than a name.

Usenet solved the first problem with `newgroup` and `checkgroups`
control messages and the monthly "List of Active Newsgroups" in
`news.announce.newgroups`: one knew which groups existed even when one's
server did not carry them. This document is the signed, checkable
version of that, plus a search.

Searching the **content** of posts and pages is not part of this
document. A read-mode entrance (UN-RFC 0043, 0035) lets search engines
index public sites whose owners allow it.

# 2. Terms

- **Listed group**: a group whose current manifest has `listed` `true`
  (section 4.1).
- **Group catalog**: the infrastructure groups that hold listings
  (section 6).
- **Listing**: an article in a group catalog carrying a group's signed
  manifest (section 6.2).
- **Search fields**: the parts of a manifest a search looks at (section
  5).

The key words MUST, SHOULD and MAY are as in RFC 2119.

# 3. What Does Not Change

- A group that is not listed works exactly as before: `!group`
  references (UN-RFC 0032), invitations, links and directory entries
  (UN-RFC 0057 section 4.2) still lead to it. Not listed is not hidden.
- Nodes still carry only what their operators choose (UN-RFC 0055). The
  catalog tells clients what exists; it does not make anybody carry it.
- Hierarchy maintainers get no new power (section 11).
- The content of closed groups stays encrypted. A listed closed group
  shows only what its manifest already shows to every node.

# 4. Manifest Fields

These fields are added to the manifest (UN-RFC 0004 section 3.1). They
are all optional.

| Field       | Type             | Meaning                                                  |
|-------------|------------------|----------------------------------------------------------|
| `listed`    | boolean          | May the group be found by search (section 4.1)           |
| `languages` | array of strings | At most 8 BCP 47 language tags the group is written in (`da`, `en`) |
| `index`     | string           | `yes` or `no`: may the group's listing be shown on the open web (section 10.5). Default `no` |

`tags` (UN-RFC 0052 section 5) and `org` (UN-RFC 0057 section 4.2) are
used as they are.

## 4.1 `listed`

Without `listed`, a group is treated as:

| Group                                                    | Listed by default |
|----------------------------------------------------------|-------------------|
| `open`, `moderated` or `channel` ordinary group          | yes               |
| `closed` group                                           | no                |
| Personal feed and site (`feed@<fp>`, `site@<fp>`, UN-RFC 0029 section 2.1) | no |
| Other key-bound groups (inbox, profile, `dir@`, `ripe@`, `state@` …) | never |

An owner changes it by publishing a manifest with `listed` set. A
key-bound group other than a personal feed or site is never listed, even
if its manifest says `true`.

A personal feed or site is not listed by default for the same reason a
person is not in the directory by default: being reachable through
one's profile is not the same as being searchable (UN-RFC 0057 section
1). A user who wants their feed or site found sets `listed`; it does not
put them in the people directory, and a search that finds the site
shows the site, not the person (section 10.2).

A client MUST say, when a closed group is listed, that its name, title,
description, charter and tags become public, never its content.

## 4.2 Personal Feeds and Sites in Group Search

A personal feed or site has no hierarchy, so it is not announced in the
group catalog. When listed, it is found through the index of the people
directory instead (section 7).

# 5. Search Fields

A search looks at:

1. the **name** of the group, split into words (section 5.1);
2. `title`;
3. `description`;
4. `charter` (UN-RFC 0014), when it is not sealed;
5. `tags` (UN-RFC 0052 section 5);
6. `languages`, `type`, `view` and the hierarchy, as **filters**, not
   as words.

The owner key is not a search field. A search for a person goes to the
people directory (UN-RFC 0057).

## 5.1 Group Names

A group name is split into words at `.`, `-`, `_` and `+`, so
`usenet.dk.fritid.biler` gives `usenet`, `dk`, `fritid`, `biler`, and
`alt.transport.bus-history` gives `alt`, `transport`, `bus`, `history`.
A group with an empty manifest can therefore always be found by the
words of its name. The whole name is also matched, so a search for
`dk.hobby.busser` finds that group exactly.

## 5.2 Normalising and Matching

Both the search and the search fields are normalised: Unicode NFKC,
case-folded, and then **folded**: combining marks removed, and `æ` to
`ae`, `ø` to `oe`, `å` to `aa`, `ß` to `ss`. A match is checked on
the folded form, so `skaelskoer` finds `Skælskør`, `Skælskør` finds a
title written `Skaelskoer`, and `cafe` finds `café`.

A search word matches a field when it is a **part of a word** in it, so
`bus` finds `busser`, `bushistorie` and `turistbusser`. Several search
words must all match, each in any field; a word in quotes must match a
whole word. Tags are matched with or without `#`.

Word parts are what make free-text search useful for compound languages
such as Danish and German. It is possible only where the client holds
the whole set of search fields locally, which is why the catalog is
fetched per hierarchy (section 6.1). Personal feeds and sites are found
by whole words and word beginnings only (section 7).

# 6. The Group Catalog

## 6.1 Catalog Groups

The catalog is one group per top-level hierarchy:

```
unseenet.catalog.<hierarchy>
```

for

- every hierarchy in the root list (UN-RFC 0018 section 4.1), including
  the gateway hierarchies (`usenet`, `matrix`, `nostr` …, UN-RFC 0023);
- every regional hierarchy, that is every assigned ISO 3166-1 alpha-2
  code (UN-RFC 0018 section 4.2);

and one group `unseenet.catalog.other` for every other first name
component (unclaimed hierarchies). When a hierarchy enters the root
list, its catalog group is created; listings that were in `other` move
there as they are renewed (section 6.4).

The catalog groups are **open council groups** (UN-RFC 0054 Part I),
owned by the council that holds the root list and the list of known
nodes (UN-RFC 0055 section 8), so that no single key - the project's
included - decides what may be listed. Clients carry their Group IDs as
they carry the other infrastructure groups. Their manifests have:

- `type`: `open`;
- `min_ripe`: `3` (UN-RFC 0025 section 5);
- `retention_days`: `400`;
- `view`: `data`;
- a `min_pow` above ordinary groups, as for node announcements (UN-RFC
  0055 section 5.1).

They are **infrastructure groups** (UN-RFC 0055 section 4): every node
MUST carry all of them, whatever hierarchies it carries itself. That is
the point. A node that leaves out the catalog of `dk.*` hides that
`dk.*` exists from its users, which is exactly what UN-RFC 0055 forbids
for the node lists.

A catalog grows with the number of groups, not the number of users.
All of old Usenet's descriptions were a few megabytes. A listing is at
most 8 KiB and usually under 1 KiB, so a catalog of 100 000 groups -
the size of all of Usenet - is in the order of 100 MB, and the
catalogs of most hierarchies are a small fraction of that. Splitting large catalogs by
second-level name is an open issue (section 13).

## 6.2 A Listing

A listing is an article in the catalog group of the group's top-level
hierarchy, with

- `Author-Key`: the group's owner;
- `Subject: listing <Group ID>`;
- `Content-Type: application/json`;
- a canonical JSON body:

| Field      | Type      | Req. | Meaning                                                  |
|------------|-----------|------|----------------------------------------------------------|
| `v`        | integer   | yes  | `1`                                                      |
| `group`    | Group ID  | yes  | The listed group                                         |
| `manifest` | b64 string| yes  | The group's current manifest article, exactly as published (UN-RFC 0004 section 3) |
| `first`    | date      | no   | When the group was created, RFC 3339 UTC: the `Date` of its serial-1 manifest |

The listing carries the manifest itself, signed by the owner, so the
search fields need no second fetch and nobody can list a group under
words its owner did not write. A listing MUST NOT exceed 8 KiB; an
owner whose manifest is larger (a long charter) cannot list the group
until it is shorter, or seals the charter.

## 6.3 Checking a Listing

A node MUST reject, and a client MUST ignore, a listing

1. whose embedded manifest is not a valid manifest article (UN-RFC
   0002 section 5, UN-RFC 0004 section 4);
2. whose embedded manifest is not for `group`, or whose owner is not
   the listing's `Author-Key`;
3. whose group's first name component does not belong to this catalog
   group (section 6.1);
4. whose embedded manifest does not make the group listed (section
   4.1), or whose group is key-bound.

A client that also holds the group's manifest from a node uses the one
with the higher `serial` (UN-RFC 0004 section 3.2). A listing whose
manifest is older than the group's current one is out of date, not
false; the client shows the current manifest's fields.

## 6.4 Renewing and Leaving

- Only the newest listing per Group ID counts. A new listing carries
  `Supersedes` (UN-RFC 0042) naming the previous one, and a node MAY drop
  superseded listings at once.
- The owner's client posts a new listing when the group is created, when
  its manifest changes, and at least every 180 days. A listing older than
  400 days counts as gone, so dead groups drop out by themselves.
- An owner who sets `listed` to `false` withdraws the listing (UN-RFC
  0042). Others may have kept copies; clients say so.
- Gatewayed groups are owned by the gateway, which posts and renews
  their listings (UN-RFC 0023). A gateway SHOULD fill its groups'
  manifests from the source network - Usenet `LIST NEWSGROUPS`
  descriptions, Matrix room names and topics, NIP-29 group metadata -
  so that they have more than a name to be found by.

# 7. Personal Feeds and Sites

A listed personal feed or site is found through the index groups of the
people directory (UN-RFC 0057 section 6), which already split search
terms into 256 buckets and are carried by most nodes. This needs no
directory entry: the index only points from term hashes to groups.

A **group index article** is an index article (UN-RFC 0057 section
6.3) posted by the group's owner, whose body has one more field:

```
{ "v": 1, "group": "feed@<fp>", "terms": ["<b64 term-hash>", ...],
  "expires": "<date>" }
```

Its terms are, hashed as in UN-RFC 0057 section 6.2:

- each word of `title`, written `g:<word>`;
- each tag, written `g:#<tag>`;
- for each such word or tag of at least four letters, its first three
  letters, written `g:pre:<letters>`.

Words are normalised and folded as in section 5.2. A group index article
has at most 24 terms; tags are kept first. The `g:` prefix keeps group
terms apart from people's, so a search for a person never returns a
feed and the other way round.

Only the newest group index article per group and bucket counts
(Supersedes). The owner's client renews it when the title or tags
change and with the group (UN-RFC 0029 section 3), and its `expires`
is that of the group, so a personal feed or site that ends drops out of
search by itself. An index article for a group that is not listed is
ignored, as is one with terms the group's title and tags do not have.

This gives personal feeds and sites **whole words and word beginnings**
from their title and tags: `bus` finds `Bussernes historie` through
`g:pre:bus`. It does not search their descriptions and charters, and it
does not find `turistbusser` from `bus`. That is the price of scale:
there may be one feed and one site per user, millions in all, too many
to fetch whole as a catalog is fetched.

# 8. Searching

A client searches as follows:

1. **Ordinary groups.** It fetches the catalogs of the hierarchies the
   search covers - by default every catalog except those of the gateway
   hierarchies (UN-RFC 0023), which can be large and are searched when
   the user includes them - keeps them up to date in the background,
   and matches the search fields of section 5 locally. A client short
   of space or bandwidth (a phone, the browser client) MAY start with
   the hierarchies the user follows groups in and fetch the rest when a
   search asks for them.
2. **Personal feeds and sites.** For each search word it computes the
   group terms of section 7 (`g:<word>`, and `g:pre:` of its first three
   letters when it has three or more), fetches the buckets as UN-RFC 0057
   section 9 does, fetches the manifests of the groups found (UN-RFC
   0041) and keeps those whose title or tags really match.
3. **Groups behind directory entries** are found by the people search of
   UN-RFC 0057 and shown with their entry (UN-RFC 0057 section 4.2).
4. It applies the filters the user chose: kind (discussion, chat, feed,
   site), hierarchy, `languages`.
5. It hides what the spam reports and hierarchy blocks the user follows
   hide (section 11).

The query never leaves the device. A node learns which catalogs and
buckets a client fetches - which hierarchies it is interested in, as it
does today from what the client reads - and nothing about the words.

**No ranking.** Results are not ordered by members, posts, reactions or
anything else that lets others decide what one sees (UN-RFC 0034,
0057). Groups whose whole name or title equals the search come first,
then the rest grouped by hierarchy and in alphabetical order of name.

**Activity is shown, not ranked.** Whether a group is alive matters to
someone about to join. A client MAY show the date of a group's last
article when a node it uses carries the group and tells it, and MAY
offer to sort by it when the user asks; it MUST NOT make that the
default order.

# 9. Groups One's Node Does Not Carry

Finding a group is half; reading it is the other half. When the user
opens a group that no node they use carries, the client

1. finds, in the node announcements (UN-RFC 0055 section 5), the nodes
   whose `carries` covers the group, and checks them as UN-RFC 0055
   section 5.3 says;
2. offers to read the group there: by adding that node to the nodes the
   user uses, or for this group only;
3. says plainly: "Your node does not carry this group. It is read from
   <node name>." The user's own node learns nothing of it.

When no announced node carries the group, the client says so, and that
the group may still exist on nodes that do not announce themselves.

A node MAY offer to fetch a single group from a peer when a client asks
for it, as Usenet servers once fetched groups on demand. That tells the
node which group the user wants, so a client MUST NOT ask for it without
the user's choice.

# 10. Clients

## 10.1 One Search

Clients SHOULD offer one search that finds groups, feeds, sites and
people (UN-RFC 0057), with a filter by kind, rather than one search per
kind. A search that looks like a Group ID or `!group` reference opens
that group; one that looks like a name, a fingerprint or a domain goes
to the lookup of UN-RFC 0057 section 10.1 as well.

Search is a core function with the local API and the CLI (as every
client function is), so that every client searches the same way.

## 10.2 Showing Results

For each group a client shows its title, name, kind, hierarchy,
`languages`, tags and the start of its description, and:

- the short Group ID with the owner's fingerprint (UN-RFC 0004 section
  1). Groups with the same name and different owners MUST be easy to
  tell apart, and are shown next to each other;
- **endorsed by** the maintainer of its hierarchy when the hierarchy
  list endorses that Group ID (UN-RFC 0018 section 5.1);
- **belongs to** an organisation or person when the directory link of
  UN-RFC 0057 section 4.2 holds both ways - and nothing when it does
  not;
- "not carried by your node" when that is so (section 9);
- the date of its last article, when known (section 8).

The owner is shown as a name or a profile only if that key has made a
profile or directory entry public. A listed group never makes its owner
searchable as a person: finding the bus enthusiast's site does not find
the bus enthusiast.

**Content warnings.** A group whose tags (UN-RFC 0052 section 5)
carry a warning (UN-RFC 0052 section 4) is shown in results as posts
with that warning are, as the reader chose: blurred behind the warning,
or folded away with a count. As for posts, it is never left out
silently.

## 10.3 Creating and Editing a Group

- A client shows the `listed` choice with its default (section 4.1),
  and says what listing a closed group or a personal feed or site makes
  public.
- It **suggests tags** already used by listed groups in the same
  hierarchy, most used first, so that people end up writing `#busser`
  and not ten variants of it. The suggestion is made locally from the
  catalog. Counting tag use here is not ranking groups: it orders
  suggestions for the owner, never results for a reader.
- It offers `languages`, filled in from the user's own languages.
- It posts and renews the listing (section 6.4) without the user
  having to think about it.

## 10.4 New Groups

The catalog doubles as the old `news.announce.newgroups`: a client MAY
offer a view of **new groups** - listings with a `first` date in the
last 30 days whose Group ID the client has not seen in the catalog
before - newest first, filtered like a search. A Group ID shown once as
new is not shown as new again, so re-listing a group does not put it
back at the top.

## 10.5 The Open Web

A group with `index` `yes` (section 4) MAY have its listing shown by an
entrance in read mode (UN-RFC 0043) and indexed by search engines. This
is a separate choice from `listed`: `listed` is about being found inside
Unseenet, `index` about the open web. The field is the same `index` as
a site's (UN-RFC 0035 section 9.3), now defined for every group; for a
site it still also covers its pages.

# 11. Abuse and Maintainers

- **Fake and spam listings** cost postage at a raised `min_pow`, need a
  key at level 3, and can only list a group the listing's own key owns
  (section 6.3). A key can still create many groups with spam
  descriptions; those are answered as all spam is:
- **Spam reports** (UN-RFC 0045) apply to listings and to the listed
  groups. A report on a group or its owner key hides the group from
  search for the readers who follow that issuer.
- **Hierarchy maintainers** get no new power. They act through what they
  already have: the issuers they name for their hierarchy (UN-RFC 0045
  section 7.1) and the identities they block (UN-RFC 0018 section 5.4).
  A client hides from search what those hide, by default, and the reader
  can turn either off, as for posts. A maintainer can therefore never
  make a group unfindable for readers who do not want that, and cannot
  remove a listing; only its owner can withdraw it.
- **Look-alikes** are answered by showing what can be trusted (section
  10.2): the owner's fingerprint, endorsements, and directory links that
  hold both ways - not by anyone deciding who may use a name.

# 12. Nodes

- A node MUST carry the catalog groups (section 6.1) as infrastructure
  groups, and MUST check listings as section 6.3 says.
- A node SHOULD keep only the newest listing per Group ID, and MAY drop
  superseded and expired listings at once.
- Group index articles (section 7) are carried with the directory index
  groups, under the policy field `directory` (UN-RFC 0057 section 13).
- A node MAY offer single groups on demand (section 9) and says so with
  the policy field `on_demand` (boolean) of its node information (UN-RFC
  0011 section 4).

# 13. Open Issues

- **Splitting large catalogs.** `alt` and `usenet` may outgrow one
  catalog. A later version may let the council split a hierarchy's
  catalog by second-level name (`unseenet.catalog.usenet.dk`) and say so
  in the root list.
- **Word beginnings for feeds and sites.** Three-letter prefixes give
  many hits per bucket; they are checked against manifests, so the cost
  is fetching, not wrong results. To be measured with real numbers, as
  UN-RFC 0057's buckets are.
- **Renewal period.** Is 180 days, with 400 days to expire, right for
  groups that are quiet but alive?
- **Founding the council** of the catalog groups, together with that of
  the node list and the root list (UN-RFC 0055 section 8, #703).

# 14. Rationale

- **Why a catalog every node carries?** Because the islands of section
  1 are worse than the cost. A node may choose what it carries; it
  should not choose what its users can know exists. Usenet had the same
  answer in `checkgroups`.
- **Why one catalog per hierarchy, not buckets?** A client that holds a
  hierarchy's whole catalog can match word parts (`bus` in
  `turistbusser`) and search descriptions and charters. Buckets of term
  hashes match only whole terms. Groups are few enough - Usenet's were
  around 100 000 - to fetch whole. Per hierarchy also matches how nodes
  choose what to carry (UN-RFC 0055) and how hierarchies are run.
- **Why feeds and sites through the people directory's index?** They
  have no hierarchy and may be millions. The index already exists, is
  already split for that scale and already keeps queries on the device;
  a third mechanism would add nothing.
- **Why does the listing carry the whole manifest?** Then a listing can
  only say what the owner signed, nodes can check it without fetching
  the group, and a client can search without a second round trip.
- **Why `listed` defaults to yes for open groups?** An open group is
  made to be read by anyone; being findable is what most owners expect.
  Personal feeds and sites are tied to a person, so they follow the
  directory's rule: not searchable unless chosen.
- **Why no ranking?** The same reason as for feeds and the directory: a
  ranking decides what people see, and in Unseenet only the reader
  decides that. Activity is shown because it is a fact about the group,
  not an opinion about it.
- **Why no new power for maintainers?** A maintainer who could take
  groups out of the catalog could hide a rival group without deleting
  anything. Blocks and report issuers already exist, are public, and
  each reader can turn them off.

# 15. Security and Privacy Considerations

- **What a node learns.** Which catalogs and buckets a client fetches,
  and which groups it then reads - as today. Never the search words.
  A client that keeps all catalogs up to date in the background reveals
  nothing by searching.
- **Owners.** Every manifest names its owner key; listing a group does
  not reveal more about the owner than the group already does. Clients
  never link a listed group's owner to a person beyond what that key has
  made public (section 10.2), and never across keys (UN-RFC 0057 section
  10.5).
- **Closed groups.** Listing one publishes its name, title, description,
  charter, tags and languages to everyone, not only to nodes. Clients
  say so (section 4.1); owners who want the charter private seal it.
- **Reading elsewhere.** Opening a group through another node (section
  9) tells that node what the user reads, as reading on one's own node
  does. Asking a node to fetch a group on demand tells it what the user
  wants before they read it.
- **Look-alikes.** Anybody can create a group with any name and words
  (UN-RFC 0004 section 1). Search makes them easier to come across, so
  results must show what can be trusted (section 10.2).

# 16. Changes to Other Documents

- UN-RFC 0004 section 3.1: the manifest fields `listed`, `languages`
  and `index` (section 4).
- UN-RFC 0035 section 9.3: `index` is defined for every group (section
  10.5); for sites it also covers their pages.
- UN-RFC 0052 section 5: group tags are search fields (section 5).
- UN-RFC 0055 section 4: the catalog groups `unseenet.catalog.*` are
  added to the infrastructure groups.
- UN-RFC 0057 section 6.3: group index articles (section 7), with the
  field `group` and `g:` terms.
- UN-RFC 0018 section 9: the names `unseenet.catalog.*` are reserved
  for the catalog groups.
- UN-RFC 0011 section 4: the policy field `on_demand` (section 12).
- UN-RFC 0023: gateways post and renew their groups' listings and fill
  their manifests from the source network (section 6.4).
- UN-RFC 0000 section 6: 0058 is added to the index.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
