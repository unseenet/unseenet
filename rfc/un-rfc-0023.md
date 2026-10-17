```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0023                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0018

                     Gateways to Usenet
```

# Abstract

This document defines a **gateway** between Unseenet and Usenet. A
gateway imports articles from chosen Usenet text groups into Unseenet,
and MAY send articles written in Unseenet back to Usenet. Gatewayed
groups live in a new top-level hierarchy, `usenet`, as moderated groups
whose moderator is the gateway. Import reuses ordinary posting; export
reuses the submission queue of moderated groups (UN-RFC 0009 section 3),
so nodes and clients need no new protocol to carry gatewayed groups.
The document also says what a gateway operator takes responsibility for,
because to Usenet the gateway is the injecting server for everything it
exports.

# 1. Motivation

Unseenet borrows Usenet's model, and Usenet still has living text
groups. Letting Unseenet users read them, and in some groups take part,
gives the network content from day one and gives Usenet readers a way
in. But the two networks differ in ways a gateway must bridge
deliberately rather than by copying bytes:

- Usenet articles are unsigned, carry a `Path`, may be crossposted, may
  be binary, and may be forged or cancelled by anyone. Unseenet articles
  are signed, content-addressed, single-group, text, and carry no `Path`
  (UN-RFC 0002).
- Group names collide: Usenet has `alt.*`, `dk.*` and the Big 8, and so
  does Unseenet (UN-RFC 0018).
- Usenet holds the injecting server responsible for what it injects.
  Unseenet has no injecting server, only signing keys.

The design goal is that a gatewayed group is an ordinary Unseenet group
to every node and client that does not know this document, and that
nothing about a gateway weakens the anonymity of nodes or users who
never touch it.

# 2. Terms

- **Gateway:** software, with its operator, that moves articles between
  one or more Usenet servers and an Unseenet node.
- **Usenet side:** the Usenet server(s) the gateway exchanges news with,
  by peering or as a reader.
- **Gatewayed group:** an Unseenet group that mirrors one Usenet group.
- **Import:** taking a Usenet article into a gatewayed group.
- **Export:** sending an Unseenet article to Usenet.
- **Group key:** the identity that owns a gatewayed group.
- **Gateway key:** the identity the gateway posts and approves with.
- **Gateway host:** the machine the gateway runs on. It has a public
  network presence on the Usenet side.

# 3. Gatewayed Groups

## 3.1 Names

The gatewayed group for the Usenet group `N` is named `usenet.` followed
by `N` in lower case. `dk.politik` becomes `usenet.dk.politik`;
`comp.lang.python` becomes `usenet.comp.lang.python`.

If the result is not a valid name (UN-RFC 0004 section 1: characters,
or more than 128 octets), the Usenet group MUST NOT be gatewayed. Two
Usenet groups that differ only in case map to the same name; a gateway
MUST gateway at most one of them.

The `usenet` prefix keeps imported groups apart from Unseenet's own
`alt.*`, `dk.*` and reserved Big 8 hierarchies, and makes the origin of
every gatewayed group visible in its name.

## 3.1.1 Other Networks

This is the general rule for gateways: groups carried from another
network live under a top-level hierarchy named after that network, and
Unseenet's own groups never carry a prefix. A gateway to FidoNet
echomail, for example, would use `fido.*`. Each such network is
specified in its own UN-RFC, which defines the name mapping and the
value of `network` in the manifest (section 3.2). This document reserves
`fido` for that purpose (section 10).

## 3.2 Manifest

A gatewayed group:

- MUST be of type `moderated` (UN-RFC 0004 section 2);
- MUST be owned by a group key, and SHOULD list the gateway key as its
  only moderator. The group key SHOULD be kept offline, so that a
  compromised gateway host can be replaced by a new manifest naming a
  new gateway key (UN-RFC 0004 section 3.2);
- MUST carry a `gateway` object in its manifest (below);
- for export, MUST name a `submissions` inbox owned by the gateway key
  (UN-RFC 0009 section 3).

