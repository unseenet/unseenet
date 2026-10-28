```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0024                                              October 2026
Category: Standards Track
Status: Draft
Implemented: unseenet-gateway 0.1.0
Updates: 0023

                         Usenet Gateways
```

# Abstract

This document is the network profile (UN-RFC 0023 section 9) for
**Usenet**. It says how Usenet group names map to `usenet.*`, how
articles convert in both directions, which Usenet messages are never
imported, how articles from Unseenet are recognised on their way back,
and what Usenet expects of a gateway. Everything not said here follows
UN-RFC 0023.

# 1. Overview

Usenet is the network Unseenet is modelled on. Both carry articles in
named groups, with RFC 5322-style headers, over NNTP; the conversion is
therefore close, and the differences are in what Unseenet adds
(signatures, content-derived Message-IDs, postage) and leaves out
(`Path`, crossposting, binaries, unauthenticated cancels).

A Usenet gateway normally runs its own news server (for example INN) on
the gateway host. The news server peers with Usenet, keeps the history,
writes `Path`, and filters spam; the gateway reads new articles from it
as a newsreader would and posts exported articles to it.

# 2. Manifest Fields

For Usenet, the `gateway` field of UN-RFC 0023 section 3.2 means:

| Field     | Value                                                          |
|-----------|----------------------------------------------------------------|
| `network` | `usenet`                                                       |
| `source`  | The Usenet group name, exactly as on Usenet                    |
| `host`    | The gateway's Usenet path identity (RFC 5536 section 3.1.5)    |
| `abuse`   | An e-mail address for complaints, as in `Injection-Info`       |

# 3. Names

The gatewayed group for the Usenet group `N` is named `usenet.` followed
by `N` in lower case: `dk.politik` becomes `usenet.dk.politik`,
`comp.lang.python` becomes `usenet.comp.lang.python`.

If the result is not a valid group name (UN-RFC 0004 section 1:
characters, or more than 128 octets), the Usenet group MUST NOT be
gatewayed. Usenet groups that differ only in case map to the same name;
a gateway MUST gateway at most one of them.

# 4. Import

## 4.1 What Is Never Imported

In addition to UN-RFC 0023 section 4.1, a Usenet gateway MUST NOT import:

1. control messages: articles with a `Control` header, or with a
   `Subject` starting with `cmsg `, including `newgroup`, `rmgroup`,
   `checkgroups` and `cancel`;
2. articles whose Message-ID ends in `@unseenet>` (section 5.2: these
   came from Unseenet and are already there);
3. articles containing yEnc or uuencoded data, or MIME parts other than
   `text/plain` that are not a signature or a short alternative such as
   `text/html`.

A gateway SHOULD filter spam at least as strictly as a well-run Usenet
text server, for example with Cleanfeed on its news server.

## 4.2 Conversion

| Unseenet header      | Value                                                          |
|----------------------|----------------------------------------------------------------|
| `From`               | The display name of the Usenet `From`, or its local part if there is none |
| `Subject`            | The Usenet `Subject`, MIME-decoded                             |
| `Origin-Network`     | `usenet`                                                       |
| `Origin-ID`          | The Usenet Message-ID, unchanged                               |
| `Origin-Date`        | The Usenet `Date`, unchanged                                   |
| `Origin-From`        | The Usenet `From`, unchanged                                   |
| `Usenet-Newsgroups`  | The Usenet `Newsgroups`, if it names more than one group       |
| `Usenet-References`  | The Usenet `References`, if any reference could not be mapped  |
| `Usenet-Followup-To` | The Usenet `Followup-To`, if present                           |

The other headers are set as in UN-RFC 0023 section 4.2. All other Usenet
headers, including `Path`, `Xref`, `NNTP-Posting-Host`, `Injection-Info`
and `Organization`, are dropped.

The body is decoded from its transfer encoding and charset to UTF-8. Of
a MIME multipart article only the first `text/plain` part is kept.

## 4.3 References

For each Usenet `References` entry, the gateway puts the mapped Unseenet
Message-ID into `References`, in the same order. An entry of the form
`<id@unseenet>` maps to itself (section 5.2). Entries that cannot be
mapped are left out, and the original header is then kept in
`Usenet-References`.

## 4.4 Crossposts

Unseenet does not allow crossposting (UN-RFC 0002 section 2.1). A Usenet
article posted to several groups is imported **once**, into the
gatewayed group of the first group in its `Newsgroups` that this gateway
gateways, and the full list is kept in `Usenet-Newsgroups`.

## 4.5 Cancels, Supersedes and No-Archive

Usenet cancels are not authenticated. A gateway MAY act on a Usenet
`cancel` or `Supersedes` according to its stated policy, for example
only for cancels issued by the server named in the target's
`Injection-Info`. When it does, it posts an Unseenet cancel for the
imported article (UN-RFC 0023 section 4.5); for `Supersedes` it then
imports the new article.

`X-No-Archive: yes` and `Archive: no` are requests not to archive in the
sense of UN-RFC 0023 section 4.5.

# 5. Export

## 5.1 Conversion

The gateway builds a Usenet article (RFC 5536) from the Unseenet article:

