```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0063                                              October 2026
Category: Standards Track
Status: Draft
Implemented: -
Updates: 0000, 0055, 0061

            Unseenet: The UN-RFC Series in the Network
```

# Abstract

The UN-RFCs are the authority over Unseenet, not any implementation
(UN-RFC 0000). Yet today the series lives in one project's repository
on one company's service, and a change is accepted when the maintainer
merges it. This document moves the series into the network itself:

- anybody, with a ripened key and without saying who they are, posts a
  **draft** in an open group, and discussion is replies to it;
- a **council** (UN-RFC 0054) publishes a draft as a numbered UN-RFC
  through a proposal with a public hearing (UN-RFC 0061), so objections
  can stop it;
- the published texts are posted by the council's replicas with
  identical bodies, kept by every node, and checkable by every client.

The repository's `rfc/` directory becomes a mirror of the network.

# 1. Motivation

The protocol is what lets independent nodes and clients work together,
and whoever controls its text controls the network in the long run.
While the text is files in one repository:

1. the maintainer, or whoever holds or takes the account, decides every
   change;
2. writing a draft needs a GitHub account, which needs an e-mail address
   and an identity GitHub accepts;
3. if the project or its account disappears, the series has no home and
   no way to change.

Everything else that has to outlive the project - the lists, the
registrar, the update channels - now runs in the network under councils
(UN-RFC 0020, 0054, 0062). The text that defines all of them should too.

# 2. Terms

- **Series council:** the council that keeps a series. For the project's
  series it is the council that keeps the lists (UN-RFC 0020 section 10),
  so the network has one body to watch, not several.
- **Draft:** a text posted in the drafts group (section 4), not yet
  published or not yet published in this form.
- **Text hash:** `b32( H( DS("UNSEENET-RFC-TEXT-1") || text ) )` of a
  document's full text in UTF-8, the first 26 characters.
- **Published text:** the current text of a numbered UN-RFC, posted in
  the series group (section 6).

The key words "MUST", "SHOULD" and "MAY" are as in UN-RFC 0000
section 2.

# 3. The Groups

A series council's manifest gains a field `series`:
`{"drafts": <Group ID>, "published": <Group ID>}`.

| Group | Kind | Holds | Who posts |
|-------|------|-------|-----------|
| drafts (`unseenet.rfc.drafts`)  | open    | Drafts, replies to them, interop reports | anybody with a ripened key |
| published (`unseenet.rfc`)      | channel council group | Published texts | the council's replicas |

Proposals and objections about the series use the council's proposals
group, and talk about the process its talk group (UN-RFC 0061
section 3). Both series groups are endorsed groups of `unseenet.*`, which
every node carries (UN-RFC 0055 section 4.1). The drafts group's
`min_pow` SHOULD be that of the proposals group, and a draft's
`Author-Key` MUST be ripened to the council's `min_level` (UN-RFC 0025).

# 4. Drafts

A draft is an article in the drafts group with

- `Subject: draft <name> <rev>`, where `<name>` is lower-case letters,
  digits and hyphens, at most 40 characters, chosen by the author (for
  example `scribes`), and `<rev>` counts from 1;
- `Content-Type: text/markdown; charset=utf-8`;
- `Draft-Text: <text hash>` of the full text;
- `Draft-Previous: <text hash>` of the revision it replaces, if any;
- a body that is the full text, with the header block of UN-RFC 0000
  section 3.4 and `UN-RFC: draft-<name>` in place of a number.

A draft that changes a published UN-RFC is its full new text, with the
document's number in its header block, and `<name>` is that number.

A text longer than fits one article (UN-RFC 0002) is posted as parts:
`Subject: draft <name> <rev> part <i>/<n>`, each part at most 60 000
octets of text, split at line ends, all with the same `Draft-Text`. The
text is the parts joined in order.

Names are not property: two authors may use the same name, and the text
hash, not the name, says which text a proposal means. Discussion is
replies to a draft (`References:`), as in any group; a reader sees a
draft, its revisions and what was said about it in one thread.

**Interop reports.** An article with `Subject: interop <number>`
states that two implementations interoperate on UN-RFC `<number>`. Its
JSON body names the implementations and their versions, and it is
posted, with identical bodies, by a key of each implementation's
publisher (UN-RFC 0062 section 3).

# 5. Publishing

A draft is published by a proposal (UN-RFC 0061 section 4) whose
`change` is

```
{"rfc": {"action": "publish" | "replace" | "obsolete",
         "text": <text hash>, "number": <integer>}}
```

- `publish` gives a draft a number: `number` is omitted, and the number
  is the lowest above every number published or proposed for publishing
  before it, in the order the proposals counted. The published text is
  the draft's text with `UN-RFC: draft-<name>` replaced by the four-digit
  number - the only change, which anybody can check.
- `replace` makes `text` the published text of `number`: an amendment
  while the document is Draft, a change of its `Status:` line (UN-RFC
  0000 section 3.3), or an erratum.
- `obsolete` marks `number` Obsoleted; `text` is the full text with its
  new header, naming what replaces it.

A proposal to make a document **Standard** counts only when the drafts
group holds an interop report for that number by two publishers with
different key lists, neither of them the publisher of the reference
implementation. This keeps "Standard" what UN-RFC 0000 section 3.3.2
says it is, without anybody judging it.

