```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0031                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0002, 0028

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
- **No tables, footnotes, task lists or other extensions**, except
  strikethrough (`~~text~~`) and emoji shortcodes (section 5).
- **No remote content of any kind.** A client MUST NOT fetch anything
  to display a message: no images, fonts, previews or link metadata.

## 3.2 Posts

Posts (UN-RFC 0028) may use: paragraphs and line breaks, headings
(levels 1 to 3; deeper ones are shown as level 3), emphasis, strong
emphasis, strikethrough, inline code, code blocks (fenced or indented,
with an optional language that clients MAY use for highlighting),
block quotes, ordered and unordered lists (nested at most 4 deep),
thematic breaks, links and images (sections 3.4 and 3.5), and emoji.

## 3.3 Chat Lines

Chat lines may use: emphasis, strong emphasis, strikethrough, inline
code, code blocks, links, images and emoji. Headings, lists, block
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
| `unseenet`          | a group, post or join link inside the network   |
| `news`              | a Usenet article or group (RFC 5538)             |

Any other destination (`javascript:`, `data:`, `file:` and the rest) is
shown as text and not as a link. Bare addresses in the text MAY be made
into links by the same rules.

## 3.5 Images

An image MUST point at an attachment, never at an address:

```
![screenshot of the error](blob:<hash>)
```

where `<hash>` names a blob of UN-RFC 0027. The client fetches it
through its node over Tor, under that document's limits. An image with
any other destination is shown as its alt text, e.g.
`[image: screenshot of the error]`, and the client MUST NOT fetch it.
The same alt text is shown where the blob cannot be had: the node does
not carry files in the group, it has expired, or the client is a
terminal that cannot show pictures (it MAY offer to open the file).

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

Pictures used as emoji (group-owned emoji) and reactions to a post are
separate matters and need documents of their own.

# 6. Changes to Other Documents

- UN-RFC 0002 section 2.3: the `Content-Type` of a post MAY be
  `text/markdown; charset=utf-8; variant=unseenet`.
- UN-RFC 0028 section 6.2: what posts and chat lines may use of
  Markdown is section 3 of this document.
- UN-RFC 0022 section 4.1 and UN-RFC 0014 section 2.1 let a profile's
  `about` and a group's `rules` be Markdown with the post subset of
  section 3.2, without images.

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

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
