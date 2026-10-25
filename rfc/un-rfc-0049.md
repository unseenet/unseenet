```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0049                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0000, 0002, 0005, 0023, 0032, 0034

            Unseenet: Imported Posts and the Time of Posting
```

# Abstract

People who come to Unseenet bring years of posts and pictures from other
networks. This document lets them bring them along without letting
anyone post into the past. An article's `Date` is always the time it was
posted to Unseenet, and nodes now enforce that for everything their own
clients post. When an article was first published elsewhere, its author
says so in `Origin-*` headers, already defined for gateways, and the
original date is shown and used for order, but never for retention,
postage or what counts as new. One rule, *old on arrival*, keeps
imported articles and late gatewayed messages out of notifications and
For you.

# 1. Motivation

An importer (section 6) takes the export a person downloads from
Facebook, X, Mastodon or another network and turns it into their
Unseenet profile, feed and site. A post written on 3 August should say
"3 August", not the day it was imported.

But `Date` cannot simply be set to 3 August:

- everything that keeps the network healthy counts from `Date`: the
  replication window and retention (UN-RFC 0012), the history that
  prevents loops (UN-RFC 0005 section 5.4), postage and ripening
  (UN-RFC 0006, 0025), quotas (UN-RFC 0027) and what clients show as
  new;
- a post dated 85 days back in a group with 90 days' retention would
  disappear after five days;
- and if `Date` may lie in the past, anyone may claim to have said
  something before they did.

Today only the future is closed: UN-RFC 0002 section 2.5 rejects a
`Date` more than one hour ahead, and UN-RFC 0012 section 3 rejects one
older than the window. Inside the window a client can choose any date in
the past. This document closes that, and gives the original date its
own place.

Gateways solved half of this already: UN-RFC 0023 section 4.2 uses the
time of import as `Date` and keeps the other network's date in
`Origin-Date`. This document makes that the rule for every import, by a
gateway or by the author, and says what clients do with it.

# 2. Terms

**Time of posting**
:   An article's `Date`: when it was posted to Unseenet (section 3).

**Origin date**
:   When the article was first published in another network, as its
    `Origin-Date` says (section 4). A claim, not a fact any node checks.

**Imported article**
:   An article that carries `Origin-Network` (section 4): it was first
    published somewhere else. Brought in either by a gateway (UN-RFC
    0023) or by its own author (a *self-import*).

**Importer**
:   A program that makes self-imports from a person's export (section 6).

**Old on arrival**
:   An imported article whose origin date is more than 24 hours before
    its time of posting (section 5.2).

# 3. No Posting into the Past

## 3.1 Clients

A client MUST set `Date` to the time it posts the article, rounded down
to 10 minutes (UN-RFC 0002 section 2.5). A client that keeps articles to
post later (offline, a queue, an importer) sets `Date` when it actually
posts them, not when they were written.

## 3.2 Nodes Accepting a POST

A node that receives an article by `POST` (UN-RFC 0005 section 4) MUST
reject it with `441 date` if its `Date` is more than **1 hour in the
past**, as it already does for one more than 1 hour in the future. A
`POST` therefore comes from a client posting now.

There is one exception. An article with `Approved-By` (UN-RFC 0004
section 5) is posted by a moderator, who may approve it days after the
author wrote it (UN-RFC 0009 section 3). Its `Date` stays the author's,
so its Message-ID and the replies to it stay valid, and the node checks
it against the window of UN-RFC 0012 only. The moderator is trusted with
the group already, and an approval is visible as one.

## 3.3 Peering

Articles received from peers (`IHAVE`, `CHECK`/`TAKETHIS`) are checked
against the window as before (UN-RFC 0012 section 3). They legitimately
arrive late: random delays (UN-RFC 0005 section 5.5), nodes that were
offline and catch up (UN-RFC 0017). Section 3.2 is checked where an
article enters the network, not where it passes.

## 3.4 Posting Again

Because Message-IDs are content-derived, a client may repeat a `POST`
safely (UN-RFC 0005 section 4). That still holds within the hour. A
client refused with `441 date` MUST build the article again with a
current `Date`, which gives it a new signature and Message-ID; the same
applies to `441 later` (UN-RFC 0030) when the article is posted again
more than an hour later.

## 3.5 What This Does Not Prevent

A node operator can still accept a backdated article from their own
client, and peers will take it if it is inside the window. Nobody can
tell when an article really entered the network except the node it
entered at, and that node is not trusted (UN-RFC 0001). What section 3.2
gives is that honest nodes refuse it, so backdating needs a dishonest
node and is limited to the window. Section 11 lists recording the time a
node first saw an article as an open issue.

# 4. Origin Headers

## 4.1 For Every Import

The origin headers of UN-RFC 0023 section 4.3 are no longer only for
gateways. Any article first published somewhere else carries them:

