```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0057                                              October 2026
Category: Standards Track
Status: Draft
Implemented: -
Updates: 0003, 0004, 0011, 0018, 0022, 0029, 0036, 0045

                     Unseenet: A People Directory
```

# Abstract

Today a person can only be found by someone who already knows their
name or fingerprint. This document adds a **people directory** that a
user joins only if they want to, by marking which parts of their
profile may be searched: name, tags such as `#abakion` or `#kvistgård`,
languages and contact details. An entry lives in a group bound to the
key; a small index, split into 256 buckets owned by a council, points
from hashed search terms to keys. The client fetches a bucket and
searches it itself, so no node learns what was searched for. Only keys
ripened to level 3 can be in the directory, entries expire after at
most a year unless renewed, and e-mail and phone numbers can be
verified by attestations, the newest of which wins. Nobody owns the
directory and nobody approves entries.

# 1. Motivation

Users want to find people they know without first being told an
address: a colleague, a friend from the scouts, the woman from
`dk.snak` who wrote about guinea pigs. Every network people know has a
search for people. What makes it hard here:

- Many Unseenet users must **not** be findable by name. Being reachable
  (a public profile, UN-RFC 0022) is not the same as being searchable.
- A search sent to a node tells the node who is being looked for. The
  query must stay on the user's device.
- Display names are not unique. Ten keys can call themselves "Andreas
  Lorensen"; impersonation is the main risk, not the search.
- Details go stale: people change phone numbers, lose keys and forget
  passphrases. A directory that never forgets fills with wrong
  information.
- Throwaway keys must not be able to fill the directory.
- At Usenet scale the directory has millions of entries; a client
  cannot fetch all of them.

Looking up a name one already knows (`@lorensen`, `sonia@lorensen`,
`andlo@lorensen.dk`) is UN-RFC 0019 and needs nothing new. Searching
the people one has already seen (authors in followed groups, contacts)
is done by the client on data it already holds. Neither is part of this
document; both are described for clients in section 10.1.

# 2. Terms

- **Entry**: what a user publishes about themselves in the directory
  (section 4).
- **Directory group**: the key-bound group `dir@<fp>` holding a key's
  entry (section 5).
- **Term**: a normalised word one can search for: a word of the name,
  a tag, a registered name or a contact detail (section 6.1).
- **Index**: the council groups `directory.bXX` that point from term
  hashes to keys (section 6).
- **Bucket**: one of the 256 index groups.
- **Verifier**: an issuer of `email` or `phone` attestations (section 8).

The key words MUST, SHOULD and MAY are as in RFC 2119.

# 3. What Does Not Change

- Profiles (UN-RFC 0022) stay as they are. The directory is a selection
  of the profile that the user chooses to make searchable; a user who
  never joins the directory is exactly as findable as before.
- The registrar (UN-RFC 0019, 0054) is not involved. It exists to make
  names unique, which needs a council and agreement. The directory has
  no uniqueness, so nobody needs to approve an entry. Results show a
  registered name when the key has one; that is the only link.
- Attestations (UN-RFC 0036) keep their format; two types are added
  (section 8).

# 4. The Entry

An entry is a JSON object in canonical JSON (UN-RFC 0004 section 3).
Every field but `v` and `type` is optional; the user chooses each one
(section 10.2).

| Field         | Type             | Meaning                                                    |
|---------------|------------------|------------------------------------------------------------|
| `v`           | integer          | `1`                                                        |
| `type`        | string           | `person`, `organisation`, `bot` or `service`               |
| `name`        | string           | Name to be found by, 1 to 64 characters                    |
| `about`       | string           | Short description, at most 280 characters, plain text      |
| `tags`        | array of strings | At most 10 tags, each as in UN-RFC 0052 section 3          |
| `languages`   | array of strings | At most 8 BCP 47 language tags (`da`, `en`, `pt-BR`)        |
| `areas`       | array of strings | At most 8 top-level hierarchies the user is part of (`dk`) |
| `contacts`    | array of objects | At most 8; section 4.1                                     |
| `org_tag`     | string           | Only for `organisation`: the tag its members carry (section 7) |
| `address`     | string           | Only for `organisation`: a postal address, at most 200 characters (section 7.2) |
| `groups`      | array of strings | At most 16 Group IDs of groups, feeds and sites the key stands behind (section 4.2) |
| `web`         | boolean          | `true`: may be shown and indexed on the open web (section 10.4). Default `false` |