| Usenet header     | Value                                                            |
|-------------------|------------------------------------------------------------------|
| `Path`            | `<host>!not-for-mail`, where `<host>` is the manifest's `host`   |
| `Message-ID`      | The Unseenet Message-ID, unchanged: `<id@unseenet>`              |
| `Newsgroups`      | The manifest's `source`. Never more than one group.              |
| `Date`            | The Unseenet `Date`                                              |
| `From`            | `"<From> (<fp4>)" <<fingerprint>@unseenet.invalid>`, where `<fp4>` is the first 4 characters of the author's fingerprint |
| `Subject`         | The Unseenet `Subject`                                           |
| `References`      | Each entry mapped back: an imported article's `Origin-ID`, otherwise the Unseenet Message-ID unchanged |
| `Injection-Info`  | `<host>; posting-account="<fingerprint>"; mail-complaints-to="<abuse>"` (RFC 5536 section 3.2.8) |
| `Content-Type`    | `text/plain; charset=utf-8`                                      |
| `Unseenet-Author-Key` | The author's `Author-Key`                                    |

No other Unseenet header is exported. In particular `Signature`,
`Proof-Of-Work`, `Approved-By` and `Approval` are dropped: Usenet readers
cannot verify Unseenet signatures, and `Unseenet-Author-Key` is
informational only.

The other network has accepted the article (UN-RFC 0023 section 5.2 step
4) when the gateway's news server answers `240` or `235`.

## 5.2 Message-IDs

Keeping the Unseenet Message-ID on Usenet means:

- replies on Usenet reference `<id@unseenet>`, which import maps to the
  original without a table (section 4.3);
- the copy that comes back through the Usenet feed is not imported
  (section 4.1 item 2), so there are no loops;
- two gateways that export the same submission produce the same
  Message-ID, and Usenet's own history drops the second.

## 5.3 Addresses

A `.invalid` address (RFC 2606) cannot receive mail. Replies by e-mail
are impossible; replies on Usenet reach the author through import.

## 5.4 Retractions

The gateway is the injecting server of every article it exports, and MAY
cancel one on Usenet (UN-RFC 0023 section 6.2). A cancel in Unseenet is
never turned into a Usenet cancel on its own.

# 6. The Other Side

For Usenet the other side (UN-RFC 0023 section 6.1) is the administrators
of the servers the gateway's news server peers with. To Usenet the
gateway is the injecting server for every exported article, and servers
that inject spam or abuse lose their peers.

- Peering by agreement is RECOMMENDED. Reading a public server as an
  ordinary user and re-publishing its groups may itself be against its
  terms.
- Before exporting, the operator MUST tell the peers that the gateway
  cannot identify or trace authors, only stop keys, and MUST have a
  working `abuse` address in `Injection-Info`.
- The pseudonymous record of UN-RFC 0023 section 6.2 is what the gateway
  can offer where a Usenet server would keep a log of who posted what.

## 6.1 Several Gateways

A Usenet group can be served by several gateways (UN-RFC 0038).

- **Usenet has no consent of its own** to give (UN-RFC 0038 section 3.2,
  step 1): anyone can read a newsgroup, and a server's peers are not the
  group. Admission rests on the group owner's approval alone, and the
  gateway that presents the join request MUST say so.
- **Duplicates need nothing more:** one Usenet article has the same
  `Message-ID`, and so the same origin pair (UN-RFC 0023 section 4.2),
  whichever gateway reads it and from whichever server, so the import
  turns of UN-RFC 0038 section 4 catch it.
- **Already there**, for export (UN-RFC 0038 section 5), is a `STAT
  <message-id>` that succeeds on the gateway's own news server, which
  holds what its peers sent it.

# 7. Timing Signals

Usenet has no presence, typing or read signals. The only timing
information is the time of injection, which UN-RFC 0023 section 5.2
blurs, and `Date`, which is the Unseenet `Date` rounded to 10 minutes.

# 8. Headers Defined Here

| Header                | In       | Defined in  |
|-----------------------|----------|-------------|
| `Usenet-Newsgroups`   | Unseenet | section 4.2 |
| `Usenet-References`   | Unseenet | section 4.2 |
| `Usenet-Followup-To`  | Unseenet | section 4.2 |
| `Unseenet-Author-Key` | Usenet   | section 5.1 |

# 9. Rationale

- **Why `usenet.dk.politik` and not `dk.politik`?** Unseenet's `dk.*` is
  free and already in use, and the Big 8 names are reserved for
  communities that want to revive them in Unseenet (UN-RFC 0018 section
  9). See also UN-RFC 0023 section 12.
- **Why keep `<id@unseenet>` as the Usenet Message-ID?** It makes loop
  prevention and threading stateless, and lets several gateways export
  the same article without duplicates.
- **Why a local news server instead of speaking NNTP to peers directly?**
  INN and its peers already solve peering, history, `Path`, filtering
  and backlog. The gateway only converts.
- **Why `.invalid` addresses?** Unseenet identities have no mail
  address, and inventing a deliverable one would invite spam to a domain
  that cannot handle it. RFC 2606 reserves `.invalid` for exactly this,
  and many Usenet servers already accept it.

# 10. Security Considerations

UN-RFC 0023 section 13 applies. In addition:

- Usenet servers keep text groups for years and many are archived in
  public. An exported article SHOULD be assumed permanent.
- Usenet cancels and `Supersedes` are easily forged; section 4.5 leaves
  acting on them to the gateway's stated policy.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