The `gateway` field:

| Field       | Type       | Req. | Meaning                                              |
|-------------|------------|------|------------------------------------------------------|
| `network`   | string     | yes  | `usenet`                                             |
| `group`     | string     | yes  | The Usenet group name, exactly as on Usenet          |
| `direction` | string     | yes  | `import` or `both`                                   |
| `host`      | string     | yes  | The gateway's Usenet path identity (RFC 5536 section 3.1.5) |
| `operator`  | key string | yes  | The operator's identity key                          |
| `contact`   | Group ID   | yes  | The operator's contact inbox (UN-RFC 0011 section 5) |
| `abuse`     | string     | if `both` | An abuse address reachable from Usenet (e-mail) |
| `policy`    | string     | no   | Free text, at most 2048 characters: what is filtered, kept and logged |

Nodes that do not know this field preserve and ignore it (UN-RFC 0004
section 3.1), so they carry gatewayed groups like any moderated group.

## 3.3 Endorsement

`usenet` is a governed hierarchy (section 10). Its maintainer endorses
at most one gatewayed group per Usenet group (UN-RFC 0018 section 5).
Anybody may still run their own gateway for the same Usenet group; their
group will have the same name with a different fingerprint and be shown
as unendorsed (UN-RFC 0018 section 8.1).

A maintainer SHOULD endorse a gateway only when its operator has agreed
to the duties in section 6 and, for `both`, has shown that the Usenet
side accepts its exports.

# 4. Import

## 4.1 What Is Imported

A gateway imports only articles that are, after the conversion in 4.2,
plain text within Unseenet's size limit. It MUST NOT import:

1. control messages (`Control` header, or a `Subject` starting with
   `cmsg `), including `newgroup`, `rmgroup`, `checkgroups` and `cancel`;
2. articles whose Message-ID ends in `@unseenet>` (section 5.3: these
   came from Unseenet and are already there);
3. articles containing binary data: yEnc, uuencode, or MIME parts other
   than `text/plain` that are not a signature or a short alternative;
4. articles larger than 64 KiB after conversion (UN-RFC 0002 section 1),
   or larger than the receiving node accepts;
5. articles the gateway's spam filter rejects. A gateway SHOULD filter
   at least as strictly as a well-run Usenet text server (for example
   with Cleanfeed or an equivalent).

A gateway imports only the Usenet groups it has gatewayed groups for.
It MAY import only articles newer than the time the gatewayed group was
created.

## 4.2 Conversion

The gateway builds a new Unseenet article (UN-RFC 0002) for each
imported Usenet article:

| Unseenet header       | Value                                                          |
|-----------------------|----------------------------------------------------------------|
| `Newsgroups`          | The gatewayed group's Group ID                                 |
| `Date`                | Time of import, rounded down to 10 minutes (UN-RFC 0002 section 2.5) |
| `From`                | The display name of the Usenet `From`, or its local part if there is none, at most 128 characters |
| `Subject`             | The Usenet `Subject`, at most 256 characters                   |
| `Author-Key`          | The gateway key                                                |
| `References`          | Section 4.3                                                    |
| `Content-Type`        | `text/plain; charset=utf-8`                                    |
| `Usenet-Message-ID`   | The Usenet Message-ID, unchanged                               |
| `Usenet-Date`         | The Usenet `Date`, unchanged                                   |
| `Usenet-From`         | The Usenet `From`, unchanged                                   |
| `Usenet-Newsgroups`   | The Usenet `Newsgroups`, if it names more than one group       |
| `Usenet-References`   | The Usenet `References`, if any reference could not be mapped  |
| `Usenet-Followup-To`  | The Usenet `Followup-To`, if present                           |

Headers that are folded on Usenet are unfolded. Header values that still
break UN-RFC 0002 section 1 (control characters, over-long values) are
truncated or the article is not imported. All other Usenet headers,
including `Path`, `Xref`, `NNTP-Posting-Host`, `Injection-Info` and
`Organization`, are dropped.

