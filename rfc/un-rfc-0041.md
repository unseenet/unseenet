```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0041                                              October 2026
Category: Standards Track
Status: Draft
Implemented: unseenet 0.4.0
Updates: 0000, 0005, 0022, 0040

                 Unseenet: Fetching Many Manifests at Once
```

# Abstract

Clients look up many small manifests: the profile and picture of every
author they show, and with UN-RFC 0036 the attestation groups of
authors and issuers. ONNTP has no command that returns several
manifests at once, so each lookup costs a `GROUP`, a `HDR` and an
`ARTICLE` over Tor. Opening a busy group with 500 authors then takes
minutes. This document adds `XUN-MANIFESTS`, which returns the current
manifest of up to 256 groups in one answer.

# 1. Motivation

Over Tor a round trip to an onion service takes about a second. A
client that reads the profile of one author today:

1. selects the group (`GROUP profile@<fp>`),
2. finds the manifests in it (`HDR Control <low>-<high>`),
3. fetches each one (`ARTICLE <n>`).

For 500 authors that is 1500 round trips - some 25 minutes, and longer
with pictures. Caching (UN-RFC 0022 section 9.2) helps the second time,
not the first, and not at all on a bootable client that starts with an
empty cache every time. The design target of UN-RFC 0001 section 1.2
is under 10 seconds for a busy group with a fresh cache.

Nothing is needed to *find* these groups: the Group ID of a key-bound
group follows from the key (UN-RFC 0029 section 2), and the client
knows the keys of the authors it shows. What is missing is a way to ask
for many at once.

# 2. The XUN-MANIFESTS Command

## 2.1 Request

```
C: XUN-MANIFESTS
C: <group-id> [<message-id>]
C: <group-id> [<message-id>]
C: ...
C: .
```

Each line names one group by its Group ID - key-bound or ordinary -
and optionally the Message-ID of the manifest of that group the client
already holds (section 3.3). The lines form a multi-line block with
dot-stuffing, as a posted article does. A request holds at least 1 and
at most *max* lines, where *max* is the number the node advertises
(section 2.4); *max* MUST be at least 256. The same Group ID MUST NOT
appear twice.

## 2.2 Answer

```
S: 296 <n> manifests follow
S: <one answer per request line, in the order of the request>
```

where `<n>` is the number of request lines. Each answer is a response
of its own, in the form a reader already knows from `ARTICLE` and
`STAT` (RFC 3977 section 6.2):

| Answer                                  | Meaning                                                  |
|-----------------------------------------|----------------------------------------------------------|
| `220 0 <message-id> <group-id>` then the article, dot-stuffed, ended by `.` | The current manifest of the group  |
| `223 0 <message-id> <group-id>`         | The current manifest is the one the client named; not sent again |
| `411 <group-id>`                        | The node does not carry the group, or it has no current manifest (expired, removed) |
| `431 <group-id>`                        | Not sent in this answer (section 2.3); ask again          |

The article is sent byte-for-byte as stored, as between nodes (UN-RFC
0005 section 3): the node MUST NOT add `Path` or `Xref`, since an
article number has no meaning here (hence the `0`). There is no
closing line after the last answer; the client knows `<n>`.

A request the node cannot accept as a whole is answered with one line
instead of `296`:

| Line                    | Meaning                                                  |
|-------------------------|----------------------------------------------------------|
| `501 <reason>`          | A malformed line, a repeated Group ID, or more than *max* lines |
| `400 <reason>`          | The node is busy or limits this connection (section 5)   |

## 2.3 Size of an Answer

A node SHOULD keep the articles of one answer to at most 1 MiB in total
and MAY use a smaller limit. When the next article would go over it,
the node answers `431` for that line and every line after it. It MUST
send at least the first article that is due, however large, so that a
client always gets on.

The client then asks again for the lines that got `431`, in a new
request. A client that has many groups to ask for may also simply send
several requests one after the other; it need not wait for an answer
before sending the next request (RFC 3977 section 3.5).

## 2.4 Capability

A node that implements the command lists in `CAPABILITIES`

```
UNSEENET-MANIFESTS <max>
```

