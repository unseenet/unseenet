```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0059                                              October 2026
Category: Standards Track
Status: Draft
Implemented: unseenet 0.6.5, unseenet-gui 0.4.0, unseenet-tui 0.3.0
Updates: 0002, 0027, 0031, 0042

                       Unseenet: Link Cards
```

# Abstract

On Facebook, Mastodon or X a link to a newspaper article shows a card:
the site's icon, a title, a short description and a picture. This
document gives Unseenet the same, without letting a link become a
tracking pixel. The card is made once, by the **poster's** client, over
Tor, while the post is being written, and travels in the signed post:
a `Link-Card` header with the text and a small icon, and the picture
as an ordinary attachment (UN-RFC 0027). Readers fetch nothing from
the web; they show what is in the post. Links to Unseenet's own groups,
posts, people and sites get cards made by the reader's client from the
network itself.

# 1. Motivation

People paste links. A bare URL says little about what is behind it, and
a card is what people know from every other network; without it a feed
of shared articles looks like a list of addresses.

The usual way is the wrong one for Unseenet:

- On Facebook the platform's servers fetch the page. Unseenet has no
  central server, and a node fetching web pages for posts would tell
  the web which node carried what.
- If the **reader's** client fetched the page when showing a post, every
  reader would tell the site that they read that post, and when. That is
  a tracking pixel, and UN-RFC 0031 section 3.1 forbids it: a client
  MUST NOT fetch anything to display a message.

What remains is the poster's own client. The poster has the link anyway
and has chosen to share it; fetching the page once, over Tor, tells the
site no more than that someone on Tor looked at it. The card then lives
as long as the post, also when the article has gone behind a paywall or
off the web.

# 2. Terms

Card
: The `Link-Card` header (section 4) and, if it has one, its picture.

Card URL
: The `http` or `https` URL the card describes.

Domain
: The host of the card URL, without a leading `www.`, shown in Unicode
  (IDNA decoded) with any characters that could be mistaken for others
  marked as UTS #39 recommends.

Icon
: The site's small picture (favicon), carried inline in the card
  (section 5).

Picture
: The page's larger picture (`og:image` and the like), carried as a blob
  (section 6).

Poster's client
: The client that writes the post. Only it ever fetches the card URL.

The key words MUST, SHOULD and MAY are as in RFC 2119.

# 3. Principles

1. **Readers never fetch.** UN-RFC 0031 section 3.1 stays as it is. A
   card is content of the post, not remote content.
2. **The domain comes from the URL.** What the page says about itself is
   the poster's claim; the domain is what the link really is. A client
   always shows the domain, and never lets a site name stand in its
   place.
3. **Pictures follow the rules for pictures.** A node that carries no
   images (UN-RFC 0027 section 5, 8) carries no card pictures either.
   Only the icon is inline, and it is small (section 5).
4. **One card per post.** It describes one link; others stay links.
5. **A card is never an error.** A page that cannot be fetched gives no
   card or a card the poster fills in by hand; the post is sent either
   way.

# 4. The Link-Card Header

```
Link-Card: url=<b64>; title=<b64> [; desc=<b64>] [; site=<b64>]
           [; icon=<b64>] [; image=<blob-id>] [; made=<date>]
```

(on one line; folding is forbidden, UN-RFC 0002 section 1). `b64` is
as in UN-RFC 0003. The header appears at most once (UN-RFC 0002 section
1), so an article has at most one card.

| Parameter | Req. | Meaning                                                     |
|-----------|------|-------------------------------------------------------------|
| `url`     | yes  | The card URL, b64 of UTF-8, at most 2048 octets before encoding |
| `title`   | yes  | Title, b64 of UTF-8, at most 200 characters                 |
| `desc`    | no   | Description, b64 of UTF-8, at most 300 characters           |
| `site`    | no   | The site's own name, b64 of UTF-8, at most 60 characters    |
| `icon`    | no   | The icon, b64 of a PNG file (section 5)                     |
| `image`   | no   | Blob ID of the picture; it MUST be one of the article's attachments (section 6) |
| `made`    | no   | When the poster's client fetched the page, as in UN-RFC 0002 `Date` |

Unknown parameters MUST be ignored. `title`, `desc` and `site` are
plain text: a client MUST NOT render them as Markdown or HTML, and
MUST replace control characters and line breaks with spaces.

## 4.1 Where the Header Goes