The body is decoded from its transfer encoding and charset to UTF-8. If
it cannot be decoded, the article is not imported. Of a MIME multipart
article only the first `text/plain` part is kept.

The gateway signs the article with the gateway key and pays its postage
(UN-RFC 0006). Because the gateway key is the group's moderator, the
article is accepted without `Approved-By` (UN-RFC 0004 section 5).

The original `Date` is kept in `Usenet-Date` rather than `Date`, because
Usenet dates are unchecked and often outside the window nodes accept.
Clients that know this document SHOULD show `Usenet-Date` and
`Usenet-From` for gatewayed articles.

## 4.3 References and Threads

The gateway keeps a table from Usenet Message-IDs it has imported to the
Unseenet Message-IDs it created, and from Unseenet Message-IDs it has
exported to their Usenet Message-IDs (section 5.2).

For each Usenet `References` entry, the gateway puts the mapped Unseenet
Message-ID into `References`, in the same order. An entry of the form
`<id@unseenet>` maps to `<id@unseenet>` itself. Entries that cannot be
mapped are left out, and the original header is then kept in
`Usenet-References` so that a later import can still thread correctly.

## 4.4 Crossposts

Unseenet does not allow crossposting (UN-RFC 0002 section 2.1). A Usenet
article posted to several groups is imported **once**, into the
gatewayed group of the first group in its `Newsgroups` that this gateway
gateways, and the full list is kept in `Usenet-Newsgroups`.

## 4.5 Cancels, Supersedes and No-Archive

Usenet cancels are not authenticated. A gateway MAY act on a Usenet
`cancel` or `Supersedes` according to its stated policy, for example
only for cancels issued by the server named in the target's
`Injection-Info`. When it does, it posts an Unseenet cancel (UN-RFC 0004
section 7) for the imported article, as moderator; for `Supersedes` it
then imports the new article.

An article with `X-No-Archive: yes` or `Archive: no` MUST either not be
imported or be given `Expires` at most 7 days after import. Archive
nodes (UN-RFC 0012) MUST NOT keep a gatewayed article past its
`Expires`.

A gateway SHOULD act on requests by the author of an imported article to
remove it, by posting a cancel. Such requests reach the operator's
`contact` inbox or `abuse` address.

# 5. Export

Export is OPTIONAL and happens only in groups whose manifest says
`"direction": "both"`.

## 5.1 Submitting

A user posts to a gatewayed group exactly as to any moderated group: the
client builds and signs the article and sends it to the `submissions`
inbox (UN-RFC 0009 section 3). The article keeps the author's own key
and signature.

Before submitting to a gatewayed group, a client that knows this
document MUST tell the user, once per group, that:

- the article will be published on Usenet, outside Tor, to servers that
  keep articles for years and that the user cannot ask to delete;
- it will carry the display name, the key fingerprint and the text;
- the gateway operator, not the user, decides whether it is sent.

## 5.2 Checking and Sending

For each submission the gateway:

1. performs the checks a moderator's client must perform (UN-RFC 0009
   section 3);
2. applies its export policy (section 6.2); a refused submission is
   dropped, and the gateway MAY reply to the submitter's `Reply-Inbox`
   with a short reason;
3. converts the article (section 5.3) and offers it to the Usenet side;
4. only after the Usenet side has accepted it (NNTP `240` or `235`),
   approves the original article and posts it to the gatewayed group
   (UN-RFC 0004 section 5). Its Message-ID is unchanged.

If the Usenet side refuses the article, the gateway MUST NOT approve it,
so that an article never appears in a gatewayed group without also
being on Usenet. A gateway SHOULD wait a random time before step 3
(RECOMMENDED: uniformly 0 to 10 minutes), so that the time of injection
says little about when the author submitted.

## 5.3 Conversion