where `<max>` is the largest number of lines it accepts in one request,
at least 256. A client MUST NOT send more. A client talking to a node without the
capability falls back to single lookups (section 1).

## 2.5 Example

```
C: XUN-MANIFESTS
C: profile@3mf7q...ka <a1b2...@unseenet>
C: profile@9xk2w...7p
C: avatar@9xk2w...7p
C: unseenet.help
C: .
S: 296 4 manifests follow
S: 223 0 <a1b2...@unseenet> profile@3mf7q...ka
S: 220 0 <c3d4...@unseenet> profile@9xk2w...7p
S: Unseenet-Version: 1
S: ...
S: .
S: 411 avatar@9xk2w...7p
S: 220 0 <e5f6...@unseenet> unseenet.help
S: ...
S: .
```

The client named the profile it held of the first author (a client
that has chosen to, section 3.3), which has not changed; the second
author has a profile but no picture.

# 3. Clients

## 3.1 Nothing Is Taken on the Node's Word

A client MUST check every manifest it gets this way exactly as one it
fetched alone (UN-RFC 0004 section 4): the signature, the owner's
fingerprint against the Group ID, the group type, the serial against the
one it holds, and `expires` (UN-RFC 0029). A manifest with a lower
serial than the one the client holds does not replace it.

A node can withhold a newer manifest with this command as with single
lookups; the defence is the same - several nodes, and the serial of
what the client already holds.

## 3.2 What to Ask For

A client that shows the posts of a group:

- SHOULD ask for the profiles of all the authors it shows, in batches,
  rather than one when the user opens it (UN-RFC 0022 sections 9.2 and
  13);
- MAY ask for pictures only of the authors on screen, since pictures
  are larger (UN-RFC 0040 section 9);
- MUST keep the profiles it gets in its cache (UN-RFC 0022 section 9.2),
  including that a key has none (`411`), for as long as it caches
  profiles.

A request for one group is allowed, and a client MAY use the command
for every manifest it needs.

## 3.3 Naming What the Client Holds

By default a client does **not** name the Message-ID of a manifest it
holds, and receives the article again. The Message-IDs a client has
cached - above all old ones - can serve as a fingerprint: a node could
recognise the same user across connections that Tor otherwise keeps
apart, in the way ETags are used to track people on the web.

- A client MAY offer naming them as a setting the user turns on, with
  a short explanation of what it costs and saves.
- A client meant for users who need to hide (a bootable client) MUST
  NOT name them.

What naming saves is small: refreshing 500 cached profiles costs about
40 KiB instead of about 450 KiB, a few seconds once a day.

# 4. Nodes

## 4.1 Answering

A node answers from the current manifest of each group it carries, as
`GROUP` and part 1 of `NEWNEWS` see it (UN-RFC 0017 section 3). A group
it has removed (UN-RFC 0013) or whose manifest has expired (UN-RFC 0029
section 5) is answered `411`. The command works for readers without
authentication, like `ARTICLE`.

## 4.2 Partial Nodes (Updates UN-RFC 0040 section 8)

A partial node asked for key-bound groups it does not hold SHOULD ask
its peers for them with `XUN-MANIFESTS`, in one request per peer, and
hold the **whole** answer while it does - for up to 10 seconds in all,
not 10 seconds per line. Lines still not found after that are answered
`411`. UN-RFC 0040 section 8 says how long the node remembers that a
group was not found.

## 4.3 Peers (Updates UN-RFC 0040 section 6)

A node offered an article in a key-bound group whose manifest it lacks
fetches the manifest with `XUN-MANIFESTS` where the peer advertises it,
naming one line per group, and falls back to `GROUP`, `HDR` and
`ARTICLE` where it does not. A node that has been offered articles in
several such groups MAY ask for them in one request.

# 5. Security and Privacy Considerations

- **What a node learns.** A node learns which groups a client asks
  for, as it does today; but one request for all 500 authors of a group
  tells it far less about whose profile the user looks at than one
  lookup when the user opens a profile. A client MAY add some Group IDs
  of other keys it has seen to a request, as cover.