The same as `Attachment-<n>` (UN-RFC 0027 section 4.3): in the outer
header block of open, moderated and channel groups, and in the inner
block of closed groups and inboxes, so that what someone linked to in a
private conversation is as private as the rest of it.

## 4.2 Consistency

A reader's client MUST treat the card as absent when:

- `url` is not an `http` or `https` URL, or the same URL (after
  removing a trailing `/` and the fragment) does not appear in the
  body as a link or a bare URL. A card can only describe a link the
  reader can see, so it cannot carry a hidden payload.
- `title` is missing or empty after the replacements above.
- `image` names a blob that is not among the article's attachments.

A node does not check cards beyond the general limits of UN-RFC 0002;
the checks above are for clients.

## 4.3 Unseenet Addresses

A card URL MUST NOT be an Unseenet address or the web form of one
(UN-RFC 0031 section 3.4.1). Those get reader-made cards (section 9).

# 5. The Icon

The icon is the one picture a card carries inline, because it is what
makes the source recognisable at a glance and must be there also on a
node that carries no blobs.

- A PNG file, re-encoded by the poster's client (section 7.4), square,
  at most **32 × 32 pixels**, at most **2048 octets**, not animated.
- A reader's client MUST check these limits after decoding and MUST
  treat an icon that breaks them, or does not decode, as absent.
- With no icon, a client shows a neutral placeholder made from the
  domain (for example its first letter), never a picture of its own
  choosing.

# 6. The Picture

The picture is an attachment (UN-RFC 0027): it is listed in `Blobs`,
described by an `Attachment-<n>` header with `type`, `size` and `dim`,
and counts towards the limit of 4 attachments and their sizes. Its
`alt` SHOULD be the card's title.

- The poster's client scales it to at most **600 pixels** on its long
  side and re-encodes it (section 7.4), aiming at no more than about
  64 KiB.
- A client shows the attachment named by `image` only in the card, not
  a second time among the post's attachments.
- On a node that does not carry the blob, the card is shown without
  it, with the same notice clients give for other files that are not
  carried (UN-RFC 0027). It is never fetched from the web.
- A group whose manifest allows no attachments (UN-RFC 0027 section
  5.1) can still have cards, without pictures.

# 7. Making a Card

## 7.1 When

The poster's client offers a card when a URL is pasted into the text or
when the poster stops typing after one; it MUST NOT fetch on every
keystroke, and MUST NOT fetch URLs that are only in quoted text. By
default it makes the card for the **first** `http` or `https` URL in
the text. The poster can choose another URL, edit the title and the
description, remove the picture, add a picture of their own, or send
without a card.

A client MUST show the card in the composer before it is sent, as it
will appear, so the poster knows what goes out under their name.

## 7.2 Fetching

- Only `http` and `https`, over Tor, `.onion` addresses included. A
  client that cannot reach Tor makes no card from the web (section
  7.5).
- A plain GET with a common browser `User-Agent` and
  `Accept-Language` from the client's language; no cookies, no stored
  state, no JavaScript, no referrer.
- At most 5 redirects; the card URL stays the one in the text, but
  relative addresses are resolved against the final one.
- At most the first **512 KiB** of the HTML, at most **5 MiB** for a
  picture or icon before re-encoding, and a short timeout (about 20
  seconds in all). A client MUST NOT follow a redirect or picture
  address to a private or local address (`localhost`, RFC 1918, link
  local and the like).
- A site that answers with a challenge page (Cloudflare and the like),
  an error or no usable metadata gives no card. The client says so in
  the composer and offers to write a title by hand; it is never an
  error that stops the post.

## 7.3 Reading the Page

From the `<head>`, each value from the first source that has a
non-empty one:

| Field  | Sources, in order                                                    |
|--------|----------------------------------------------------------------------|
| title  | `og:title`, `twitter:title`, `<title>`                               |
| desc   | `og:description`, `twitter:description`, `<meta name="description">` |
| site   | `og:site_name`, `application-name`                                    |
| picture| `og:image:secure_url`, `og:image`, `twitter:image`                    |
| icon   | the largest `link rel="icon"` or `rel="apple-touch-icon"` of at most 192 pixels, else `/favicon.ico` |