The gateway builds a Usenet article (RFC 5536) from the Unseenet article:

| Usenet header     | Value                                                            |
|-------------------|------------------------------------------------------------------|
| `Path`            | `<host>!not-for-mail`, where `<host>` is the manifest's `host`   |
| `Message-ID`      | The Unseenet Message-ID, unchanged: `<id@unseenet>`              |
| `Newsgroups`      | The manifest's `group`. Never more than one group.               |
| `Date`            | The Unseenet `Date`                                              |
| `From`            | `"<From> (<fp4>)" <<fingerprint>@unseenet.invalid>`, where `<fp4>` is the first 4 characters of the author's fingerprint |
| `Subject`         | The Unseenet `Subject`                                           |
| `References`      | Each entry mapped back: an imported article's `Usenet-Message-ID`, otherwise the Unseenet Message-ID unchanged |
| `Injection-Info`  | `<host>; posting-account="<fingerprint>"; mail-complaints-to="<abuse>"` (RFC 5536 section 3.2.8) |
| `Content-Type`    | `text/plain; charset=utf-8`                                      |
| `Unseenet-Author-Key` | The author's `Author-Key`                                    |

No other Unseenet header is exported. In particular `Signature`,
`Proof-Of-Work`, `Approved-By` and `Approval` are dropped: Usenet readers
cannot verify Unseenet signatures, and `Unseenet-Author-Key` is
informational only.

Keeping the Message-ID means:

- replies on Usenet reference `<id@unseenet>`, which import maps to the
  original without a table (section 4.3);
- the copy that comes back through the Usenet feed is not imported
  (section 4.1 item 2), so there are no loops;
- two gateways that export the same submission produce the same
  Message-ID, and Usenet's own history drops the second.

A `.invalid` address (RFC 2606) cannot receive mail. Replies by e-mail
are impossible; replies on Usenet reach the author through import.

## 5.4 What Is Never Exported

A gateway MUST NOT export:

- articles from any group other than the gatewayed group they were
  submitted to;
- articles from closed groups, inbox groups or local groups, or any
  encrypted article;