**Editorial proposals.** A `replace` marked `"editorial": true` - a typo,
a broken reference, wording that does not change what anything does -
has a hearing of 3 days and fails when *O* > *F* / 2. Anybody who thinks
it changes substance can stop it with an objection, and then it must be
proposed as an ordinary change.

**The process itself.** A proposal that publishes, replaces or obsoletes
UN-RFC 0000 or this document has a hearing of at least 30 days and
counts only with two thirds of the full members.

# 6. The Published Texts

When a proposal passes, each full member's replica posts the published
text in the series group with `Subject: rfc <number>` (and `part <i>/<n>`
as in section 4), `Draft-Text:` of the draft and `RFC-Text:` of the
published text. The parts of the current text of each number are kept
articles (UN-RFC 0017) of the kind `rfc`, keyed by number and part, so
nodes keep them beyond retention; a newer text of a number replaces the
older as kept.

A text counts as published when at least *Q* different full members have
posted it with identical bodies, as lists do (UN-RFC 0020 section 8).
Clients and tools take the series from the series group: the current
text of each number is the newest that counts.

Older texts leave by retention. Their history stays in the drafts group
for a year and, without end, with scribes (UN-RFC 0020 section 6.4),
whose mirrors of the repository hold every published text.

# 7. The Repository as a Mirror

A mirror tool reads the series group and writes the texts that count to
`rfc/un-rfc-NNNN.md` in the repository, one commit per published text,
naming the proposal that published it. Nothing else changes `rfc/`; the
header check of UN-RFC 0000 section 3.4 runs on drafts before a
proposal, by any member's replica, and its result is posted as a reply.

A GitHub pull request MAY stay as a front door: a bridge posts the
pull request's text as a draft, signed by the author's own key, which
the author's client made. The bridge holds no key of its own.

# 8. Starting

The series council's genesis manifest names, in `import` (UN-RFC 0020
section 9), the current text of every UN-RFC, posted with identical
bodies by the founding members. From the day that import counts, the
series changes only as this document says, and pull requests to `rfc/`
are drafts, not changes.

During the founding period (UN-RFC 0054 section 19) the founder may be
the only full member. Its proposals still stand a hearing of 14 days in
public, and objections can stop them: the founder no longer decides
alone what the protocol is, even before anybody else sits in the
council.

# 9. Domain Separations

UN-RFC 0003 section 3 is extended with `UNSEENET-RFC-TEXT-1`, which
hashes a text (section 2).

# 10. Rationale

- **Why one council for lists and series?** Each council needs people
  who run replicas and watch hearings. While there are few, one council
  that is alive is better than two that are not. A later document can
  give the series a council of its own by `succeeds` (UN-RFC 0054
  section 13.2).
- **Why numbers only on publishing?** In the network nobody hands out
  "the next free number". Drafts are named and identified by hash, as
  Internet-Drafts were; a number is given once, by a rule.
- **Why replies, not pull request comments?** The network is a
  discussion system. A thread under the draft is where the people who
  use Unseenet already are.
- **Why kept articles?** A node that joins next year must find the
  series as it is, not the series of the last year's posts.
- **Why interop reports?** "Standard" means independent code works
  together. Two publishers saying so, with keys that cost something,
  is a fact a replica can check; it needs no judge.

# 11. Security and Privacy Considerations

- **A stolen member key** can post a text that no proposal published.
  It does not count without *Q* identical posts, and the log shows the
  difference (UN-RFC 0061 section 8).
- **Draft spam** costs postage and a ripened key per author.
- **Text swapped under a proposal.** A proposal names a text hash; the
  published text is that text with one defined substitution. Any reader
  can recompute both.
- **Anonymous authors.** A draft is signed by a key, not a person. That
  is intended: a text is judged by what it says, and the hearing is
  public.
- **Scale.** The current series is about 1 MB of text; every node keeps
  it, about as much as a few days of a busy group. The kind `rfc` counts
  against the 256 kept targets of the series group (UN-RFC 0017
  section 2.2); before the series reaches that, a later document splits
  it over several groups. Drafts are ordinary articles under the
  hierarchy's retention.

# 12. What Is Autonomous, and What Is Not Yet (Informative)

When this is built, no key - the project's included - can change the
protocol's text without a public hearing that anybody can stop. While
the founder is the series council's only member, the founder still
writes most proposals; the difference is that they are public, take
time, and can be refused. The series is alive when others propose,
object and sit in the council.

# 13. Changes to Other Documents

- UN-RFC 0000 section 3.1: the series lives in the series group;
  `rfc/` in the repository is its mirror (section 7).
- UN-RFC 0000 section 3.3.1: a change is accepted when its proposal
  passes its hearing, not when a maintainer merges it.
- UN-RFC 0000 section 4: steps 2 to 4 become: post a draft (section 4),
  discuss it in replies, and have a full member propose it (section 5).
- UN-RFC 0000 section 1 gains: an implementation that says it follows
  the series follows the texts that count in the series group.
- UN-RFC 0055 section 4.1: the kept texts of the series are an
  exception to the retention limit, as the chains of UN-RFC 0054 are.
- UN-RFC 0061 section 4: `change` may also be `{"rfc": …}` (section 5).

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