Meta tags are recognised by `property` or `name`. Values are
HTML-unescaped, trimmed, and cut at the limits of section 4 on a word
boundary with `…`. A `<title>` that ends in the site name after ` | `,
` - ` or ` – ` MAY have that part removed. An `og:url` is ignored: the
card describes the URL the poster wrote.

## 7.4 Re-encoding Pictures

Every picture and icon is decoded and encoded again by the poster's
client, never passed on as fetched. This removes metadata (UN-RFC 0027
section 9.1) and makes a malformed file fail on the poster's device
instead of on every reader's. A picture that cannot be decoded is left
out. SVG icons are rasterised or left out; they are never carried.

## 7.5 Settings

- A client MUST let the user turn link cards off. With them off it
  fetches nothing; the poster can still write a card by hand.
- Clients made for people who need to hide the most (such as the
  bootable client) MUST have cards **off by default**:
  fetching a URL confirms that someone received it, for example a link
  with a tracking token sent only to them.
- A client running in a browser (UN-RFC 0043) can usually not fetch
  arbitrary pages, and an entrance MUST NOT fetch pages on behalf of
  its visitors: it would learn what people link to and become an open
  proxy. Such a client makes cards from the web only when the device
  has Tor; otherwise the poster can write one by hand.

# 8. Showing a Card

- **Feeds and timelines** show the card under the post's text: the
  picture if there is one, then a line with the icon and the **domain**,
  then the site name, the title and the start of the description.
  A post with more links shows "+N links".
- **A card without a picture** is shown compactly: a larger icon beside
  the text, rather than an empty picture area.
- **A post with pictures or files of its own** (UN-RFC 0027) shows them
  first, as it would without a card; its card SHOULD then be shown small,
  as in a chat (icon, domain and title), after them. The poster's own
  pictures are what the post is about; the card only says where the link
  goes.
- **The post view** shows the same card, with all links in the text.
- **Chats** show a small card: icon, domain and title.
- **Text-only clients** show the domain, site, title and description as
  text, and the picture as a file that can be opened like other
  attachments.
- The domain MUST be shown on every card, as text, at least as
  prominently as the site name. A client SHOULD say that the card comes
  from the poster (for example "Preview from the poster" and the date
  from `made`).
- Opening a card opens its URL under the rules for links (UN-RFC 0031
  section 3.4): only on the reader's action, with the warning before
  leaving Tor, and never in a client that does not open links.
- Cards never change the order of a feed (UN-RFC 0034).

# 9. Cards for Unseenet Addresses

Links to a group (`!group` or its address), a post, a person or a site
page (UN-RFC 0031 section 3.4.1) get a card made by the **reader's**
client from the network: the group's title and description from its
manifest, a post's subject and author, a person's name and profile
picture (UN-RFC 0022), a page's title. This fetches nothing from the
web, so it is not remote content in the sense of UN-RFC 0031 section
3.1, and it cannot be faked by the poster.

- Such cards are not carried in the article and do not count as the
  post's card; a post can have a `Link-Card` for a web link and also
  show cards for Unseenet addresses.
- A client SHOULD make them only from what it already has or fetches
  anyway from its node, and MAY show just the address until then.
- A group or person the reader's node does not carry is shown with its
  address and "not on this node".

# 10. Editing

A card is part of the article, so it is changed or removed with a new
version under UN-RFC 0042. A client SHOULD offer to make the card again
when the post is edited.

# 11. Services

- **Bots** SHOULD give their posts
  cards, made the same way. They include a picture only where the
  source's licence allows it, as for other pictures they post.
- **Gateways** MAY give incoming posts with a link a card, made by the
  gateway over Tor under section 7, with the same licence rule. Going
  out, a gateway sends the plain URL; the other network's clients make
  their own previews.
- **Spam report issuers** (UN-RFC 0045) MAY compare a card with its page
  and report cards whose title or picture does not belong to it.

# 12. Rationale

- **Why the poster, not the reader?** The reader fetching is a tracking
  pixel, and one fetch per reader instead of one per post. The poster
  already has the link and chose to share it.
- **Why the picture as a blob and not inline?** Operators choose whether
  their nodes carry images, and blobs are off by default for their
  sake (UN-RFC 0027). An inline picture in every post with a link would
  get past that choice. The card's text always travels, so a node
  without blobs still shows a useful card.
- **Why the icon inline anyway?** It is what makes the source
  recognisable, and a card without it on most nodes would lose that. At
  32 pixels and 2 KiB it is as cheap as a profile picture (UN-RFC 0022)
  and leaves little room for abuse.