Unknown fields MUST be preserved and ignored. An entry in canonical
JSON MUST NOT exceed 4096 octets. Text fields are shown as profile
text is shown (UN-RFC 0022 section 4.1), with control characters
replaced.

A place is given only as a tag (`#kvistgård`), never as coordinates or
an address. The one exception is an organisation's `address` (section
7.2): an association's or company's address is public already, a
person's is not.

## 4.1 Contacts

Each contact is an object:

| Field   | Type   | Meaning                                                         |
|---------|--------|-----------------------------------------------------------------|
| `kind`  | string | `email`, `phone`, or a link kind of UN-RFC 0022 section 4.2     |
| `value` | string | The contact, shown to everyone; normalised as in section 6.1    |
| `hash`  | string | The contact hash of section 6.2 instead of `value`              |

A contact has exactly one of `value` (**shown**) and `hash` (**findable
only**). A findable-only contact lets people who already know the
e-mail address or number find the key, without showing it to anyone
else.

## 4.2 Groups of an Entry

`groups` lets an entry point at the groups, feeds and sites behind it:
the Busshistorisk Selskab's discussion group, its feed and its site, or
a person's hobby site. Whoever finds the entry finds them too, without
having to know their names.

A pointer alone is a claim: anybody can list `dk.busser` in their
entry. A client therefore shows a listed group as **belonging to** the
entry only when the group points back, that is when

- the group is owned by the entry's own key, or
- the group's manifest has the field `org` (UN-RFC 0004 section 3.1),
  a string holding the entry key's fingerprint.

A listed group that does not point back is not shown at all. A group's
`org` field without a matching entry shows nothing either. So a
member who runs the association's site with their own key adds `org`
to its manifest, and the association adds the site to `groups`; neither
can do it alone.

A group in `groups` is shown to anyone who finds the entry, even if the
group itself is not listed for group search (#775); listing it in the
entry is the owner's choice to show it. A closed group listed in
`groups` reveals that it exists and who stands behind it, not its
content; clients SHOULD say so when such a group is added.

# 5. The Directory Group

A key's entry lives in the group it owns named `dir`:

```
dir@<fingerprint of the key>
```

It is a key-bound group (UN-RFC 0029). Its manifest (UN-RFC 0004
section 3) has:

- `name`: `dir`;
- `type`: `channel`, with no `posters`;
- `view`: `data` (UN-RFC 0008 section 3.1.1);
- `directory`: the entry of section 4;
- `expires`: at most **365 days** after the manifest's `Date`, as for a
  registered name (UN-RFC 0019 section 5.1) - shorter than other
  key-bound groups, because details go stale;
- `retention_days`: RECOMMENDED `7`.

Ordinary articles in a directory group mean nothing; clients MUST
ignore them. A client MUST NOT create the directory group of a key
until its user joins the directory.

A client accepts an entry if the manifest is valid, its `owner` is the
key, its `name` is `dir`, it has not expired, its `directory` field is
a valid entry, and the key has **level 3** or more (UN-RFC 0025 section
4). An entry of a key below level 3 is ignored until the key ripens.

## 5.1 Changing, Renewing and Leaving

There is one entry per key: the current manifest. A change is a new
manifest with a higher `serial`, which replaces the old one, so old
phone numbers do not pile up. The manifest's `Date` is the entry's
**updated** date, which clients show (section 10.3).

The owner's client renews the entry without asking while the key is in
use, RECOMMENDED when fewer than 60 days remain, together with its
index articles (section 6.3). A key that is never used again leaves the
directory by itself within a year.

A user leaves at once by posting a manifest without `directory` and
withdrawing their index articles (UN-RFC 0004 section 7). As for
profiles (UN-RFC 0022 section 5.3), copies others have kept cannot be
recalled, and clients MUST say so.

A key that is lost cannot leave; its entry stays until it expires. That
is why the lifetime is short, and why a newer verification of the same
contact wins (section 8.2). Recovery words (UN-RFC 0050) give back the
same key, so an entry restored that way simply continues.

# 6. The Index

## 6.1 Terms

The terms of an entry are:

- each word of `name`, and the whole `name`;
- for an organisation, each word of `address` of at least three
  letters (a street, a postcode, a town such as `skælskør`), as plain
  words like those of `name`;
- each tag in `tags`, written `#tag`;
- the key's registered name (UN-RFC 0019), written `@name`, if its
  certificate is valid;
- each contact, shown or findable only (section 6.2);
- for each shown contact of kind `web`, also its host as
  `web:<host>`, lower-cased, without `www.`, port or path, so that
  `https://www.busshistorisk.dk/om` is found by `busshistorisk.dk`.

A client given a search that looks like a domain or a web address
searches for both `web:<host>` and the registered name `@<host>`
(UN-RFC 0019 section 6.4).

A term is normalised before it is hashed: Unicode NFC, case-folded,
white space collapsed to one space and trimmed. An e-mail address is
lower-cased as a whole. A phone number is written in E.164
(`+4512345678`). An entry has at most 24 terms; a client leaves out
address words first, then whole-name and name-word terms, if there are
more.

`languages`, `areas` and `type` are not terms. They are filters,
applied by the client to the entries it has found (section 9).

## 6.2 Term Hashes and Contact Hashes

The hash of a term is

```
term-hash = first 16 octets of H( DS("UNSEENET-DIR-TERM-1") || term )
```

with `H` and `DS` as in UN-RFC 0003. Its first octet, written as two
lower-case hex digits `XX`, is the term's **bucket**.

A contact term is first made slow to guess:

```
contact-hash = Argon2id( password = term,
                         salt     = "UNSEENET-DIR-CONTACT-1",
                         t = 3, m = 65536 KiB, p = 1, 32 octets )
```

and the term that is then hashed as above is `contact:` followed by
`b64(contact-hash)`. The `hash` field of a
findable-only contact (section 4.1) is `b64(contact-hash)`.

The salt is the same for everyone, because a searcher must be able to
compute it. Argon2id makes each guess cost about a tenth of a second,
which protects e-mail addresses reasonably well. It does **not**
protect phone numbers: a country's numbers can be tried in a matter of
days on a few machines. Clients MUST say so (section 10.2).

## 6.3 The Index Groups

The index is the 256 groups

```
directory.b00@<fp> ... directory.bff@<fp>
```

one per bucket, each a council group (UN-RFC 0054 Part I) with the
same members, so that no single key - the project's included - owns
the directory. Since a council group's fingerprint follows from its
genesis, each bucket has its own; clients carry the list of the 256
Group IDs, as they carry the project's registrar (UN-RFC 0019 section
7.2). Their
manifests have:

