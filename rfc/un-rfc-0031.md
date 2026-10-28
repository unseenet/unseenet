```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0031                                              October 2026
Category: Standards Track
Status: Draft
Implemented: unseenet 0.4.0
Updates: 0002, 0004, 0022, 0028, 0034, 0035

             Unseenet: Formatting - Markdown and Emoji
```

# Abstract

This document lets the text of a message be **Markdown**: a small,
safe subset of CommonMark that reads well also where it is not rendered,
as Usenet text always has. It says which parts posts and chat lines
(UN-RFC 0028) may use, that nothing is ever loaded from outside the
network, that images can only point at attachments (UN-RFC 0027), and
how **emoji** are written: as Unicode, or as shortcodes like `:tada:`
from one fixed table.

# 1. Motivation

People expect to write *emphasis*, lists, code and links, and to send
a 👍. Markdown is the natural choice for Unseenet because its raw form
is the plain text Usenet already uses: `> quotes`, `*stars*`, indented
code. A reader without Markdown, tin included, still reads it fine.

The dangers are what graphical clients usually do with formatted text:
load images and fonts from the web, run HTML, and hide where a link
really goes. Over Tor, loading anything from outside reveals the
reader. This document allows none of that.

# 2. Marking a Message as Markdown

A message whose text is Markdown has

```
Content-Type: text/markdown; charset=utf-8; variant=unseenet
```

in its header block, or in the inner article of a closed group or an
inbox (UN-RFC 0004 section 6, UN-RFC 0009 section 2.3), where the
`Content-Type` already is. Without it, or with `text/plain`, the text
is plain and MUST be shown as written.

- Clients SHOULD send Markdown by default and MUST let the author send
  plain text instead.
- A reader MAY always show Markdown as plain text; it is written to be
  read that way.
- The signature (below `-- `, UN-RFC 0002) is never Markdown.

# 3. The Subset

The text is parsed as CommonMark 0.31, with these limits. Anything
outside the subset is shown as the text it is.

## 3.1 Never

- **No raw HTML**, inline or as blocks. It is shown as text.
- **No footnotes, task lists or other extensions**, except
  strikethrough (`~~text~~`), tables (section 3.6) and emoji shortcodes
  (section 5).
- **No remote content of any kind.** A client MUST NOT fetch anything
  to display a message: no images, fonts, previews or link metadata.

## 3.2 Posts

Posts (UN-RFC 0028) may use: paragraphs and line breaks, headings
(levels 1 to 3; deeper ones are shown as level 3), emphasis, strong
emphasis, strikethrough, inline code, code blocks (fenced or indented,
with an optional language that clients MAY use for highlighting),
block quotes, ordered and unordered lists (nested at most 4 deep),
thematic breaks, links and images (sections 3.4 and 3.5), tables
(section 3.6), and emoji.

### 3.2.1 Read More

Where a long post is cut for "… more" - in a feed, a timeline or any
other preview - the author can choose the place, with a **read-more
line**: a line that holds only `...` or `…`, with at most three spaces
before it and any spaces after it. Like WordPress' `<!--more-->`, but in
a form that falls back nicely: a reader that does not know this rule,
or a newsreader over NNTP, shows a line with three dots.

- **Which line.** Only the first read-more line counts. Lines inside
  code blocks (fenced or indented) and block quotes are not read-more
  lines. It applies to posts, Markdown or plain text, including private
  posts and the about texts and charters where those are shown cut; not to
  chat lines, which are never cut this way.
- **Where it cuts.** A client cuts at the read-more line instead of
  its normal place when the line comes within its normal cut, and also
  when it comes later but within **twice** the normal cut: the author
  may make the shown part somewhat longer than usual. Further down it is
  ignored and the normal cut applies, so one post cannot fill a feed or
  a thread list. The normal cut is the client's own (a number of lines,
  or a height); "twice" is measured the same way.
