```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0019                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0002, 0003

                  Unseenet: Names for Identities
```

# Abstract

An identity is a key, and a key is not something people can remember.
This document gives identities names in three layers. Every identity is
shown as its self-chosen name with a short fingerprint
(`andreas~7f3a`). An identity MAY hold a **registered name**
(`@lorensen`), issued first come, first served by a **registrar** as a
signed **name certificate**, or a **domain name** (`@lorensen.dk`),
issued only after the registrar has checked that the identity controls
the domain. The holder of such a name MAY give **names under it** to
other identities (`sonia@lorensen`), and a domain MAY name people in DNS
(`andlo@lorensen.dk`), much as e-mail addresses work. Above all of these,
every user's own **petnames** decide what they see. Names are optional; an identity without one loses
nothing.

# 1. Motivation

UN-RFC 0003 makes display names (`From`) unauthenticated labels and
asks clients to show a few characters of the fingerprint next to them.
That keeps people apart, but nobody can tell a friend "write to me at
`7f3am2…`". People want a short name they can say aloud, and
organisations want a name that proves they are who they say they are.

A global name system without anybody in charge cannot be made safe:
there is no way to agree on who claimed a name first (see UN-RFC 0018
section 11). A registrar solves this the way registries of Internet
domains do: one party sees the claims in one order and signs the result.
As with hierarchies, the registrar is pinned, not built in, and nothing
it does can affect what an identity may post.

# 2. Terms

- **Display name:** the free-text `From` of an article (UN-RFC 0002).
- **Short form:** a display name followed by `~` and the first 4
  characters of the fingerprint, e.g. `Andreas~7f3a`.
- **Registered name:** a name without dots, e.g. `lorensen`.
- **Domain name:** a name with at least one dot, e.g. `lorensen.dk`,
  that is a domain in the Internet DNS.
- **Name certificate:** a registrar's signed statement that a name
  belongs to a key until a date (section 5).
- **Registrar:** an identity that issues name certificates.
- **Petname:** a name a user gives a key in their own client (section 8).

# 3. What Does Not Change

- An identity is still its key. Signatures, posting rules, group
  ownership and everything else refer to keys, never to names.
- Every identity can post without a name. Clients MUST NOT treat an
  identity without a name as less trustworthy than one with a name.
- A registrar cannot prevent an identity from posting, and cannot
  change or remove any article.

# 4. Name Syntax

## 4.1 Registered Names

```
reg-name = ALPHA *( ALPHA / DIGIT / "-" )   ; lowercase only
```

- 3 to 32 characters, `a-z`, `0-9` and `-`;
- starts with a letter, does not end with `-`, contains no `--`
  (which would make it look like an encoded international name);
- **contains no dot**.

A registrar MUST refuse a registered name that

1. is a top-level domain in the IANA root zone at the time of the claim
   (the list published by IANA, e.g. `com`, `dk`, `microsoft`, `app`),
   unless the claiming key is in the TXT record `_unseenet.nic.<tld>`
   (section 4.5). The registrar looks the list up when it handles the
   claim; nobody keeps a copy of it for this purpose;
2. is reserved in section 9, unless the claim comes from the project;
3. is the name of a top-level hierarchy in the trusted root list (UN-RFC
   0018) at the time of the claim, unless the claim comes from that
   hierarchy's maintainer. A hierarchy without a maintainer gives its
   name to nobody. Names in section 9 are decided by item 2 alone.

## 4.2 Domain Names

A domain name is a fully qualified DNS name of at least two labels,
lowercase, in ASCII (international names in their `xn--` form), at most
253 characters, without a trailing dot.

## 4.3 Telling Them Apart

A name with a dot is a domain name; a name without one is a registered
name. The two can never be confused, and neither can be confused with a
group name, because names of identities are always written with `@`.

## 4.4 Names Under a Name

```
sub-name = local "@" parent
local    = ( ALPHA / DIGIT ) *( ALPHA / DIGIT / "-" )   ; lowercase only
```

- `local` is 1 to 32 characters, `a-z`, `0-9` and `-`, does not start
  or end with `-` and contains no `--`;
- `parent` is a registered name (`sonia@lorensen`) or a domain name
  (`andlo@lorensen.dk`);
- there is one level only: `x@sonia@lorensen` is not a name.