- `type`: `open`;
- `min_ripe`: `3` (UN-RFC 0025 section 5), so that nodes refuse index
  articles from keys below level 3;
- `retention_days`: `400`;
- `view`: `data`.

An **index article** is posted by the entry's own key into each bucket
that holds one of its terms. It has `Content-Type: application/json`
and the canonical JSON body

```
{ "v": 1, "terms": ["<b64 term-hash>", ...], "expires": "<date>" }
```

where `terms` are the entry's term hashes in that bucket and `expires`
equals the `expires` of the key's directory group. A new index article
in a bucket carries `Supersedes` (UN-RFC 0042) naming the key's earlier
one there; only the newest counts. A client renewing or changing an
entry posts new index articles in the buckets it now uses and withdraws
those in buckets it no longer uses.

An index article is a pointer, never the entry. A client trusts it for
nothing: it fetches the entry and checks that the entry really has the
term (section 9). An index article that names terms its key's entry
does not have is ignored, and a node or another key cannot make a key
findable by a term it did not choose.

With 8 terms per entry, one million entries make about 31 000 index
articles of about 150 octets per bucket, some 5 MB. Splitting further
is an open issue (section 14).

# 7. Organisations

Tags are claims: anybody can write `#abakion`. An organisation can
confirm them:

1. the organisation has its own key with an entry of `type`
   `organisation` and an `org_tag`, say `abakion`;
2. it issues `member` attestations (UN-RFC 0036 section 4.2) to its
   members' keys;
3. a client that shows an entry with the tag `#abakion` and finds an
   accepted `member` attestation for that key from a key whose own
   entry has `org_tag` `abakion` shows the tag as **confirmed by**
   that organisation, with its name or registered name.

Two keys can both claim `org_tag` `abakion`. Clients therefore always
show *who* confirmed, never just "confirmed"; which organisation key is
the real one is the reader's judgement, helped by its registered name
and its own attestations.

