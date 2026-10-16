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
the domain. Above all of these, every user's own **petnames** decide
what they see. Names are optional; an identity without one loses
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
   (the list published by IANA, e.g. `com`, `dk`, `microsoft`, `app`).
   The registrar looks this up when it handles the claim; nobody keeps a
   copy of the list for this purpose;
2. is reserved in section 9.

## 4.2 Domain Names

A domain name is a fully qualified DNS name of at least two labels,
lowercase, in ASCII (international names in their `xn--` form), at most
253 characters, without a trailing dot.

## 4.3 Telling Them Apart

A name with a dot is a domain name; a name without one is a registered
name. The two can never be confused, and neither can be confused with a
group name, because names of identities are always written with `@`.

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

If a client knows two accepted certificates for the same name with
different keys, it uses the one with the higher `serial`. If the serials
are equal, the registrar has made a mistake or its key was stolen: the
client MUST show both identities in short form and SHOULD mark the name
as **disputed**.

# 6. Registration

The formats in this section (claims, the DNS record, the revocation
list) are normative. The limits and the dispute policy are those of the
project's registrar; other registrars MAY choose their own.

## 6.1 Claims

A claim is sent to the registrar's inbox (UN-RFC 0009) as an inbox
article whose inner article has `Content-Type: application/json`, a
`Sender-Key` and `Sender-Signature` by the claiming identity, a
`Reply-Inbox`, and a canonical JSON body:

| Field    | Type   | Req. | Meaning                                 |
|----------|--------|------|-----------------------------------------|
| `v`      | integer| yes  | `1`                                     |
| `action` | string | yes  | `claim`, `renew`, `transfer` or `release` |
| `name`   | string | yes  | The name                                |
| `to`     | key    | for `transfer` | The new key                     |

The claiming identity is the verified sender key. The registrar answers
through `Reply-Inbox` with the certificate, or with a reason for
refusing.

## 6.2 Registered Names

The registrar issues a certificate for a free name to the first valid
claim it handles. To make squatting expensive, the project's registrar
(section 7.2):

- requires the claim article to carry at least 24 bits of postage
  (UN-RFC 0006);
- issues at most 3 registered names per key;
- issues certificates for 1 year.

## 6.3 Renewal and Expiry

The holder renews by sending `renew` before the certificate expires.
After expiry, only the former holder can renew for 30 days. Then the
name is free.

A registered name that has become a top-level domain since it was issued
(section 4.1) keeps its current certificate until it expires, but is not
renewed.

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

## 6.7 Disputes

The project's registrar takes a name away only for **impersonation or
abuse**: a name used to pass as a particular other person or
organisation, or to deceive. Wanting a name somebody else has is not a
dispute. Complaints are made as for hierarchies (UN-RFC 0018 section
7.1), and decisions are public.

Organisations that want a name nobody can dispute should use a domain
name.

# 7. Trusted Registrars

## 7.1 Pinning

A client has zero or more trusted registrars. Each is pinned as a
channel group, exactly like a node list publisher (UN-RFC 0010 section
4): the Group ID pins the owner, and the **registrar keys** are the
owner and the `posters` of its current manifest. A certificate is
trusted when its `registrar` is one of these keys. The same group holds
the revocation list and, as ordinary articles, the certificates the
registrar has issued, so that a client can look up who holds a name
(section 8.3).

If two trusted registrars issue the same name to different keys, the
client shows both in short form.

## 7.2 The Project's Registrar

The reference client pins the project's registrar:

- channel group `unseenet.names@ph5fc5hop5232qsz`, owned by the project
  key of UN-RFC 0010 section 6;
- inbox for claims: the inbox of the automated registrar key listed as a
  poster in that group's manifest.

The registrar runs automatically. It is a convenience of the reference
client, not part of the protocol.

# 8. Display

## 8.1 Order

To show an identity, a client uses the first of these that applies:

1. **Petname:** the name the user gave the key;
2. **Domain name** from an accepted certificate: `@lorensen.dk`;
3. **Registered name** from an accepted certificate: `@lorensen`;
4. **Short form** of the display name: `Andreas~7f3a`.

If an identity has several accepted names, the client MAY let the user
choose. It MUST let the user see the full key, and SHOULD show names
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
does not issue these registered names: `admin`, `abuse`, `help`, `info`,
`node`, `nodes`, `operator`, `postmaster`, `registrar`, `root`,
`security`, `support`, `system`, `unseenet`, `usenet`, and the names
reserved in UN-RFC 0018 section 9.

# 10. Signature Purposes

UN-RFC 0003 section 3 is extended with:

| Purpose label           | Signs                          | Defined in |
|-------------------------|--------------------------------|------------|
| `UNSEENET-NAME-CERT-1`  | a name certificate (section 5) | 0019       |

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
  domain name under it. The cost is that some common words (`app`,
  `music`, `shop`) cannot be registered.
- **Why do names not give hierarchies?** A name is cheap and automatic; a
  hierarchy is a promise to a community and needs a charter (UN-RFC
  0018). Joining them would make hierarchies free. It can be added
  later; it could not easily be taken away.
- **Why do domains expire after 35 days?** Domains change hands. A name
  that outlived its domain would mislead.

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
- **Stolen identity key.** The thief holds the name too, until the
  registrar acts on a complaint or the certificate expires.
- **Lookalikes.** Names are ASCII only, so Unicode lookalikes are
  impossible; section 8.2 covers near matches.

# 13. Changes to Other Documents

- UN-RFC 0002 section 2.3: the optional header `Name-Certificate` is
  added.
- UN-RFC 0003 section 2: "Clients SHOULD display at least the first 4
  characters next to display names" is replaced by section 8 of this
  document; the purpose in section 10 is added.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
