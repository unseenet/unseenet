```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0036                                              October 2026
Category: Standards Track
Status: Draft
Implemented: -
Updates: 0000, 0003, 0004, 0008, 0012, 0017, 0022, 0029

                       Unseenet: Attestations
```

# Abstract

An identity is a key. It can say things about itself in a profile
(UN-RFC 0022), and a registrar or a name holder can give it a name
(UN-RFC 0019), but nobody else can vouch for it. This document lets
one key, the **issuer**, make a small signed statement about another
key, the **subject**: that the issuer has met its holder, that the
holder is a member of the issuer, that the issuer has checked one of
its links, or, for issuers that check an eID, that the holder is a
real person, an adult or has a given legal name. Such an
**attestation** is published only by its subject, in a key-bound
group of its own, `attest@<fingerprint>`, so that nobody can hang
statements on somebody else's key. Every client decides for itself
which issuers it trusts and for what. There is no global trust, no
trust through chains of keys, and nothing else in the network
depends on attestations.

# 1. Motivation

A signature proves that two articles come from the same key. In open
groups such as `dk.snak` that is often enough, and it is all that a
person who needs to stay anonymous should ever give away. But many
people want others to be able to trust what they post, link to and
agree on: that this key belongs to the Andreas who maintains a project
on GitHub, to a member of the association that runs `dk.*`, to
somebody a friend has met, or at least to a real adult and not a bot
(unseenet #215).

Unseenet already has part of this. Names come from certificates
(UN-RFC 0019), and a domain name ties a key to a domain through DNS.
Link proofs (UN-RFC 0022 section 7) let a key show that it controls an
account elsewhere. Both are about what a key controls. What is missing
is a way for **somebody else** to vouch for a key, as OpenPGP's
signatures on keys were meant to.

The OpenPGP web of trust is a warning as much as a model. Published
signatures on keys draw a map of who has met whom. Anybody could add
signatures to anybody's key on the keyservers, until keys were flooded
with them and the keyservers were closed. Trust computed through chains
of keys was hard to understand and easy to get wrong. And a single
"verified" mark, as on large platforms, gives power to whoever hands
it out. This document tries to keep the useful part and leave those
out.

# 2. Terms

- **Attestation:** the JSON object of section 4.
- **Issuer:** the key that signs an attestation.
- **Subject:** the key an attestation is about.
- **Type:** what an attestation states (section 4.2).
- **Attestation group:** the group `attest@<fingerprint of a key>`
  (section 6.1). It holds the attestations about its owner that the
  owner has published, and the revocations the owner has made as an
  issuer.
- **Trusted issuer:** an issuer the user has chosen to trust for one
  or more types (section 8).
- **eID issuer:** an issuer that checks an electronic identity outside
  the network before it issues (section 10).

# 3. What Attestations Do Not Do

- They do not change whether an article is valid, who wrote it, what
  postage it needs or what standing its key has (UN-RFC 0025).
- They do not give names. Names come only from certificates (UN-RFC
  0019); a `legal-name` attestation is never shown as a name
  (section 9).
- They do not decide who may join, post in or moderate a group. Groups
  that require an attestation are left for a later document
  (section 13).
- Every identity can do everything without attestations. Clients MUST
  NOT treat an identity without attestations as less trustworthy than
  one with them, beyond showing the attestations that exist.
- They are not legal signatures. An Ed25519 signature on Unseenet
  shows other users who said what; it is not a qualified electronic
  signature in the sense of eIDAS, and an attestation does not make it
  one.

# 4. The Attestation Object

## 4.1 Format

An attestation is a JSON object in canonical JSON (UN-RFC 0004
section 3):

| Field     | Type       | Req. | Meaning                                              |
|-----------|------------|------|------------------------------------------------------|
| `v`       | integer    | yes  | `1`                                                  |
| `type`    | string     | yes  | What is stated (section 4.2)                         |
| `value`   | string     | no   | As the type requires, at most 256 characters         |
| `subject` | key string | yes  | The key the attestation is about                     |
| `issuer`  | key string | yes  | The key that signs it; MUST differ from `subject`    |
| `issued`  | date       | yes  | RFC 3339 UTC                                         |
| `expires` | date       | yes  | RFC 3339 UTC, within the type's lifetime (4.2)       |
| `serial`  | integer    | yes  | Increases each time the issuer issues this type for this subject |
| `publish` | boolean    | no   | `false`: the subject may show it only privately (section 6.3). Default `true` |
| `sig`     | signature  | yes  | By `issuer`, purpose `UNSEENET-ATTEST-1`, over the canonical JSON without `sig` |

Unknown fields MUST be preserved and ignored. An attestation in
canonical JSON MUST NOT exceed 1024 octets.

`value`, where a type has one, is plain text: clients show it as
profile text is shown (UN-RFC 0022 section 4.1), with control
characters replaced.

## 4.2 Types

| Type         | States                                                       | `value`                         | Lifetime  |
|--------------|--------------------------------------------------------------|---------------------------------|-----------|
| `met`        | The issuer has met the holder of `subject` and compared the full fingerprint with them | `in-person` (default) or `video` | 2 years |
| `member`     | The holder is a member of the issuer, an organisation         | Optional role, at most 64 characters (`member`, `board`, `employee`) | 2 years |
| `link`       | The issuer has checked the link proof (UN-RFC 0022 section 7) of one link | `<kind> <value>` of the link, as in UN-RFC 0022 section 4.2 | 90 days |
| `person`     | The holder is a living natural person                         | None                            | 1 year    |
| `adult`      | The holder was at least 18 years old when it was issued       | None                            | 2 years   |
| `legal-name` | The holder's name as in an official identity document         | The name                        | 2 years   |

The lifetime is the longest time from `issued` to `expires`. An issuer
MAY choose shorter.

`person`, `adult` and `legal-name` are meant for eID issuers (section
10), but any issuer MAY issue them; what they are worth depends
entirely on what the issuer checked, which is why clients show who
issued them (section 9).

New types are added by updating this table. Until then `x-` followed
by 1 to 32 of `a-z`, `0-9` and `-` MAY be used (`x-student`), with a
lifetime of at most 2 years. Clients show an unknown type as its text.

## 4.3 Checking an Attestation

A client accepts an attestation if

1. it parses, has `v` 1 and a type of section 4.2 or an `x-` type, and
   `value` satisfies the type;
2. `issuer` differs from `subject`, and `sig` verifies with `issuer`;
3. the current time is between `issued` and `expires`, and `expires`
   is within the type's lifetime;
4. it was found where section 6 allows: in the attestation group owned
   by `subject`, with `publish` not `false`; or sent privately by
   `subject` (section 6.3);
5. it is not revoked (section 7).

Of several accepted attestations with the same issuer, subject and
type, the one with the highest `serial` counts. For `link`, this holds
per `value`.

# 5. Issuing

## 5.1 Asking for an Attestation

The subject asks by sending a private message (UN-RFC 0009) to the
issuer, with `Sender-Key`, `Content-Type:
application/x-unseenet-attestation-request` and the canonical JSON

```
{"subject":...,"type":...,"v":1,"value":...}
```

(`value` only where the type has one). `subject` MUST equal the
`Sender-Key`. The issuer decides by its own rules, which may involve
things outside the network: a membership list, a meeting, an eID check.
It answers with the attestation, or not at all.

## 5.2 Handing It Over

An issuer hands an attestation to its subject only, as a private
message with `Content-Type: application/x-unseenet-attestation` and
the attestation's canonical JSON as body. An issuer MAY issue without
being asked, for example after a meeting.

An issuer MUST NOT publish the attestations it issues anywhere else.
Clients will not show them if it does (section 4.3), but they would
still tell others what the issuer knows.

An issuer sets `publish` to `false` when the subject may show the
attestation to chosen people but not to everybody - typically a `met`
attestation from somebody who does not want to be publicly seen to
know the subject (section 11).

An issuer renews an attestation by issuing it again with a higher
`serial` before it expires. An organisation might renew `member` each
year with the fee; an issuer of `link` checks the link again first.

## 5.3 Meeting

A client MUST NOT issue `met` unless the user confirms that they have
compared the subject's **full** fingerprint (UN-RFC 0003 section 2)
with its holder - in person, or for `video` over a video call - and not
merely the short form, a name or a picture. Graphical clients SHOULD
offer a QR code of the full key for this; terminal clients SHOULD show
the full fingerprint in groups of four characters.

`met` is often mutual. A client that has just issued `met` MAY offer to
ask for one back.

## 5.4 Issuer Policies

An issuer that issues to people it does not know personally (an
organisation, an eID issuer, a link checker) SHOULD say in its public
profile (UN-RFC 0022) or on its site (UN-RFC 0035) which types it
issues, what it checks before it issues each one, what it stores, and
how to ask. Clients SHOULD let the user read this before trusting the
issuer (section 8).

# 6. Publishing

## 6.1 The Attestation Group

A key's published attestations live in the group it owns named
`attest`:

```
attest@<fingerprint of the key>
```

Its Group ID follows from the key, like that of the profile group
(UN-RFC 0022 section 5.1). It is a key-bound group (UN-RFC 0029). Its
manifest (UN-RFC 0004 section 3) has:

- `name`: `attest`;
- `type`: `channel`, with no `posters`;
- `view`: `data` (UN-RFC 0008 section 3.1.1);
- `attestations`: an array of at most 24 attestations whose `subject`
  is the owner (section 6.2);
- `revocations`: the revocation lists of the owner as an issuer
  (section 7.2);
- `expires`: as for key-bound groups (UN-RFC 0029);
- `retention_days`: RECOMMENDED `7`.

Either field may be missing or empty. The manifest MUST NOT exceed
32 768 octets, the size every node accepts (UN-RFC 0002 section 1).
Other articles than the revocation lists of section 7 mean nothing in
an attestation group; clients MUST ignore them.

A client MUST NOT create the attestation group of a key until the user
publishes an attestation with it or revokes one as an issuer. Most keys
never need one, and every group costs every node something (section
11).

A client reads an attestation group as it reads a profile group
(UN-RFC 0022 section 5.2): it asks a node for the current manifest and
accepts it if its `owner` is the key, its `name` is `attest` and it has
not expired. A node that does not carry it is not an error.

Nodes carry attestation groups like profile groups (UN-RFC 0022
section 10), under the policy field `profiles` of their node
information: a node that carries profile groups SHOULD carry
attestation groups.

## 6.2 Publishing an Attestation

Only the subject publishes an attestation, by adding it to the
`attestations` of its own attestation group with a new manifest.
Clients MUST ignore an entry whose `subject` is not the group's owner,
and an entry whose `publish` is `false`.

A client MUST NOT publish an attestation unless the user chooses to,
one attestation at a time. Before it does, it MUST tell the user, in
plain words, what the attestation will tell everybody who knows the
key:

- `met`: that the issuer has met them, and so that the issuer's key
  and theirs belong to people who know each other;
- `member`: that they belong to the issuer;
- `link`: the same as the link itself (UN-RFC 0022 section 9.1);
- `person`, `adult`: that the issuer has checked an identity document
  or eID, and so knows who holds the key;
- `legal-name`: their legal name, to everybody;

and that a published attestation cannot be fully taken back, as for
profiles (UN-RFC 0022 section 5.3).

The subject removes an attestation by publishing a manifest without
it. When it renews the group (UN-RFC 0029), its client SHOULD drop
attestations that have expired or been revoked.

## 6.3 Showing an Attestation Privately

A subject may show attestations only to chosen people, including
those with `publish` set to `false`. It sends them as articles, or
inner articles, with `Content-Type: application/x-unseenet-attestation`,
in the same ways as a private profile (UN-RFC 0022 section 6): in a
private message with `Sender-Key`, or in a closed group. A receiving
client accepts the attestation only if its `subject` is the
`Sender-Key`, or the inner `Author-Key` in a closed group, and shows
it only in that context.

# 7. Revocation

An issuer revokes an attestation before it expires - when a member
leaves, when a checked link disappears, when it learns that it was
deceived. Revocation has to work for an issuer with a handful of
subjects and for an association or an eID issuer with hundreds of
thousands, without a client ever fetching more than one small list
to check one attestation.

## 7.1 Revocation Lists

An issuer publishes its revocations in **revocation lists**: articles
in its own attestation group with

```
Content-Type: application/x-unseenet-revocations
Revocations: <shard>
```

and as body the canonical JSON `{"revoked":[...],"shard":...,"v":1}`,
where `shard` repeats the header. Each entry in `revoked` is a string

```
<fingerprint of the subject> <type> <serial>
```

for example `ph5fc5hop5232qsz member 3`. It revokes every attestation
by the issuer whose subject has that fingerprint (UN-RFC 0003 section
2), whose type is `type` and whose `serial` is less than or equal to
`serial`. For `link` it revokes all links of the subject up to that
serial; the issuer issues again those that are still valid.

An issuer uses either one shard, `*`, holding the revocations for all
subjects, or 32 shards, one for each character of the b32 alphabet
(UN-RFC 0003 section 1), each holding the revocations for the subjects
whose fingerprint begins with that character. The body of a revocation
list MUST NOT exceed 30 000 octets, so that the article fits within
the size every node accepts (UN-RFC 0002 section 1).

## 7.2 Finding Them

The manifest of the issuer's attestation group has the field

- `revocations`: an object whose keys are the shards in use - either
  only `*`, or b32 characters - and whose values are the Message-IDs of
  their current revocation lists.

A shard that is not a key has no revocations. To revoke, the issuer
posts the new revocation list and then a new manifest that names it.
It MAY gather revocations and publish them together, for example once
a day; until then the attestations it revokes still count.

A client checks an attestation by reading the issuer's attestation
group manifest (section 6.1). If the manifest names the shard of the
subject, or `*`, it fetches that one article with `ARTICLE
<message-id>`, and accepts it as the list if its author is the issuer,
its `Revocations` header is the shard and its body is valid. It caches
the list until the manifest's `serial` changes. A client that cannot
reach the manifest or the list MAY show the attestation from cache,
but MUST then say that revocation could not be checked.

## 7.3 Group State

UN-RFC 0017 section 2 is extended: the state of an attestation group
also includes the revocation lists named in its current manifest.
Nodes keep them whatever the group's retention, and list them in
`NEWNEWS` right after the manifest (UN-RFC 0017 section 3). When a
newer manifest no longer names a list, it expires normally.

UN-RFC 0012 section 3 is amended as for pages (UN-RFC 0035 section
6.2): a node MUST NOT reject a revocation list for being older than
the window if the current manifest of its group names it.

## 7.4 Capacity and Lifetimes

An entry takes about 28 octets, so one list holds about 1 000
revocations and 32 shards about 32 000. An issuer drops an entry once
every attestation it revokes has expired, so its lists hold only the
revocations made within one lifetime of its attestations.

An issuer whose revocations within one lifetime would not fit MUST
issue shorter lifetimes, and SHOULD then renew automatically (section
5.2). For example, an association with 100 000 members of whom 15 000
leave in a year fits with lifetimes of one year; one ten times larger
needs lifetimes of about a month.

An issuer MAY leave out of its lists attestations that expire within
7 days anyway, and a client MAY then skip the revocation check for an
attestation whose whole lifetime is 7 days or less.

# 8. Trust

Each client keeps a local list of **trusted issuers**. An entry names a
key, the types the user trusts it for, and a petname (UN-RFC 0019
section 8.4). The list is never sent to nodes or other users.

- A client MUST start with an empty list. The reference client trusts
  no issuer by default, and the project runs none (section 12).
- A client SHOULD treat the keys the user has given a petname (UN-RFC
  0019 section 8.4) - the user's contacts - as trusted for `met`, and
  only for `met`, and MUST let the user turn this off.
- A client MAY let the user trust an issuer from its profile, showing
  its policy (section 5.4) and the types it issues, and asking for
  which types.
- An issuer is trusted for an organisation's `member` attestations
  just by being trusted for `member`: the type states membership of
  the issuer itself.
- Trust is never passed on. A client MUST NOT trust an issuer because a
  trusted issuer has attested it, and MUST NOT combine attestations
  into a score or a level.

# 9. Showing

- A client SHOULD show the attestations of an identity in its profile
  view (UN-RFC 0022 section 9.2), after the names and the short form
  and before `about`.
- Each accepted attestation from a trusted issuer is shown with its
  type, its `value` and the issuer, by the issuer's petname, certified
  name or short form: "member of Foreningen X, board", "Peter has met
  this person", "legal name Andreas Lorensen, checked by
  @eid-example". A client SHOULD show `expires` on request.
- Attestations from issuers the user does not trust are shown, if at
  all, apart from the others and collapsed ("3 attestations from
  issuers you have not chosen to trust"), and each one as stated by
  its issuer's short form, never by a name the issuer claims.
- A `link` attestation is shown with the link it names, as "checked by
  <issuer> on <issued>", beside the user's own check (UN-RFC 0022
  section 7).
- A client MUST NOT show a single mark meaning "verified". It MAY show
  a small mark next to an author when there are attestations from
  trusted issuers, but the mark MUST open the list of what was
  attested and by whom, and MUST NOT look like the mark of a certified
  name (UN-RFC 0019 section 8.1).
- A `legal-name` is shown only in this list. It MUST NOT be used in
  place of a petname, name or display name, and the order of UN-RFC
  0019 section 8.1 is unchanged.
- A client MUST let the user hide the attestations of a key, as with
  profiles.

# 10. eID Issuers

An eID issuer checks an electronic identity before it issues `person`,
`adult` or `legal-name`: a national eID such as MitID through a broker,
or an EU Digital Identity Wallet. It runs outside the network and is
an issuer like any other: it has a key, a policy (section 5.4) and the
trust of those clients whose users chose to trust it.

Because it learns who holds a key, an eID issuer is the one place where
a key and a person meet. It:

- SHOULD ask the eID only for what the type needs, and SHOULD use
  selective disclosure where the eID offers it: an age-over-18 proof
  for `adult`, not a birth date;
- MUST issue `person` and `adult` without any name, number or other
  identifier in `value`;
- MUST issue `legal-name` only when the user explicitly asks for that
  type;
- SHOULD NOT keep the link between the eID and the subject key after it
  has issued, beyond what the law it operates under requires, and MUST
  say in its policy what it keeps;
- MAY promise at most one valid `person` per human. It then has to
  remember something per human; it SHOULD keep only a keyed hash of a
  pseudonymous identifier from the eID together with the `expires` of
  the attestation it issued, and not the subject key. It then cannot
  revoke for a user who lost their key, which is why `person` lasts at
  most one year.

A client MUST, before it sends a request to an eID issuer, tell the
user in plain words that the issuer will learn who they are and that
this key is theirs, and SHOULD advise using a separate identity for it
(section 11).

How an eID issuer talks to the eID - brokers, wallets, protocols - is
outside this document.

# 11. Security and Privacy Considerations

- **Linking.** Every attestation but `met` from a contact tells
  something about who holds a key, and `legal-name` tells everything.
  An identity used for anonymous posts or in closed groups should have
  none. A client SHOULD warn when the user asks for or publishes
  `person`, `adult`, `legal-name` or `member` on an identity that has
  posted without a profile, or in closed groups, and SHOULD make it
  easy to keep a separate, attested identity, as for names and
  profiles (UN-RFC 0019 section 12, UN-RFC 0022 section 9.1).
- **The social graph.** A published `met` ties two keys together, and
  many of them map who knows whom - the very thing onion services hide
  for nodes. That is why only the subject publishes (section 6.2), why
  the issuer can forbid it (`publish`: `false`), and why clients warn
  first.
- **Flooding.** Because clients accept attestations only from the
  subject's own group or from the subject in private (section 4.3), a
  stranger cannot attach anything to somebody else's key, and the
  manifest limits (section 6.1) bound what a subject can attach to its
  own.
- **Impersonation.** A key can name itself "Foreningen X" and issue
  `member` to anybody. Clients show untrusted issuers by short form
  only and apart (section 9), and trust comes only from the user's own
  choice (section 8).
- **Careless or bought issuers.** An attestation is worth what its
  issuer checked. Policies (section 5.4), per-type trust and showing
  the issuer every time keep this visible; revocation (section 7) and
  expiry limit the damage when an issuer is found out.
- **Scale.** Each attestation group is one more key-bound group, and
  key-bound groups are the part of the network that grows with the
  number of people (unseenet #217). This document therefore creates
  the group only when needed (section 6.1), bounds its size, and keeps
  revocation checks to two fetches (section 7).
- **Delayed revocation.** Between a revocation and the manifest that
  publishes it, and for as long as a client relies on its cache, a
  revoked attestation still counts. Issuers that need revocation to
  take effect quickly should publish at once and use short lifetimes.
- **Stolen issuer keys.** A thief can issue attestations until the
  issuer's users stop trusting the key. Organisations and eID issuers
  SHOULD keep their keys offline or in a vault and issue from a
  separate machine.
- **Lost subject keys.** Attestations belong to the key and are lost
  with it. The holder asks the issuers again for a new key; the old
  ones expire.
- **What nodes learn.** A node sees which attestation groups a client
  asks for, and so whose attestations and which issuers' revocations a
  user looks at. As for profiles, caching and reading the groups of
  all authors in a group at once make single lookups less telling.
  Private attestations are invisible to nodes.
- **What issuers learn.** A request goes over Tor, but it tells the
  issuer the subject key, and for an eID issuer the person behind it.
  A seized issuer can reveal what it stored, which is why eID issuers
  should store as little as section 10 allows.
- **Pressure.** An attestation that becomes expected - by a group, a
  community or a state - turns into a gate. This document gives no
  group or node a way to require one, and asks clients not to treat
  identities without attestations as less trustworthy (section 3).
- **Legal weight.** An attestation is not an identity document, and a
  signature on Unseenet is not a qualified electronic signature.
  Clients SHOULD NOT present either as such.

# 12. Rationale

- **Why only the subject publishes.** It is the one rule that avoids
  the keyserver problems: nobody can flood a key, and nobody can reveal
  a relationship the subject has not chosen to show. The cost is that
  an attestation is invisible until the subject publishes it, which is
  what the subject would want anyway.
- **Why a group of its own, and not in the profile.** A profile is
  limited to 8 KiB and is about what the key says; attestations are
  what others say, can be larger, and need a place for the issuer's
  revocations. One key-bound group serves both, so a client finds the
  attestations about a key and the revocations made by it at the same
  address.
- **Why no web of trust.** Trust through chains is how OpenPGP became
  hard to use and how one careless signature spread. A client shows one
  step: who attested this, and whether the user trusts them. Contacts
  being trusted for `met` gives the useful part - "somebody I know has
  met this person" - without chains.
- **Why no "verified" badge.** A single mark makes whoever hands it out
  the gatekeeper of the network. Saying who attested what keeps every
  issuer one of many, and leaves the judgement to the reader.
- **Why the project runs no issuer and trusts none by default.** So
  that no government, company or project - including this one - can
  decide who counts as trustworthy on Unseenet (UN-RFC 0025 section 6
  states the same principle for standing). Anybody can run an issuer;
  the project's registrar (UN-RFC 0019 section 7.2) gives names, not
  trust.
- **Why sharded revocation lists named in the manifest.** A client
  needs at most two fetches to check an attestation - the issuer's
  manifest and one list - whether the issuer has ten subjects or a
  million, and needs no new command. Naming the lists in the manifest
  makes them group state, so nodes keep them; 32 shards keep the
  manifest small. Entries use fingerprints rather than keys, which
  halves their size; 16 characters of fingerprint are as safe here as
  in link proofs (UN-RFC 0022 section 12). Beyond what 32 shards hold,
  short lifetimes do the work, as short-lived certificates have
  replaced revocation lists on the web.
- **Why types with lifetimes.** Facts change: people leave
  associations, accounts are deleted, keys are lost. Short lifetimes,
  shortest for links, let attestations go stale by themselves and keep
  revocation lists short.
- **Why `met` requires the full fingerprint.** Short forms are for
  telling known keys apart, not for checking them; an attacker can
  search for a key with a chosen short form.
- **Why eID issuers are outside the network.** An eID check needs a
  contract with a broker or a registration as a relying party, and
  personal data that must never reach nodes. Keeping it outside, as
  just another issuer, means the network works the same with or
  without it.

# 13. Open Issues

- **Groups that require attestations**, for example a members-only
  group of an association, or a group open only to `adult`. It is
  useful, but it is also the gate of section 11, and needs a document
  of its own.
- **Attestations about groups and nodes**, for example an organisation
  vouching for a node it runs, or for the owner of a hierarchy.
- **Moving to a new key.** A holder who rotates keys could ask issuers
  to re-issue in one step, with the old key signing the request.
- **eID integration.** Which eIDs and wallets an issuer should accept,
  and a profile for doing so, once the EU Digital Identity Wallets are
  in use.

# 14. Signature Purposes

UN-RFC 0003 section 3 is extended with:

| Purpose label        | Signs                          | Defined in |
|----------------------|--------------------------------|------------|
| `UNSEENET-ATTEST-1`  | an attestation (section 4)     | 0036       |

# 15. Changes to Other Documents

- UN-RFC 0003 section 3: the purpose `UNSEENET-ATTEST-1` (section 14).
- UN-RFC 0004 section 3.1: the manifest fields `attestations` and
  `revocations`, only in attestation groups.
- UN-RFC 0012 section 3: old revocation lists named in a current
  manifest are accepted (section 7.3).
- UN-RFC 0017 section 2: revocation lists named in the current
  manifest are part of the group's state (section 7.3).
- UN-RFC 0008 section 3.1.1: attestation groups are data groups.
- UN-RFC 0022 section 7: a client MAY check all links of a profile at
  once when the user asks for that, and shows `link` attestations
  beside its own checks (section 9).
- UN-RFC 0029 section 2: `attest@<fp>` is added to the table of
  key-bound groups.
- UN-RFC 0000 section 6: 0036 is added to the index.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