- **Why one card per post?** Feeds show one card in any case, and one
  card keeps the format, the composer and the abuse surface small.
  Other links are still links. More cards could be allowed later by a
  new header without breaking this one.
- **Why the first URL by default?** It is what people know from other
  networks, and the poster can choose another.
- **Why show the domain so firmly?** The card is the poster's claim.
  Anybody can make a card that says "DR" and links elsewhere; the
  domain is the part that cannot lie.
- **Why must the URL be in the text?** So a card cannot describe or
  carry something the reader does not see, and so readers without
  cards (newsreaders, UN-RFC 0027 section 9.3) see the same link.
- **Why `made`?** A card shows what the page said then. Articles change
  and vanish; the date tells the reader how old the description is.

# 13. Security and Privacy Considerations

- **What the poster's fetch reveals.** The site learns that a Tor exit
  fetched the page at that time. A link made for one person (a tracking
  token, a unique address) can still confirm that it was received and
  opened; that is why bootable clients have cards off by default and
  every client can turn them off (section 7.5).
- **Readers.** Readers fetch nothing, so a card tells the site nothing
  about who read the post.
- **Private posts and closed groups.** The card is in the inner header
  block and its picture is an encrypted blob (section 4.1), as for
  other attachments.
- **Deceptive cards.** A poster can write any title or choose any
  picture. Clients show the domain from the URL and that the card comes
  from the poster; issuers can report deceptive cards (section 11).
- **Look-alike domains.** Internationalised domains are shown decoded
  with confusable characters marked (section 2), so `bt.dk` and a
  look-alike in another script do not look the same.
- **Hostile files.** Pictures and icons are re-encoded by the poster's
  client and checked by readers (sections 5, 7.4), and treated as
  hostile like any file (UN-RFC 0027 section 9.2).
- **Server-side request forgery.** Bots and gateways fetch pages for
  others' links; the ban on private and local addresses (section 7.2)
  keeps them from being used to reach their own networks.
- **Copyright.** Titles and short descriptions are what any link
  preview shows. Pictures are the poster's choice and can be removed;
  services follow the source's licence (section 11), and operators can
  refuse picture blobs like any other (UN-RFC 0027 section 7.3).

# 14. Example

A post in `dk.snak.nyheder` with a link to a newspaper article (lines
shortened):

```
Newsgroups: dk.snak.nyheder
Subject: Så blev han dømt
Blobs: blob1:7hq2...k4=21877
Attachment-1: blob1:7hq2...k4; type=image/jpeg; size=21877; dim=600x315; alt=QW5zYXQg...
Link-Card: url=aHR0cHM6Ly93d3cuYnQuZGsva3Jp...; title=QW5zYXQgaSBwb2xpdGll...; desc=UmV0dGVuIGkgU8O4bmRl...; site=Qi5ULg; icon=iVBORw0KGgoAAAANSUhEUg...; image=blob1:7hq2...k4; made=Fri, 30 Oct 2026 12:31:07 +0000

Så blev han dømt. https://www.bt.dk/krimi/ansat-i-politiet-snoed-fleggaard-nu-er-han-doemt
```

Shown in a feed:

```
@lorensen · today 12:31
Så blev han dømt. https://www.bt.dk/krimi/ansat-i-…
┌──────────────────────────────────────────┐
│               [picture]                  │
│ [icon] bt.dk · B.T.                      │
│ Ansat i politiet snød Fleggaard: Nu er   │
│ han dømt                                 │
│ Retten i Sønderborg har idømt en …       │
│ Preview from the poster · 30 Oct 2026    │
└──────────────────────────────────────────┘
```

A page with no picture and no `og:title` (only `<title>` and
`/favicon.ico`) gives a card with `title`, `desc` and `icon`, shown
compactly.

# 15. Changes to Other Documents

- UN-RFC 0002 section 2: the header `Link-Card` is added.
- UN-RFC 0027 section 4: an attachment named by a card's `image` is
  shown in the card only (section 6).
- UN-RFC 0031 section 3.1: a note that link cards (UN-RFC 0059) and
  cards for Unseenet addresses are content of the post or of the
  network, not remote content; the rule itself is unchanged.
- UN-RFC 0042: a card is changed with the post (section 10).
- UN-RFC 0000 section 6: 0059 is added to the index.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