- **Shown cut**, the part before the read-more line is shown, and
  "… more" (or the client's word for it) even when that part is short.
- **Opened**, the whole text is shown and the read-more line itself is
  not.
- **Only a display hint.** The article is unchanged and the full text
  is always there; nodes do nothing with it, and quoting, searching
  and editing see the line as it is. A client that renders text for
  others to draw (UN-RFC 0046) gives the place as a block of its own,
  so they need not find it again.

## 3.3 Chat Lines

Chat lines may use: emphasis, strong emphasis, strikethrough, inline
code, code blocks, links, images, tables (section 3.6) and emoji. Headings, lists, block
quotes and thematic breaks are shown as the text they are, so that chat
stays chat.

## 3.4 Links

A link is shown with its text **and** where it goes, or the address is
shown on hover or focus, so the reader always sees the real address.
A client MUST NOT open a link without the reader's action.

Allowed destinations:

| Scheme              | Meaning                                         |
|---------------------|-------------------------------------------------|
| `http`, `https`     | the web; a client SHOULD warn before opening one that is not a `.onion` address, as it leaves Tor's protection unless the browser is Tor Browser |
| `unseenet`          | an address inside the network (section 3.4.1)   |
| `news`              | a Usenet article or group (RFC 5538)             |

An `http` or `https` link that is the web form of an address (section
3.4.1) is an address, not a link to the web: a client opens it in the
network as the address it stands for, and does not warn as for the web.
`web+unseenet` is the same scheme as `unseenet` (section 3.4.1).

Any other destination (`javascript:`, `data:`, `file:` and the rest) is
shown as text and not as a link. Bare addresses in the text MAY be made
into links by the same rules.

### 3.4.1 Addresses

An `unseenet:` address names something in the network. It is the one
form for all of them, used in links, invitations, link proofs and
anywhere else a client writes or reads one:

```
unseenet:<fingerprint>                    an identity
unseenet:<group-id>                       a group: also a feed, a site, a personal group
unseenet:<group-id>?m=<message-id>        a post or chat line in that group
unseenet:<group-id>?p=<path>              a page of a site (UN-RFC 0035)
```

- `<fingerprint>` is a key's fingerprint (UN-RFC 0003 section 2), 16
  characters of `a-z` and `2-7`. `<group-id>` is a whole Group ID,
  `<name>@<fingerprint>` (UN-RFC 0004), never a shortened one.
- `m` is a Message-ID without its angle brackets; `p` is a path of
  UN-RFC 0035 section 4.1.
- `n=<onion address>` MAY be added to any of them: a node that carries
  it, as a hint. A client MAY ask that node over Tor, and SHOULD ask
  the user before adding it to the nodes it uses.
- Parameters are separated by `&` and may come in any order; their
  values are percent-encoded as RFC 3986 requires, except that `@` and
  `/` may be written as they are. A client ignores parameters it does
  not know.
- Names (UN-RFC 0019) are not part of an address: they can change hands
  and look like Group IDs. Where a name is valid for a key, a client
  SHOULD show it with the address, and MUST let the reader see the
  fingerprint.

A client opens an address only when the reader asks (section 3.4). It
shows a group the user does not follow and asks before subscribing; it
shows what it cannot find as unavailable, which is not an error.

Older forms MUST still be read, and SHOULD NOT be written:

| Older form                                  | Read as                               |
|---------------------------------------------|---------------------------------------|
| `unseenet:join?g=<group-id>&n=...&p=...`    | `unseenet:<group-id>?n=...&p=...`     |
| `unseenet:<fingerprint>/<path>`             | `unseenet:site@<fingerprint>?p=<path>` |

**The web form.** Outside the network, people share links in web pages,
chats and mail, where `unseenet:` does nothing. Every address therefore
also has a web form: the address without its scheme, under the fixed
path `/a/` on any web entrance (UN-RFC 0043 section 8.1):

```
unseenet:<group-id>?p=projects/ovos   https://<host>/a/<group-id>?p=projects/ovos
unseenet:<group-id>?m=<message-id>    https://<host>/a/<group-id>?m=<message-id>
unseenet:<fingerprint>                https://<host>/a/<fingerprint>
```

- The path and parameters are the same on every host, so a link keeps
  working when one entrance is blocked or gone: another host, or the
  jump page of UN-RFC 0043 section 8.7, gives the same address.
- A client MUST read the web form on **any** host, `http` or `https`,
  and treat it as the address it stands for: it opens it in the
  network, over Tor, and never fetches the web page. The host is not
  part of the address and is not trusted for anything; the address
  itself says whose group it is.
- When a client writes a web form, it uses a listed entrance, or the
  host the user has chosen, and SHOULD leave out `n` (a node hint helps
  nobody who reads the address on the web).
- `?p=` without `m` means the page as it is now; `?m=` names one
  article, so it is the permanent address of one version.

**`web+unseenet`.** Browsers let a page register itself only for
schemes that begin with `web+`. A client in a browser (UN-RFC 0043)
therefore registers `web+unseenet:`, and every client reads
`web+unseenet:<...>` exactly as `unseenet:<...>`. Desktop clients MAY
register `unseenet:` with the operating system. Clients write
`unseenet:`, never `web+unseenet:`.

### 3.4.2 Group References

In the text of a post, a chat line, a profile's `about` or a group's
`charter`, `!<name>` or `!<name>@<fp>` refers to a group, so that one can
point somebody to a better place - as Lemmy writes `!community@instance`.
`<name>` is a group name that contains a letter, at most 128 characters;
`<fp>` is the first 4 to 16 characters of the owner's fingerprint. A `!`
that follows a letter, digit, `_`, `@`, `#`, `!`, `/`, `&`, `.`, `+` or `-`
does not start one, nor does `![`, which begins a Markdown image.

`#word` is a tag, not a group (UN-RFC 0052 section 3). (Before 27 October
2026, while Unseenet was pre-alpha, `#` referred to groups; it was changed
so that `#` means what readers expect of it everywhere else.)

- `!<name>@<fingerprint>` with the whole fingerprint means
  `unseenet:<name>@<fingerprint>`.
- A shorter `<fp>`, or none, is resolved by the reader's client among
  the groups its nodes list. It shows every match, with the warning of
  UN-RFC 0018 where the name is not the hierarchy's, and asks when
  there is more than one.

## 3.5 Images

An image MUST point at an attachment, never at an address:

```
![screenshot of the error](blob1:<52 characters>)
```

where the destination is a blob ID of UN-RFC 0027 section 3.1, written
as it is, and MUST be one of the blobs the article itself carries (its
`Blobs` header, or for an encrypted article the inner one). An image
whose blob the article does not carry is shown as its alt text, as
below, so a post cannot make a reader fetch someone else's file. The
client fetches it through its node over Tor, under that document's
limits. An image with
any other destination is shown as its alt text, e.g.
`[image: screenshot of the error]`, and the client MUST NOT fetch it.
The same alt text is shown where the blob cannot be had: the node does
not carry files in the group, it has expired, or the client is a
terminal that cannot show pictures (it MAY offer to open the file).

## 3.6 Tables

Tables are those of GitHub Flavored Markdown 0.29: a header row, a
delimiter row under it, and the rows after, cells separated by `|`:

```
| Group     | What            | Address        |
|:----------|:---------------:|---------------:|
| Discuss   | threads         | `unseenet:...` |
```

- A table needs its delimiter row, so an ordinary line with a `|` in it
  is never one. That is also why tables are allowed in chat lines.
- Cells hold inline content only (section 3.2's inline parts, with
  links and images); the delimiter row's colons give each column's
  alignment, left, centre or right.
- A client MUST show at least the first 16 columns and 500 rows, and
  MAY leave out what is beyond. A table wider than the space it has
  SHOULD scroll sideways or be cut, never break the layout around it.
- A client that does not show tables shows the text as it is, which is
  meant to be readable as it stands.

# 4. Quotes and Replies

A reply quotes with `> ` at the start of each line, as before. In
Markdown that is a block quote, so quoting works the same in both forms.
Clients MAY fold long quotes. Writing clients SHOULD quote the text as
written (its Markdown source), not as rendered.

# 5. Emoji

## 5.1 Unicode

Emoji are ordinary UTF-8 text and are allowed everywhere: in plain and
in Markdown text, in subjects and in chat. Clients MUST pass them
through unchanged. A terminal client SHOULD measure their width
correctly; on a terminal without the glyphs they show as whatever the
terminal can.

## 5.2 Shortcodes

In Markdown text, a shortcode is a name between colons, `:tada:`,
made of lowercase letters, digits, `_`, `+` and `-`. The names come from
one fixed table: the aliases of **gemoji 4.1.0** (github/gemoji,
`db/emoji.json`), the names people know from GitHub, Slack and Discord.
Implementations ship the table; the reference implementation has it as
`emoji.json`. A later document may name a newer version of the table;
names are only ever added.

- The author's client sends what the author wrote and does not convert
  shortcodes to Unicode.
- A graphical client shows the glyph. A terminal client shows the glyph
  if it can, and otherwise the shortcode as written.
- An unknown name, and anything inside code, stays text.

## 5.3 Not in This Document

Pictures used as emoji are UN-RFC 0056 (a group's own emoji), and
reactions to a post UN-RFC 0048.

# 6. Changes to Other Documents

- UN-RFC 0002 section 2.3: the `Content-Type` of a post MAY be
  `text/markdown; charset=utf-8; variant=unseenet`.
- UN-RFC 0028 section 6.2: what posts and chat lines may use of
  Markdown is section 3 of this document.
- UN-RFC 0034 section 4.1 and UN-RFC 0046: an entry cut with "… more"
  is cut at its read-more line (section 3.2.1); the rendered text marks
  the place with a block `{"t": "more"}`.
- UN-RFC 0022 section 4.1 and UN-RFC 0014 section 2.1 let a profile's
  `about` and a group's `charter` be Markdown with the post subset of
  section 3.2, without images.
- Profiles' `about`, groups' `charter` and pages (UN-RFC 0035) may hold
  tables as posts do (section 3.6).
- UN-RFC 0004 section 6.4 (invitations), UN-RFC 0022 section 7 (link
  proofs) and UN-RFC 0035 section 8 (links to pages) use the addresses
  of section 3.4.1; their older forms are read as section 3.4.1 says.

# 7. Security and Privacy Considerations

- **No outside requests:** nothing in a message makes a client fetch
  anything from the web; images come only from the network's own
  attachments. This is the main protection, and clients MUST keep it.
- **No HTML, no scripts:** raw HTML is text, and only the link schemes
  in section 3.4 are links.
- **Deceptive links:** showing where a link goes, and warning before
  leaving Tor, keeps a link's text from lying about its destination.
- **Rendering cost:** clients SHOULD limit nesting and the size of what
  they render, so a crafted message cannot hang them.
- **Web forms on any host:** a web form names its host, but the client
  never asks that host for anything; it opens the address in the
  network. A web form on a hostile host can therefore lead only to
  what the address names, which the address's fingerprint pins down,
  just as for `unseenet:`. Copying such a link into a normal browser
  does contact the host, which then learns that somebody opened it
  from that IP address; clients SHOULD say so where they offer to copy
  a web form.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