A sub-name under a registered name is given by the holder of the parent
(section 5.4). One under a domain name is given either by the holder of
the domain name (section 5.4) or by the domain itself in DNS, checked by
the registrar (section 6.4). Sub-names are written without a leading
`@`, like e-mail addresses: `sonia@lorensen`, while other names keep it:
`@lorensen`.

## 4.5 Names of Others

Some registered names already belong to somebody outside the registrar:
a top-level domain belongs to its registry, a top-level hierarchy to its
maintainer. Section 4.1 gives such a name only to its owner, never to
whoever is quickest:

- **A top-level domain.** Its registry proves itself the way a domain
  does (section 6.4), with the record

  ```
  _unseenet.nic.microsoft.  TXT  "unseenet-key=ed25519:..."
  ```

  Generic top-level domains have the host `nic.<tld>`, run by their
  registry, so nobody else can publish it. A top-level domain where
  nobody can publish this record stays closed.
- **A top-level hierarchy.** Its maintainer in the root list claims it
  like any registered name. `@torproject` thus becomes the Tor
  Project's the day it is given `torproject.*`, and is nobody's until
  then - the project's included.

The registrar checks both again at each renewal (section 6.3).
Names that only exist as domains below the top level (`maersk`, for
`maersk.com` and `maersk.dk`) are first come, first served like any
other: see section 11.

# 5. Name Certificates

## 5.1 Format

A name certificate is a JSON object in canonical JSON (UN-RFC 0004
section 3):

| Field       | Type       | Req. | Meaning                                            |
|-------------|------------|------|----------------------------------------------------|
| `v`         | integer    | yes  | `1`                                                |
| `name`      | string     | yes  | The registered or domain name                      |
| `kind`      | string     | yes  | `registered` or `domain`                           |
| `key`       | key string | yes  | The identity the name belongs to                   |
| `issued`    | date       | yes  | RFC 3339 UTC                                       |
| `expires`   | date       | yes  | RFC 3339 UTC                                       |
| `serial`    | integer    | yes  | Increases each time the registrar issues this name  |
| `registrar` | key string | yes  | The issuing key                                    |
| `claim`     | string     | no   | Message-ID of the claim it was issued for (6.8)    |
| `claimed`   | date       | no   | The `Date` of that claim, RFC 3339 UTC (6.8)       |
| `sig`       | signature  | yes  | By `registrar`, purpose `UNSEENET-NAME-CERT-1`, over the canonical JSON without `sig` |

Lifetimes:

- `registered`: at most 1 year;
- `domain`: at most 35 days, because the registrar checks the domain
  again every month (section 6.4).

## 5.2 Carrying a Certificate

An identity carries its certificate itself. An article MAY have the
header

```
Name-Certificate: <b64 of the canonical JSON>
```

It is part of the canonical form and so is signed by the author. In
encrypted articles (UN-RFC 0004 section 6, UN-RFC 0009) it MUST be put
in the inner header block, not the outer one, so that nodes do not learn
the author's name.

Clients SHOULD include it only in the first article in a group and
every so often after that (RECOMMENDED: once a week per group), and
SHOULD cache certificates by key, so that articles stay small.

## 5.3 Checking a Certificate

A client accepts a certificate for the author of an article if

1. it parses and has `v` 1;
2. `key` equals the article's `Author-Key`;
3. `registrar` is a trusted registrar (section 7), and `sig` verifies;
4. the current time is between `issued` and `expires`;
5. it is not revoked (section 6.6);
6. its `name` satisfies section 4 for its `kind`.

Certificates for the same name, key and serial from different registrar
keys of one group are the same decision (section 6.8), not a conflict.

If a client knows two accepted certificates for the same name with
different keys, it uses the one with the higher `serial`. If the serials
are equal, it uses the one with the earlier `claimed`, and then the one
with the lexicographically lower `claim`. Only if that does not decide
(both are equal, or a certificate has no `claim`) has the registrar made
a mistake or had a key stolen: the client MUST then show both identities
in short form and SHOULD mark the name as **disputed**.

A client MAY require a decision to be signed by at least two registrar
keys of the group before it shows a name, so that one stolen key alone
cannot give a name away.

## 5.4 Sub-name Certificates

The holder of a registered or domain name issues a sub-name under it
with a **sub-name certificate**, signed by its own identity key; no
registrar is involved. It has the fields of section 5.1, except:

| Field       | Type       | Req. | Meaning                                            |
|-------------|------------|------|----------------------------------------------------|
| `kind`      | string     | yes  | `sub`                                              |
| `parent`    | string     | yes  | The name it is under; MUST be the part after `@`   |
| `registrar` | key string | yes  | The issuer: the holder of `parent` when it was issued |
| `sig`       | signature  | yes  | By the issuer, purpose `UNSEENET-SUBNAME-CERT-1`   |

`claim` and `claimed` are not used. A sub-name certificate lasts at most
five years; the issuer chooses (RECOMMENDED: one year). It is carried in
`Name-Certificate` like any certificate (section 5.2).

A client accepts a sub-name certificate for the author of an article if

1. it parses, has `v` 1 and `kind` `sub`, and its `sig` verifies with
   the issuer's key;
2. `key` equals the article's `Author-Key`, and the current time is
   between `issued` and `expires`;
3. the issuer holds `parent` **now**: the client has accepted a
   certificate for `parent` (section 5.3) whose `key` is the issuer;
4. the issuer has not revoked it (section 6.6);
5. for a name under a domain: no accepted certificate from the registrar
   names a different key for the same sub-name (DNS wins, section 6.4).

Of several accepted sub-name certificates for one name, the one with the
highest `serial` from the current issuer counts. When the parent changes
hands or expires, every sub-name under it stops counting until the new
holder issues its own.