| Header           | Gateway import            | Self-import                       |
|------------------|---------------------------|-----------------------------------|
| `Origin-Network` | MUST (UN-RFC 0023 4.3)    | MUST                              |
| `Origin-Date`    | MUST when known, as text  | MUST, RFC 3339 UTC                |
| `Origin-ID`      | MUST                      | MAY (section 4.3)                 |
| `Origin-From`    | MUST when known           | MAY                               |
| `Origin-Proof`   | SHOULD where defined (UN-RFC 0023 4.3.1) | MAY                |

A self-import is signed by its author's own key and posted to the
author's own groups, usually their feed or site (UN-RFC 0034, 0035).
It is not gatewayed: there is no gateway manifest and no gateway key,
and the article is the author's in every way, including editing
(UN-RFC 0042) and withdrawal.

`Origin-Network` takes the network names gateways use (UN-RFC 0023
section 3.1) where one exists, otherwise a lowercase name of the
network: `facebook`, `x`, `instagram`, `mastodon`, `bluesky`,
`tiktok`, `nostr`, `matrix`, `usenet`.

## 4.2 Origin-Date

`Origin-Date` says when the article was first published in the other
network. For a self-import it MUST be an RFC 3339 UTC time; a gateway
copies it as text, as UN-RFC 0023 says. It MUST NOT be later than the
article's `Date`. A client ignores an `Origin-Date` it cannot read or
that is later than `Date`, and treats the article as if it had none.

It is the author's claim. Nobody can check what Facebook showed on 3
August, and clients MUST show it as a claim (section 5.1), never as
the time of posting.

## 4.3 Origin-ID for Self-imports

An identifier from the other network ties the Unseenet key to that
account for anyone who can look it up. A person importing their posts
has usually chosen that link already, by their name and picture, but
not always. An importer therefore leaves `Origin-ID` out unless the
person chooses to keep it, and keeps what it needs to avoid importing
the same post twice on the person's machine instead (section 6.3).

# 5. Clients

## 5.1 Showing

A client that knows this document SHOULD show an imported article with
its network and origin date, for example "Imported from Facebook ·
originally 3 August 2026", and the time of posting where details are
shown. For a self-import it MUST NOT suggest that the article came from
a gateway: the author signed it (UN-RFC 0023 section 8 is for gatewayed
groups).

## 5.2 Old on Arrival

An imported article is *old on arrival* when its `Origin-Date` is more
than 24 hours before its `Date`. A client:

- MUST NOT raise a notification for it, or add it to For you, unless
  it mentions the reader in a way UN-RFC 0032 covers (and an importer
  sends no mention notices, section 6.2);
- SHOULD NOT count it as new or unread in a group's or the timeline's
  counters;
- shows it as any other article once the reader opens the group.

The same rule covers gatewayed articles: a Usenet article fetched a week
late, or a Matrix room's history brought in when a gateway starts, is
old on arrival. Messages from a live gateway are not, because their
origin date is within minutes of their time of posting.

## 5.3 Order

Where articles are ordered by time, a client orders an imported article
by its origin date and every other article by `Date`:

- in a feed and in the timeline (UN-RFC 0034 sections 4.1 and 7), so
  imported posts sit where they belong in the author's history instead
  of on top of every follower's timeline;
- in a thread, by the same key, so replies made on the other network
  keep their order.

Retention, expiry, the replication window, postage, ripening, quotas and
anything a node does still use `Date` only.

# 6. Importers

An importer is a client (or part of one) that makes self-imports. This
section says what it must do. The program the project makes is
`unseenet-import`; others may make their own.

## 6.1 On the Person's Own Machine

An importer MUST read the person's exports, and keep its drafts, on the
person's own machine. It MUST NOT send an export, a draft or anything
from them to a node, an entrance or any other server; what leaves the
machine is only the articles the person chooses to post, posted the way
any client posts. A web form of an importer runs in the browser
(UN-RFC 0043), with the same rule.

Drafts and exports SHOULD be stored encrypted with a key from the
person's vault (UN-RFC 0007), and SHOULD NOT be stored in the vault
itself, which travels to other devices. The importer SHOULD offer to
delete them when everything is posted.

## 6.2 What Is Imported

- Only the person's **own** content: their posts and the pictures and
  files they published themselves, their profile fields and picture.
- **Never** other people's content: comments, posts on the person's
  wall by others, messages, friend and follower lists, tags of others,
  pictures others published. Once posted, nobody can remove them from
  the network, and they are not the person's to post.
- Pictures SHOULD have their metadata (location, camera, times)
  removed by default (UN-RFC 0027).
- An importer MUST NOT send mention notices (UN-RFC 0032) for imported
  articles. Names from the other network are not Unseenet identities.
- The person sees and chooses what is posted. An importer SHOULD show
  how it will look in the profile, the feed and the site before
  anything is posted.

## 6.3 Several Sources and Imports Again