## 7.1 An Organisation's Groups, Feeds and Sites

An organisation lists its groups, feeds and sites in `groups` (section
4.2). Searching for "busshistorisk" then finds the association and,
from its entry, its discussion group, feed and site, checked both ways.
Groups run by members with their own keys carry `org` in their
manifests.

## 7.2 Website and Address

People often know an organisation's website or address rather than its
exact name. An organisation can be found by both:

- **Website.** A shown contact of kind `web` is a term by its host
  (section 6.1). That is still a claim. The strongest proof is to
  register the domain itself as a name (UN-RFC 0019 section 6.4) with
  the DNS record `_unseenet.<domain>`: the registrar has then checked
  that whoever holds the domain holds the key, and a search for the
  domain finds `@<domain>` with its certificate. Without that, the
  website can carry a link proof (UN-RFC 0022 section 7), which a
  reader's client checks only when asked. Results show which of the
  two, if any, backs the website.
- **Address.** An organisation MAY give its postal address in
  `address`. Its words are terms (section 6.1), so a search for a town
  finds the organisations that give it. The address is the
  organisation's own statement; nothing checks it. Clients MUST NOT
  allow `address` in an entry of any other `type`, and SHOULD say,
  when it is added, that it is meant for an organisation's public
  address, not a home.

# 8. Verifying E-mail and Phone

## 8.1 Verifiers

A **verifier** is any key that checks that the holder of a key receives
mail at an address or messages at a number - typically by sending a
code - and then issues an attestation (UN-RFC 0036) of the type
`email` or `phone` (section 17). Its `value` is the `b64(contact-hash)`
of section 6.2, never the contact itself, so the attestation does not
reveal a findable-only contact. Its lifetime is at most 1 year.

The verifier sees the link between the key and the contact. Clients
MUST say so before a user asks a verifier (section 10.2). Anybody can
run a verifier; the project runs none for phone numbers, because text
messages cost money for each one sent.

An e-mail address on the user's own domain can instead be proven
without a verifier, with a link proof of UN-RFC 0022 section 7 and the
DNS, as domain names are in UN-RFC 0019 section 6.4.

## 8.2 The Newest Verification Wins

Of the accepted `email` or `phone` attestations from one issuer with
the same `value`, across all subjects, only the one with the latest
`issued` counts. The others are shown as **superseded by a newer
verification**, and a search for that contact finds the newer key
first.

So a user who has lost a key and verifies the same address or number
with a new key takes the contact over at once, even though the old
entry cannot be withdrawn. A verifier SHOULD also revoke the older
attestation (UN-RFC 0036 section 7) when it verifies the same contact
for another key.

Each verification carries its own date and expires by itself; clients
show both (section 10.3).

# 9. Searching

A client searches for a term as follows:

1. It normalises the term and computes its term hash (section 6), and
   from it the bucket.
2. It fetches the bucket's index articles it does not hold yet, from
   any node it uses, and keeps them (section 13).
3. It picks the keys whose newest, unexpired index article in that
   bucket lists the term hash.
4. It fetches their directory groups' manifests, many at once (UN-RFC
   0041), and accepts the entries of section 5.
5. It keeps only the entries that really have the term, then applies
   the filters the user chose (`type`, `languages`, `areas`).
6. It leaves out keys hidden by the spam reports the user follows
   (section 12).

A search for several terms intersects the results; each term may need
its own bucket.

The query never leaves the device. A node sees only which buckets a
client fetches, each of which covers 1/256 of all terms. A client
SHOULD fetch a few buckets more than it needs, chosen at random, and
MAY keep all 256 up to date in the background, after which its
searches reveal nothing.

Results are **not ranked** by followers, reactions or anything else
that would let others decide what one sees (as for feeds, UN-RFC
0034): exact matches of the whole name first, then the rest in
alphabetical order of `name`.

# 10. Clients

## 10.1 Before the Directory (Informative)

Clients SHOULD offer one "Find person" field that also

- opens a profile directly from `@name`, `name@holder`, `name@domain`
  or a fingerprint (UN-RFC 0019 section 8.3);
- searches, on the device, the people the user has already seen:
  authors in followed groups, contacts, followed identities and those
  who commented in the user's feed.

Neither sends the query anywhere.

## 10.2 Joining