- control articles, including cancels: a cancel in Unseenet does not
  reach Usenet (but see section 6.2 for the operator's own cancels);
- articles whose body is not plain text, or that exceed the Usenet
  side's size limit.

# 6. Duties of a Gateway Operator

## 6.1 Both Directions

An operator:

- MUST keep the `contact` inbox read, and act on removal requests
  (section 4.5);
- MUST state in `policy` what is filtered and what is logged;
- MUST NOT import from or export to a Usenet server against that
  server's terms. Reading a server as an ordinary user and re-publishing
  its groups may itself be against its terms; peering by agreement is
  RECOMMENDED;
- SHOULD tell the Usenet side's administrators that the peer or account
  is a gateway to Unseenet, and point them to this document.

## 6.2 Export

To Usenet, the gateway is the injecting server for every exported
article, and Usenet holds injecting servers responsible: servers that
inject spam or abuse lose their peers. Unseenet gives the gateway no IP
address or account to act on, only the author's key. An operator that
exports therefore:

- MUST publish a working `abuse` address and answer complaints;
- MUST be able to stop an author: by banning the key in the group's
  manifest (UN-RFC 0004 section 5.1), which is public and stops all
  gateways using that manifest, or by refusing the key's submissions
  locally;
- MUST keep, for as long as the exported articles are likely to be
  retained on Usenet, which key wrote each exported Message-ID. This
  record is pseudonymous: it says which key wrote an article, never who
  holds the key or where the article came from. It is public anyway
  through `Unseenet-Author-Key`;
- MUST NOT try to learn more about authors than their key, for example
  by asking for contact details or by logging anything about the node
  or circuit a submission arrived through. A gateway that did would
  undo the anonymity Unseenet exists to give;
- MUST make this plain to the Usenet side before exporting: the gateway
  can stop a key, but cannot identify or trace a person;
- MAY cancel on Usenet an article it exported, as its injecting server,
  for example after a complaint or at the author's request;
- MUST limit the rate of exports per key, and SHOULD limit it per group;
- SHOULD require more postage on submissions than the group's `min_pow`
  (RECOMMENDED: at least 24 bits), and MAY refuse keys it has not seen
  in the network for some time, since keys cost nothing to make;
- SHOULD apply the same spam filter to exports as to imports.

## 6.3 The Gateway Host

The gateway host is reachable on the Usenet side, normally on the open
Internet, often with a static address and a DNS name in `host`. It is
not hidden, and nothing in this document tries to hide it.

- A gateway host MUST NOT also run an Unseenet node whose location is
  meant to be hidden. Exchanging traffic between the two on one machine,
  or one operator running both with matching uptime, links the hidden
  node to a public address.
- The gateway talks to Unseenet like a client: over Tor, to one or more
  nodes, with no special status. Nodes need not know which of their
  clients is a gateway.
- A public "backbone" node whose operator does not need location hiding
  (for example one using single onion service mode) MAY share a host
  with a gateway.

# 7. Nodes

A node carries a gatewayed group like any moderated group. It needs no
support for this document. A node operator MAY decide not to carry the
`usenet` hierarchy at all, for example because the operator does not
want to store content from outside the network; this is the ordinary
choice of what to carry (UN-RFC 0004 section 3.3).

A node that knows this document MAY show gatewayed groups separately in
`LIST` output intended for its own users.

# 8. Clients

A client that knows this document SHOULD:

- mark gatewayed groups as such, with the Usenet group name and the
  gateway's `host`;
- show `Usenet-From` and `Usenet-Date` for imported articles, and make
  clear that their author has no Unseenet identity and that the gateway
  key, not the author, signed them;
- for `"direction": "import"`, not offer to post;
- for `"direction": "both"`, give the warning of section 5.1 before the
  first submission.

A client that does not know this document shows imported articles as
posts by the gateway key with the original author's name in `From`. That
is misleading but not wrong, which is why the gateway key's profile
(UN-RFC 0022) SHOULD make the situation plain, for example by naming
itself "Usenet gateway".

# 9. Headers Defined Here

| Header                | In       | Defined in  |
|-----------------------|----------|-------------|
| `Usenet-Message-ID`   | Unseenet | section 4.2 |
| `Usenet-Date`         | Unseenet | section 4.2 |
| `Usenet-From`         | Unseenet | section 4.2 |
| `Usenet-Newsgroups`   | Unseenet | section 4.2 |
| `Usenet-References`   | Unseenet | section 4.2 |
| `Usenet-Followup-To`  | Unseenet | section 4.2 |
| `Unseenet-Author-Key` | Usenet   | section 5.3 |

The Unseenet headers are ordinary optional headers (UN-RFC 0002 section
2.3) and are covered by the gateway's signature. Nodes preserve them
without knowing this document.

# 10. Changes to Other Documents

- UN-RFC 0018 section 9: the initial root list gains `usenet`,
  `governed`, maintainer the project key, title "Gateways to Usenet".
  The project MAY later delegate it. It also gains `fido`, `reserved`,
  for a future gateway to FidoNet (section 3.1.1).
- UN-RFC 0004 section 3.1: manifests of gatewayed groups carry the
  `gateway` field of section 3.2. No change is needed in nodes, which
  already preserve unknown fields.
- UN-RFC 0012: archive nodes honour `Expires` on gatewayed articles
  (section 4.5).

# 11. Rationale

- **Why a separate hierarchy instead of importing `dk.politik` as
  `dk.politik`?** Unseenet's `dk.*` is free and already in use, and the
  Big 8 names are reserved for communities that want to revive them in
  Unseenet (UN-RFC 0018 section 9). Mixing imported and native groups
  under one name would give readers two groups called `dk.politik` with
  different rules, authors and lifetimes. `usenet.*` says where a group
  comes from.
- **Why a prefix for foreign groups and not for Unseenet's own?**
  Unseenet is the home network, so its groups get the short names
  (`dk.snak`, not `unseenet.dk.snak`). Groups from elsewhere are guests,
  and their prefix says where they come from. One prefix per network
  keeps the rule the same for every gateway to come.
- **Why moderated groups with the gateway as moderator?** It is the only
  existing group type in which one key can post on behalf of others
  while users can still submit. Export then needs no new mechanism: the
  submission queue and approvals already exist, and an exported article
  keeps its author's signature inside Unseenet.
- **Why approve only after Usenet accepted?** A gatewayed group should
  show the same conversation as the Usenet group. An article that only
  exists on one side splits the thread.
- **Why not sign imported articles with per-author keys?** The gateway
  would hold keys for people who never chose to be in Unseenet, and the
  signatures would claim more than the gateway knows. One gateway key
  says exactly what is true: "this gateway saw this on Usenet."
- **Why keep `<id@unseenet>` as the Usenet Message-ID?** It makes loop
  prevention and threading stateless, and lets several gateways export
  the same article without duplicates.
- **Why can't a gateway keep a "log of who posted what"?** Usenet
  servers are trusted to know their users' accounts or addresses so that
  abuse can be traced. A gateway does not know them and must not: a
  submission reaches it through Tor and an inbox, signed by a key that
  costs nothing to make. What it can offer instead is control: it can
  refuse a key, ban it in public, raise the postage and limit the rate.
  This is the same bargain the anonymous mail-to-news gateways offered
  Usenet, and Usenet servers have been free to accept or filter them.
- **Why `.invalid` addresses?** Unseenet identities have no mail
  address, and inventing a deliverable one would invite spam to a
  domain that cannot handle it. RFC 2606 reserves `.invalid` for
  exactly this, and many Usenet servers already accept it.

# 12. Security and Privacy Considerations

- **Exported articles leave Tor.** They are copied to Usenet servers
  that keep them for years, index them, and do not honour Unseenet
  cancels. The author's fingerprint and display name go with them, which
  links the author's Usenet posts to everything else the same key has
  posted in open Unseenet groups. Authors who care SHOULD use a separate
  identity for gatewayed groups (UN-RFC 0003 section 2). Clients MUST
  warn (section 5.1).
- **Timing.** The gateway injects an article some time after the author
  submitted it. The submission travels through Tor to an inbox, and the
  gateway adds a random delay (section 5.2), so the injection time says
  little about where or when the author was online. It is still a public
  timestamp, close to the time of writing.
- **The gateway sees every submission in plain text.** Submissions are
  sealed to the gateway key, as to any moderator. The gateway, and anyone
  who seizes the gateway host, can read submissions that were refused.
  Operators SHOULD delete refused submissions.
- **The gateway can lie.** It signs imported articles, so it can alter,
  invent or drop them, and readers can only check them against Usenet.
  Endorsement (section 3.3) is the defence: readers trust the endorsed
  gateway, and anybody may run a second gateway to compare.
- **Imported content is not filtered by Unseenet postage.** A gateway
  pays postage for everything it imports, so a Usenet flood becomes CPU
  load on the gateway, not on nodes, but it still fills nodes. Gateways
  MUST filter (section 4.1) and SHOULD cap imports per group per day.
- **Legal exposure.** The gateway operator republishes third-party
  content into Unseenet and, for export, injects anonymous content into
  Usenet under their own host name. Gateways are therefore best run by
  people or organisations willing to be publicly responsible, much like
  the operators of public mail-to-news gateways in the past. Personal
  data in imported articles (names, addresses, signatures) is subject to
  the operator's local law; section 4.5 provides removal.
- **Binary content** is excluded in both directions (sections 4.1 and
  5.4). Gatewaying binary groups would turn Unseenet into a file
  distribution network, which UN-RFC 0002 section 8 rules out.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