**Asking for one.** An identity asks for a sub-name by sending a private
message (UN-RFC 0009) to the parent's holder with `Content-Type:
application/x-unseenet-name-request` and the canonical JSON
`{"key":...,"name":...,"v":1}`. The holder answers by sending the
certificate as a private message with `Content-Type:
application/x-unseenet-name-certificate`, or not at all. A holder MAY
also issue a sub-name without being asked, including to its own key.

An identity MAY hold several names - its own registered name and
sub-names under several other names. It chooses which certificate its
articles carry, and readers SHOULD show the one an identity sent most
recently (section 8.1).

# 6. Registration

The formats in this section (claims, the DNS record, the revocation
list) are normative. The limits and the dispute policy are those of the
project's registrar; other registrars MAY choose their own.

## 6.1 Claims

A claim is sent to the registrar's **claim inbox** (UN-RFC 0009), which
the registrar group's manifest names in the field `claims` (a Group ID),
as an inbox article whose inner article has
`Content-Type: application/json`, a `Sender-Key` and `Sender-Signature`
by the claiming identity, a `Reply-Inbox`, and a canonical JSON body:

| Field    | Type   | Req. | Meaning                                 |
|----------|--------|------|-----------------------------------------|
| `v`      | integer| yes  | `1`                                     |
| `action` | string | yes  | `claim`, `renew`, `transfer` or `release` |
| `name`   | string | yes  | The name                                |
| `to`     | key    | for `transfer` | The new key                     |

The claiming identity is the verified sender key. The registrar answers
through `Reply-Inbox` with the certificate, or with a reason for
refusing. With several replicas (6.8) every replica answers, with its own
certificate; a client keeps them all, since a name stays valid as long as
any of their keys is trusted.

## 6.2 Registered Names

The registrar issues a certificate for a free name to the first valid
claim in the order of section 6.8. To make squatting expensive, the
project's registrar (section 7.2):

- requires the claim article to carry at least 24 bits of postage
  (UN-RFC 0006), by giving the claim inbox a `min_pow` of 24, so that
  the nodes enforce it;
- issues at most 3 registered names per key;
- issues certificates for 1 year.

## 6.3 Renewal and Expiry

The holder renews by sending `renew` before the certificate expires.
After expiry, only the former holder can renew for 30 days. Then the
name is free.

The checks of section 4.1 are made again at each renewal. A registered
name that has since become a top-level domain or the name of a top-level
hierarchy whose owner is not the holder keeps its current certificate
until it expires, but is not renewed.

## 6.4 Domain Names

To claim `lorensen.dk`, the identity publishes the DNS TXT record

```
_unseenet.lorensen.dk.  TXT  "unseenet-key=ed25519:..."
```

with its full key, and sends a `claim`. The registrar looks the record up
and issues a certificate only if it contains the claiming key. It does
the same check before each monthly renewal, without being asked; when
the record is gone, it issues no new certificate and the old one runs
out within 35 days.

There is no limit on the number of domain names per key, and no extra
postage: owning the domain is the proof.

A domain can also name **people under it**, the way it names their
e-mail addresses. To claim `andlo@lorensen.dk`, the identity publishes,
or has the domain's owner publish,

```
andlo._unseenet.lorensen.dk.  TXT  "unseenet-key=ed25519:..."
```

and sends a `claim` for `andlo@lorensen.dk`. The registrar checks it like
a domain name and issues a certificate of kind `domain`, renewed monthly
while the record is there. An organisation can thus give its people
names without running Unseenet itself. Where such a certificate and a
holder's sub-name certificate (section 5.4) disagree, the registrar's
counts.

A registrar MUST refuse a claim for a sub-name under a registered name
(`sonia@lorensen`): only the holder of the parent gives those.

## 6.5 Transfer and Release

The holder can send `transfer` naming a new key, which the registrar
answers by issuing a certificate to the new key with a higher `serial`
and revoking the old one. This is also how an identity moves to a new
key. `release` gives a name up at once.

## 6.6 Revocation

A registrar publishes a **revocation list**, a JSON object
`{"v":1,"revoked":[{"name":...,"serial":...}, ...]}`, in its
channel group (section 7) like a node list (UN-RFC 0010). It names
certificates that are no longer valid before their expiry: after a
transfer, a release, or a dispute (6.7). Entries can be dropped once the
certificate they name has expired, so the list stays short.

Each registrar key of a group publishes its own list. A client takes the
newest list by each trusted key, and an entry in any of them revokes
every certificate for that name and serial, whichever key signed it.

An **issuer of sub-names** publishes its revocation list in the same
format in a data group (UN-RFC 0008 section 3.1.1) of type `channel`
that it owns, named `names` - so its Group ID is
`names@<fingerprint of the issuer>`, and a client can find it from the
certificate alone. A client SHOULD read it for the issuers of the
sub-names it shows.

## 6.7 Disputes

The project's registrar takes a name away only for **impersonation or
abuse**: a name used to pass as a particular other person or
organisation, or to deceive. Wanting a name somebody else has is not a
dispute. Complaints are made as for hierarchies (UN-RFC 0018 section
7.1), and decisions are public.

Organisations that want a name nobody can dispute should use a domain
name.

## 6.8 Several Registrar Keys

A registrar group MAY list several registrar keys, each held by a
**replica** of the registrar running on its own machine. Every replica
issues its own certificate, signed with its own key, for every decision.
So the registrar keeps working while any one replica runs, and a name
stays valid while any key that signed it is still trusted. The group's
owner adds and removes replicas by changing the manifest's `posters`.

All replicas read the same claims. The claim inbox is an inbox group
whose owner is an **inbox key** that every replica holds; it is used only
to open claims and to sign the inbox's manifest, never to sign
certificates, and it is not a registrar key. Like any group, the inbox is
carried by every node. For the replicas to reach the same decisions,
every replica follows these rules:

1. **Order.** Claims are handled in the order of their `Date`, then of
   their Message-ID. At time *t*, a replica handles every claim whose
   `Date` is at least one hour before *t* and that it has not yet
   handled, in that order. The hour gives the claim time to reach every
   node.
2. **Late claims.** A claim that reaches a replica only when its `Date`
   is already more than an hour old is late. The replica refuses it
   ("arrived late, send it again") and takes no other action.
3. **Same inputs, same output.** A decision depends only on the claim,
   the earlier decisions in this order, and the DNS record and list of
   top-level domains as the replica finds them when it handles the claim.
   A certificate issued for a claim has `claim` set to the claim's
   Message-ID, `claimed` and `issued` set to the claim's `Date`,
   `expires` set to `issued` plus the lifetime, and `serial` one more
   than the highest serial issued for the name for any earlier claim. A
   monthly renewal of a domain name without a claim is issued at 00:00
   UTC on the first day of the month, without `claim` and `claimed`.
4. **Converging.** If a replica finds that another replica's certificate
   wins over its own by section 5.3, because it did not see a claim in
   time or found a DNS record differently, it issues the winning
   decision with its own key as well. It does not revoke its own
   certificate: section 5.3 already makes the winner count on every
   client, and a revocation names a serial, so it would revoke the
   winner's certificate too.

Claims, certificates and revocations all travel through the network,
so replicas need no connection to each other and no other place to keep
state: a replica that starts on a new machine rebuilds what it knows
from its group and its inbox.

# 7. Trusted Registrars

## 7.1 Pinning

A client has zero or more trusted registrars. Each is pinned as a
channel group, exactly like a node list publisher (UN-RFC 0010 section
4): the Group ID pins the owner, and the **registrar keys** are the
owner and the `posters` of its current manifest. A certificate is
trusted when its `registrar` is one of these keys. The same group holds
the revocation list and the certificates the registrar has issued, so
that a client can look up who holds a name (section 8.3):

- a certificate is posted as an ordinary article with
  `Content-Type: application/json`, `Subject: name <name>` and the
  certificate's canonical JSON as its body;
- the revocation list is posted the same way with `Subject: revoked`.

A client looking up a name reads the subjects and takes the accepted
certificate with the highest `serial` (section 5.3).

If two trusted registrars issue the same name to different keys, the
client shows both in short form.

## 7.2 The Project's Registrar

The reference client pins the project's registrar:

- channel group `unseenet.names@ph5fc5hop5232qsz`, owned by the project
  key of UN-RFC 0010 section 6;
- claim inbox: the Group ID in the `claims` field of that group's
  manifest.

The registrar runs automatically, as at least two replicas (section 6.8)
on machines that are not the project's nodes, so that it depends on no
single machine or node. It is a convenience of the reference
client, not part of the protocol.

# 8. Display

## 8.1 Order

To show an identity, a client uses the first of these that applies:

1. **Petname:** the name the user gave the key;
2. **A certified name:** of the accepted names of section 5, the one
   whose certificate the identity sent most recently; otherwise, in this
   order, a domain name (`@lorensen.dk`, also `andlo@lorensen.dk` from
   DNS), a sub-name (`sonia@lorensen`), a registered name (`@lorensen`);
3. **Short form** of the display name: `Andreas~7f3a`.

So an identity with several names chooses which one it shows, by the
certificate its articles carry. It MUST let the user see the full key, and SHOULD show names
from certificates so that they cannot be mistaken for petnames or
display names (e.g. with a mark).

## 8.2 Warnings

A client SHOULD warn when a name it is about to show differs only
slightly (e.g. by one character) from a petname or a certified name the
user already knows, and MUST NOT show a display name in a way that looks
like a certified name (e.g. a `From` of `@lorensen`).

## 8.3 Addressing by Name

A client MAY let the user write to `@lorensen` or `@lorensen.dk`. It
resolves the name through the trusted registrar's group and MUST show
the key it found, and its short form, before the first message is sent.

## 8.4 Petnames

Clients MUST support petnames. A petname is local: it is never sent to
nodes or other users. A client SHOULD offer to save the name it shows as
a petname the first time the user writes to or replies to an identity,
so that later changes of certificate do not silently change what the
user sees.

# 9. Reserved Names

Besides the top-level domains (section 4.1), the project's registrar
does not issue these registered names to anybody but the owner of its own
group (section 7), that is, the project: `admin`, `abuse`, `help`,
`info`, `node`, `nodes`, `operator`, `postmaster`, `registrar`, `root`,
`security`, `support`, `system`, `unseenet`, `usenet`, and the names
reserved in UN-RFC 0018 section 9. The project uses them for itself (for
example `@unseenet`, and `help@unseenet` under it), so that nobody else
can pose as it.

Hierarchies added to the root list later are covered by section 4.1
item 3 without being added here: their names go to their maintainers,
not to the project.

# 10. Signature Purposes

UN-RFC 0003 section 3 is extended with:

| Purpose label           | Signs                          | Defined in |
|-------------------------|--------------------------------|------------|
| `UNSEENET-NAME-CERT-1`  | a name certificate (section 5) | 0019       |
| `UNSEENET-SUBNAME-CERT-1` | a sub-name certificate (section 5.4) | 0019 |

# 11. Rationale

- **Why certificates and not a list?** A list of every name does not fit
  in an article (UN-RFC 0002 allows 32 768 octets for sure). A
  certificate travels with the identity, and a client can check it
  without asking anybody.
- **Why first come, first served?** Anything else needs somebody to judge
  who deserves a name. The project has neither the means nor the wish
  to do that. Domain names give those who need proof a way to get it.
- **Why are top-level domains refused?** `@microsoft` would otherwise go
  to whoever was quickest. Names that are top-level domains already
  belong to somebody in the world outside, and that somebody can use a
  domain name under it, or claim the name itself (section 4.5). The cost
  is that some common words (`app`, `music`, `shop`) cannot be
  registered by anybody but their registry.
- **Why may a registry claim its top-level domain?** Refusing `@microsoft`
  to everybody kept it from squatters, but also from Microsoft. The
  record under `nic.<tld>` can only be published by the registry, so
  letting it claim costs nothing and keeps the name out of the wrong
  hands just as well.
- **Why do hierarchy names go to their maintainers?** A hierarchy is a
  promise to a community; somebody holding `@torproject` or `@matrix`
  would look as if they spoke for `torproject.*` or `matrix.*`. Reading
  the root list means a new hierarchy is covered the day it is listed,
  with nothing copied by hand.
- **Why not ask DNS proof for `maersk` too?** Nearly every name exists as
  a domain somewhere (`anna.com`, `sonia.net`), so it would end
  registered names for everybody without a domain, tie identities to
  whoever paid for a domain, and make the registrar choose between the
  owners of `maersk.com` and `maersk.dk`. Those who need proof have
  domain names, which clients show first (section 8.1).
- **Why do names not give hierarchies?** A name is cheap and automatic; a
  hierarchy is a promise to a community and needs a charter (UN-RFC
  0018). Joining them would make hierarchies free. It can be added
  later; it could not easily be taken away.
- **Why do domains expire after 35 days?** Domains change hands. A name
  that outlived its domain would mislead.
- **Why may sub-names last five years?** The holder of a name may be away
  from the network for a long time - an organisation's admin, say - and
  its people should not lose their names meanwhile. A sub-name still
  counts only while its issuer holds the parent, and the issuer can
  revoke it at any time, so a long life does not outlast the parent.
- **Why one level?** `x@sonia@lorensen` would be hard to read and harder
  to reason about. One level covers families and organisations.

# 12. Security and Privacy Considerations

- **Linking.** A name ties together everything its identity posts, and a
  domain name ties the identity to whoever owns the domain. Clients MUST
  make this clear before claiming a name, and SHOULD NOT suggest names
  for identities used in closed groups. Clients SHOULD let an identity
  post without its certificate.
- **The registrar sees claims.** It learns which key claimed which name
  and when, but not where from: claims arrive in its inbox over Tor.
- **DNS lookups** are made by the registrar, never by clients, so a
  client never reveals over the clearnet which names it is looking at.
  A registrar SHOULD make its lookups over Tor.
- **Stolen registrar key.** A thief can issue certificates for any name
  until the group owner removes the key from the manifest; clients then
  stop trusting its certificates at once, because trust follows the
  current manifest. Certificates the thief issued with an existing
  name's serial show up as disputed (5.3). Petnames are not affected.
- **Stolen replica key.** One stolen key among several can still issue
  certificates the others did not; a client that requires two keys (5.3)
  is not fooled by it. Removing the key from the manifest makes only that
  key's certificates untrusted: the others' certificates for the same
  decisions stay valid.
- **Stolen inbox key.** It lets the thief read claims, which say little
  that the certificates do not, but not issue anything. The group's owner
  makes a new inbox key and claim inbox and changes `claims` in the
  manifest.
- **Stolen identity key.** The thief holds the name too, until the
  registrar acts on a complaint or the certificate expires.
- **Sub-names.** The holder of a name can give names under it to anyone;
  readers see `sonia@lorensen` as "given by whoever holds `@lorensen`",
  no more. A stolen holder key can issue sub-names until the parent is
  transferred or revoked; then they all stop counting (section 5.4).
- **Lookalikes.** Names are ASCII only, so Unicode lookalikes are
  impossible; section 8.2 covers near matches.

# 13. Changes to Other Documents

- UN-RFC 0002 section 2.3: the optional header `Name-Certificate` is
  added.
- UN-RFC 0004 section 3.1: a registrar group's manifest has the field
  `claims` (section 6.1).
- UN-RFC 0003 section 2: "Clients SHOULD display at least the first 4
  characters next to display names" is replaced by section 8 of this
  document; the purpose in section 10 is added.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