The directory is a selection of the profile. In the profile editor
each field that can be in an entry gets a mark "include in the
directory", off by default; tags, languages and contacts for the
directory are added there too. The client builds the entry from the
marked fields, posts it and its index articles, and renews them
(section 5.1). The marks themselves are kept in the user's state in the
network (UN-RFC 0044), so that every device of the user builds the same
entry.

When a user joins, adds a tag or adds a contact, the client MUST say
plainly that

- the entry is public, and copies cannot be recalled;
- details combine: a name, `#employer` and `#town` together are close
  to an address;
- a findable-only phone number gives practically no protection
  (section 6.2);
- a verifier sees which key holds the address or number (section 8.1).

A client SHOULD remind the user of their recovery words (UN-RFC 0050)
when they join, since a lost key cannot leave the directory. A client
whose key is below level 3 says that the entry will appear once the key
has ripened.

## 10.3 Showing Results

For each result a client shows the name, `type`, a part of the
fingerprint, the registered name if any, the **updated** date, the
attestations it accepts - with who issued them, when, and whether they
are superseded (section 8.2) - and which tags are confirmed and by whom
(section 7). Look-alike display names MUST be easy to tell apart.
An entry's groups, feeds and sites that point back (section 4.2) are
shown with it, by title and kind, each opening the group, and an
organisation's website shows what backs it (section 7.2).

Clicking a `#tag` on a profile or in an entry SHOULD offer to search
the directory for it. Contacts and directory entries SHOULD be
reportable like posts (section 12).

## 10.4 The Open Web

An entry with `web` `true` MAY be shown by an entrance in read mode
(UN-RFC 0043) and indexed by search engines. Without it, an entrance in read mode
MUST NOT show the entry.
This is a separate choice from joining the directory.

## 10.5 Several Identities

Many users will have one key in the directory and another that nobody
should connect with them. A client MUST NOT suggest, show or compute a
link between keys - not from shared contacts, writing style, posting
times or anything else - and MUST NOT put a key's other identities in
its entry.

## 10.6 Finding One's Contacts

A client MAY offer to find the people in an address book on the
device. It computes the contact hashes there, fetches the buckets they
need - RECOMMENDED all 256, for a larger address book - and matches
locally. A client MUST NOT send an address book, or hashes made from
it, to a node, an entrance or anyone else. Phone numbers found this way
are only as private as section 6.2 says.

# 11. Other Directories

## 11.1 Closed Directories

An organisation or association that wants its members findable only by
each other uses a closed group (UN-RFC 0004) as its directory. Members
post their entries there as ordinary articles with the body of section
4; nodes see only ciphertext. No index is needed, because members can
read the whole group.

## 11.2 Hierarchy Directories

The maintainer of a hierarchy (UN-RFC 0018) MAY run a directory for it,
as 256 groups `<hierarchy>.directory.bXX` with the format of section
6.3, owned by the maintainer. A user whose entry names that hierarchy
in `areas` MAY post index articles there too. The maintainer moderates
these groups as any other in its hierarchy, including blocking keys
(UN-RFC 0018 section 5.4).

# 12. Abuse

- **Throwaway keys** cannot be in the directory: nodes refuse index
  articles below level 3 (section 6.3), and clients ignore entries below
  level 3 (section 5). Each index article also pays normal postage.
- **Spam reports** (UN-RFC 0045) apply to entries: a key report hides
  the key's entry, and a post report on an index article hides it.
  Clients use the issuers the user follows. The council's index
  manifests MAY name issuers for the directory, as a hierarchy does
  (UN-RFC 0045 section 7.1); the user can change them.
- **Impersonation** is answered by showing what can be trusted
  (section 10.3), not by anyone deciding who may use a name.
- **Harassment**: being found is the point of the directory, so the
  remedies are leaving it (section 5.1), blocking, and reports with the
  reason `harassment`.

# 13. Nodes

A node advertises whether it carries the index groups with the policy
field `directory` (boolean) of its node information (UN-RFC 0011
section 4). Directory groups (`dir@`) are carried like profile groups,
under the policy field `profiles` (UN-RFC 0022 section 10).

The index groups are **not** infrastructure groups that every node must
carry: the directory can grow large, and a node may choose it as it
chooses hierarchies. Nodes SHOULD carry them; the project's own nodes
do.

A node SHOULD keep only the newest index article of each key in each
bucket, and MAY drop superseded and expired ones at once.

# 14. Open Issues