- **What the Message-ID tells.** Naming the Message-ID a client holds
  tells the node that this client has seen that manifest before, and a
  set of them can link connections to one user. Clients therefore leave
  them out by default (section 3.3).
- **No new secrets.** Manifests are public and flooded to every full
  node, and every one of them can be read today with `GROUP` and
  `ARTICLE`. The command changes what a lookup costs, not what can be
  looked up.
- **Cost attacks.** A request costs the node one index lookup per line
  and at most about 1 MiB of reading and sending (section 2.3). A node
  MAY limit the number of requests per connection and per minute for
  unauthenticated connections, and answers `400` beyond that, as for
  `XUN-RECONCILE` (UN-RFC 0040 section 4.3).
- **Scale.** At the targets of UN-RFC 0001 section 1.2:
  - a client opening a busy group of 500 authors with an empty cache
    asks for 500 profiles in two requests; at the typical size of
    UN-RFC 0040 section 9 (0.9 KiB) that is about 450 KiB, sent in one
    or two answers - a few seconds over Tor, where single lookups take
    about 25 minutes;
  - with pictures of all 500 (typically 4.8 KiB each, about 2.4 MiB) it
    is about four answers more; showing pictures only on screen keeps it
    to a few;
  - refreshing 500 cached profiles costs the same as fetching them,
    about 450 KiB, or about 40 KiB for a client that names what it holds
    (section 3.3);
  - a node pays an index lookup per line and the reading of the
    articles it sends; nothing grows with the number of groups or
    identities in the network.

# 6. Rationale

- **Why one command and not pipelining?** A client could pipeline
  `GROUP`, `HDR` and `ARTICLE` for many groups, but each answer decides
  the next command, so it would still be three rounds and the node would
  walk article numbers in each group. One command lets the node answer
  from its index of current manifests, and lets the client name what it
  holds.
- **Why answers in the form of `ARTICLE`?** Every client already parses
  `220` followed by a dot-stuffed article, and `223`, `411` and `431`
  mean what they mean elsewhere. Nesting articles in another format
  would need a second kind of framing.
- **Why the Message-ID and not a serial?** Two manifests can have the
  same serial (UN-RFC 0004 section 3.2 breaks the tie by Message-ID),
  and a client trusts only what it has checked. The Message-ID names
  exactly the article the client holds; if it is still current, nothing
  else needs to be sent.
- **Why is it off by default?** The saving is a few seconds a day; the
  risk is that a node can tell users apart across connections. Tor's
  value is that it cannot (section 3.3).
- **Why no form with fingerprints and names?** A key-bound Group ID *is*
  the name and the fingerprint (`profile@<fp>`). A second form would
  save nothing.
- **Why 256 lines, and no lower minimum?** A line is at most 512
  octets (UN-RFC 0005 section 6), so a request stays under 128 KiB. A
  line costs the node one index lookup, so a smaller node saves almost
  nothing by accepting fewer, while every client would have to handle
  nodes with different limits. The size of an answer, not the number of
  lines, is what needs a limit (section 2.3).
- **Why 1 MiB?** An answer should arrive within a second or two over an
  onion service, and a node should not build large answers in memory.
  About 1100 profiles of typical size fit, so the limit is mostly met
  with pictures. The number is an estimate (section 7).
- **Why an `XUN-` name?** UN-RFC 0000 section 5: experimental commands
  carry the prefix until standardized, as `XUN-RECONCILE` does.

# 7. Open Issues

- The size limit of section 2.3 (1 MiB) is an estimate. It is to be
  measured with the load generator of unseenet #219 and set before this
  document becomes Proposed.

# 8. Changes to Other Documents

- **UN-RFC 0005** section 2: `CAPABILITIES` may list
  `UNSEENET-MANIFESTS <max>`, and the command `XUN-MANIFESTS` is added.
- **UN-RFC 0022** section 9.2: a client that reads the profiles of the
  authors in a group uses `XUN-MANIFESTS` where the node has it
  (section 3.2).
- **UN-RFC 0040** sections 6 and 8: "the batch lookup of unseenet #218"
  is `XUN-MANIFESTS` (sections 4.2 and 4.3).
- **UN-RFC 0000** section 6: 0041 is added to the index.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