An importer MAY merge several sources into one profile, feed and site,
and MAY be run again later. It SHOULD recognize a post it has already
imported, or one that appears in two sources, and import it once. It
does so from what it keeps locally and from the person's existing
articles (`Origin-Network` with `Origin-ID` where kept, otherwise
`Origin-Date` and body), never by asking a server.

## 6.4 Pace

A new key is slow and dear to post with (UN-RFC 0025), and nodes limit
files per key and per day (UN-RFC 0027 section 8.1). An importer posts
through the shared client core like any client (so postage, ripening and
quotas are applied the same way), newest first, and spreads the rest
over as many days as those limits need. It SHOULD tell the person how
long that will take, and keeps what remains on the machine until it is
posted. Because `Date` is the time of posting (section 3.1), each
imported article lives its group's full retention from then.

# 7. Gateways

Nothing changes in how a gateway builds an article (UN-RFC 0023 section
4.2): `Date` is the time of import and the other network's date is in
`Origin-Date`. A gateway posts to its node like any client, so section
3.2 applies to it, and section 5 now tells clients what to do with what
it already sends.

# 8. Changes to Other Documents

- **UN-RFC 0002** section 2.5: `Date` is the time of posting (section
  3.1); nodes reject a `POST` more than 1 hour in the past (section
  3.2). Section 2.3: the origin headers of UN-RFC 0023 section 4.3 may
  appear on any article (section 4).
- **UN-RFC 0005** section 4: `441 date` also answers a `POST` whose
  `Date` is more than 1 hour in the past, except an approved article
  (section 3.2); posting again after an hour means a new article
  (section 3.4).
- **UN-RFC 0023** section 4.3: the origin headers are defined for every
  imported article, by gateways and by authors (section 4.1); section
  8: clients also apply section 5 of this document.
- **UN-RFC 0032**: an importer sends no mention notices (section 6.2);
  an article old on arrival is not added to For you (section 5.2).
- **UN-RFC 0034** sections 4.1 and 7: an imported entry is ordered by
  its origin date (section 5.3).
- **UN-RFC 0000** section 6: 0049 is added to the index.

# 9. Rationale

- **Why not let `Date` be the original date?** Everything the network
  counts, it counts from `Date` (section 1). Two meanings in one header
  would let an import, or anyone, decide how long an article lives and
  what it costs.
- **Why check only at POST?** That is where an article enters the
  network, so it is the only place the real time is known. After that,
  lateness is normal.
- **Why one hour?** Clients round down to 10 minutes, clocks drift, and
  posting over Tor through an entrance takes time. The future limit was
  already one hour, and the same number either way is easy to
  remember.
- **Why may approved articles keep an old `Date`?** Approval keeps the
  Message-ID (UN-RFC 0009 section 3) so that replies stay valid; a new
  `Date` would break that. The approval itself is visible.
- **Why order by the origin date when it is only a claim?** It changes
  where a post sits in a list, nothing else: not how long it lives, what
  it cost or who is notified. A false claim makes a post look older and
  sink, which helps nobody. And it is what readers expect: an imported
  post from August belongs among August's posts.
- **Why 24 hours for old on arrival?** Live gateways deliver within
  minutes and a slow one within hours; a day separates "late" from
  "history" without counting carefully.
- **Why not a separate header for self-imports?** Gateways already
  define what readers need. One set of headers means one way to show
  them in every client.

# 10. Security and Privacy Considerations

- **The link to another account.** A self-import with a name, a picture
  and posts ties the key to a person on another network for good.
  Importers MUST say so before anything is posted, and leave `Origin-ID`
  out unless chosen (section 4.3). People who need to hide should not
  import.
- **Pictures** carry location and device data; section 6.2 removes it
  by default.
- **Others' content** is never imported (section 6.2), because nobody
  can withdraw it from all nodes again.
- **Exports never leave the machine** (section 6.1). A server that
  received them would see a person's whole history and could link it
  to the key that posts it, which is exactly what nodes and entrances
  must never know.
- **False origin dates** are possible and cannot be detected; clients
  show them as claims (section 4.2). `Origin-Proof` lets networks that
  sign their messages prove them.
- **Backdating by a dishonest node** remains possible inside the window
  (section 3.5).

# 11. Open Issues

- **Time first seen.** A node could record when it first saw an
  article, and show it to its own clients, so that an article whose
  `Date` is much earlier than any node saw it is visible. It reveals
  something about where an article entered, so it needs care.
- **Proofs for self-imports.** Networks that sign posts (Nostr,
  Bluesky) could let an importer carry `Origin-Proof`, so a reader can
  check the post is real and its date honest. Which networks, and how,
  is left to the importer's profiles.
- **Sites from other networks.** Section 6 covers posts and profiles.
  Pages imported into a site (UN-RFC 0035) may want an origin date per
  page.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