- **Lifetime.** Is 365 days, as for registered names, short enough, or
  should entries live 180 days?
- **Splitting further.** At ten million entries a bucket is some 50 MB.
  A later version may let the council raise the number of buckets
  (12 bits, 4096 buckets) in its manifests, with clients posting to
  both sizes for a while.
- **Argon2id parameters** must be measured on phones and in the
  browser client (Pyodide) before this document is accepted.
- **Founding the council** of the index groups, how the list of the
  256 Group IDs reaches clients, and whether it should
  be the registrar's council (UN-RFC 0054) or a council of its own.

# 15. Rationale

- **Why opt in, field by field?** Being reachable is not being
  searchable. Many users need the first and must not have the second,
  and those who want to be found choose how: by name only, by
  `#employer`, by e-mail.
- **Why not in the registrar?** The registrar makes names unique and
  therefore needs a council to agree. Nothing in the directory is
  unique, so nothing needs agreeing. Putting it in the registrar would
  make the registrar larger and a more obvious target, and give the
  directory a central party it does not need.
- **Why an index of hashes instead of searching on the node?** A query
  sent to a node tells the node who is being looked for. Fetching a
  bucket tells it only 1/256 of that, and fetching all buckets tells it
  nothing.
- **Why keep the entry in the key's own group?** The index can then be
  small and can lie about nothing: every hit is checked against the
  entry its own key signed.
- **Why level 3?** Clients ripen to level 3 by default (UN-RFC 0025),
  so ordinary users get there without doing anything, while thousands
  of fake entries cost thousands of days of computing.
- **Why one entry per key and a short lifetime?** Stale numbers and
  addresses are worse than none. Lost keys cannot clean up after
  themselves; time and the newest verification do it for them.
- **Why verifications as attestations?** Anybody can run a verifier,
  and the reader sees who verified, as with every other attestation.
  Nothing new has to be trusted.
- **Why no ranking?** The same reason as for feeds: a ranking decides
  what people see, and in Unseenet only the reader decides that.

# 16. Security and Privacy Considerations

- **An entry is public.** Name, tags and shown contacts can be read by
  anyone, combined with each other and with what the key posts, and
  kept forever by whoever copied them. Clients warn (section 10.2).
- **Findable-only contacts** can be confirmed by anyone who guesses
  them. For e-mail, Argon2id makes guessing slow; for phone numbers it
  does not help enough (section 6.2).
- **Bucket fetches** leak 1/256 of a term to the node; random extra
  buckets and background fetching of all buckets reduce that to
  nothing (section 9). A node also sees *that* a client uses the
  directory.
- **Verifiers** learn which key holds an address or number, and an
  e-mail or text message reveals more to the mail or phone provider.
- **Linking identities** is the gravest risk for users who keep several
  keys. Clients never link them (section 10.5); users who need to stay
  apart should not reuse a contact, tag combination or name across
  keys, and clients SHOULD say so when the same contact is about to be
  added to a second identity's entry on the same device.
- **Lost keys** leave entries behind for up to a year; the newest
  verification wins (section 8.2), and results show the updated date.
- **Index articles cannot lie** about an entry, but a key can choose
  misleading terms for its own entry, such as someone else's name.
  That is impersonation, answered as in sections 10.3 and 12.

# 17. Changes to Other Documents

- UN-RFC 0029 section 2: `dir@<fp>` (directory entry, section 5) is
  added to the key-bound groups, with a lifetime of at most 365 days.
- UN-RFC 0022: the profile editor's directory marks (section 10.2);
  directory groups are carried under the policy field `profiles`.
- UN-RFC 0036 section 4.2: the types `email` and `phone`, `value` a
  contact hash (section 6.2), lifetime 1 year, and the rule of section
  8.2.
- UN-RFC 0018 section 9: `directory` is reserved for the index groups.
- UN-RFC 0011 section 4: the policy field `directory` (section 13).
- UN-RFC 0045: reports apply to directory entries and index articles
  (section 12).
- UN-RFC 0004 section 3.1: the manifest field `directory` (object, only
  in directory groups), and the manifest field `org` (string, a key
  fingerprint: the directory entry this group belongs to, section 4.2).
- UN-RFC 0003: the domain separations `UNSEENET-DIR-TERM-1` and
  `UNSEENET-DIR-CONTACT-1`.
- UN-RFC 0000 section 6: 0057 is added to the index.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
