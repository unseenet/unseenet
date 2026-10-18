```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0022                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0004, 0008, 0011

                    Unseenet: Profiles for Identities
```

# Abstract

An identity is a key, and since UN-RFC 0019 it may have a name. This
document lets an identity also say something about itself: a short free
text and a list of places to find it elsewhere - a web page, Mastodon,
Matrix, Facebook, TikTok and so on. A **public profile** is kept in the
manifest of a well-known group the identity owns, `profile@<fingerprint>`,
so that anyone who knows the key can find it, nodes carry it like any
other group, and it lasts as long as its owner uses the key: the
client renews it, and it expires when nobody does. A **private profile** is the same
object sent only to chosen people or to a closed group. An identity
may also have a small **picture**, kept apart from the text in a group
of its own, `avatar@<fingerprint>`, that nodes carry only if their
operator chooses to, and every identity has an **identicon** derived
from its key. Profiles and pictures are optional, and nothing in them
is ever fetched from or opened on the clearnet by a client without the
user asking.

# 1. Motivation

On a BBS you could look up who wrote a post; on Unix you could `finger`
somebody and read their `.plan`. Unseenet shows a display name, a short
fingerprint and perhaps a name, and nothing more. In open groups such
as `dk.snak` many people are happy to say who they are, and readers want
to know who they are talking to, find people again outside the network,
and judge a stranger before replying.

The danger is the opposite of the motivation: a link to a Facebook
profile tells everybody who holds the key, and in a replicated network
nothing that has been published can be recalled for certain. A profile
system for Unseenet must therefore be easy to leave empty, easy to keep
on one identity and off another, and honest about what it reveals.

# 2. Terms

- **Profile:** the JSON object of section 4.
- **Public profile:** a profile in the manifest of the identity's
  profile group (section 5).
- **Profile group:** the group `profile@<fingerprint of the identity>`.
- **Private profile:** a profile sent in an inbox message (UN-RFC 0009)
  or posted in a closed group (UN-RFC 0004 section 6) (section 6).
- **Link:** an entry in the profile's `links` (section 4.2).
- **Link proof:** a string placed on the linked page that shows the
  identity controls it (section 7).
- **Picture:** the JSON object of section 8.1, a small image of the
  identity's choosing.
- **Avatar group:** the group `avatar@<fingerprint of the identity>`
  (section 8.2).
- **Identicon:** a pattern derived from a key (section 8.4).

# 3. What Does Not Change

- An identity is still its key. A profile states nothing that a client
  may use to decide who wrote an article, who may post or who holds a
  name. Names come only from certificates (UN-RFC 0019).
- Every identity can post, own groups and hold names without a profile.
  Clients MUST NOT treat an identity without a profile as less
  trustworthy than one with a profile.
- Nodes need no new rules to carry public profiles: a profile group is a
  group, and its profile is part of its manifest.

# 4. The Profile Object

A profile is a JSON object in canonical JSON (UN-RFC 0004 section 3):

| Field   | Type             | Req. | Meaning                                         |
|---------|------------------|------|-------------------------------------------------|
| `v`     | integer          | yes  | `1`                                             |
| `about` | string           | no   | Free text, at most 2048 characters (4.1)        |
| `links` | array of objects | no   | At most 16 links (4.2)                          |
| `lang`  | array of strings | no   | Languages the identity writes, as BCP 47 tags (`da`, `en`), at most 8 |
| `bot`   | boolean          | no   | `true`: the identity posts automatically (UN-RFC 0030 section 6) |

Unknown fields MUST be preserved and ignored. A profile with neither
`about` nor `links` is empty; clients show it as no profile, except
for the bot mark if `bot` is `true`.

The display name is not part of the profile: it is the `From` of the
identity's articles (UN-RFC 0002), and its names are its certificates.

## 4.1 About

`about` is plain text in UTF-8. Lines are separated by LF. Clients MUST
show it as text: no markup, no links made clickable, no terminal
control characters (they MUST replace C0 and C1 control characters other
than LF with a visible substitute).

## 4.2 Links

Each link is an object:

| Field   | Type   | Req. | Meaning                                              |
|---------|--------|------|------------------------------------------------------|
| `kind`  | string | yes  | What the link is, from section 4.3, or `x-` followed by 1-32 of `a-z`, `0-9`, `-` |
| `value` | string | yes  | The address, handle or URL, at most 256 characters   |
| `label` | string | no   | A short description, at most 64 characters           |

`value` is written the way people of that service write it: `@andlo@fosstodon.org`
for Mastodon, `https://www.tiktok.com/@andlo` or `@andlo` for TikTok,
`@andlo:matrix.org` for Matrix. Clients MUST show `value` exactly as it
is, together with `kind`, and MUST NOT shorten or rewrite it, so that a
reader can see where a link really points.

The same `kind` MAY appear more than once.

## 4.3 Kinds

| Kind        | Value                                    |
|-------------|------------------------------------------|
| `web`       | An `https://` or `http://` URL           |
| `onion`     | An `http://` URL whose host is a `.onion` address |
| `email`     | An e-mail address                        |
| `mastodon`  | A fediverse handle or profile URL        |
| `bluesky`   | A Bluesky handle or profile URL          |
| `matrix`    | A Matrix ID or room address              |
| `xmpp`      | An XMPP address                          |
| `signal`    | A Signal username or link                |
| `pgp`       | An OpenPGP fingerprint, 40 hex digits    |
| `github`    | A GitHub user name or URL                |
| `gitlab`    | A GitLab user name or URL                |
| `facebook`  | A Facebook profile name or URL           |
| `instagram` | An Instagram handle or URL               |
| `tiktok`    | A TikTok handle or URL                   |
| `x`         | An X (Twitter) handle or URL             |
| `youtube`   | A YouTube handle or channel URL          |
| `linkedin`  | A LinkedIn profile URL                   |

New kinds are added by updating this table. Until then `x-` kinds
(`x-pixelfed`) MAY be used; clients show an unknown kind as its text.
Clients SHOULD warn when a `value` does not look like its `kind` (for
example a `facebook` link to another domain), but MUST still show it.

## 4.4 Size

A profile in canonical JSON MUST NOT exceed 8192 octets. Nodes MAY
refuse a manifest whose `profile` is larger; clients MUST ignore one.

# 5. Public Profiles

## 5.1 The Profile Group

An identity's public profile lives in the group it owns named `profile`:

```
profile@<fingerprint of the identity's key>
```

Like the personal inbox (UN-RFC 0009 section 2.2) and the sub-name
revocation group (UN-RFC 0019 section 6.6), its Group ID follows from
the key, so anyone who knows the key can find it without asking.

Its manifest (UN-RFC 0004 section 3) has:

- `name`: `profile`;
- `type`: `channel`, with no `posters`;
- `view`: `data` (UN-RFC 0008 section 3.1.1), so that clients do not
  offer it as a group to join;
- `profile`: the profile object of section 4;
- `expires`: an RFC 3339 UTC date, at most 730 days after the
  manifest's `Date` (section 5.4);
- `retention_days`: RECOMMENDED `7` (section 5.3).

Ordinary articles in a profile group mean nothing. The owner SHOULD NOT
post any, and clients MUST ignore them.

## 5.2 Reading a Public Profile

A client finds the public profile of a key by asking a node it uses for
the current manifest (UN-RFC 0004 section 3.2) of the key's profile
group. It accepts the profile if

1. the manifest is valid and its `owner` is the key;
2. its `name` is `profile` and its `profile` field is a valid profile
   (section 4);
3. the current time is before its `expires` (section 5.4).

If the node does not carry the group, the client sees no public profile.
That is not an error and MUST NOT be shown as one.

Because the manifest is part of the group's state, nodes keep it until
it expires (section 5.4), however rarely its owner posts.

## 5.3 Changing and Removing

The owner changes the profile by posting a new manifest with a higher
`serial`. Nodes then let the old manifest expire with the group's
retention; a short `retention_days` makes old versions disappear from
well-behaved nodes soon after.

The owner removes the profile by posting a manifest without `profile`,
and MAY then remove the group (UN-RFC 0013).

Neither can recall copies that others have already kept: archive nodes
(UN-RFC 0012), readers' caches and anybody who saved the text. Clients
MUST say so when a user publishes, changes or removes a public profile
(section 9.1).

## 5.4 Lifetime and Renewal

Profile groups and avatar groups (section 8.2) are key-bound groups
(UN-RFC 0029). Their manifests carry `expires`, at most two years
ahead; the owner's client renews them without asking, together with the
identity's other key-bound groups, and nodes remove them when they
expire. A key that is never used again thus loses its profile and
picture by itself.

# 6. Private Profiles

A private profile is a profile shown only to those an identity chooses.
It is sent as an article, or the inner article of an inbox message,
with

```
Content-Type: application/x-unseenet-profile
```

and the profile in canonical JSON as body, either

- in an inbox message (UN-RFC 0009) to one person, with `Sender-Key`, so
  that the receiver knows whose profile it is; or
- in a closed group (UN-RFC 0004 section 6), where only members can read
  it.

Nodes see only ciphertext in both cases. A private profile is about the
key that signed it: `Sender-Key` in an inbox message, the inner
`Author-Key` in a closed group.

A client SHOULD keep the newest private profile it has received for each
key and context (a closed group, or "sent to me"), and SHOULD show it in
that context in place of the public profile, marked as shared with the
reader or with the group. A private profile sent in one closed group
MUST NOT be shown in another group or outside it.

A private profile with neither `about` nor `links` withdraws the
sender's earlier private profile in that context.

# 7. Link Proofs

A link is only the identity's own statement: anybody can put somebody
else's Facebook page in their profile. A **link proof** lets the owner
of the linked account confirm it. The owner puts this string somewhere
on the linked page - a bio, a pinned post, a web page:

```
unseenet:<fingerprint of the identity's key>
```

for example `unseenet:ph5fc5hop5232qsz`. The profile, signed by the key,
points at the page, and the page points back at the key; together they
show that one person controls both. No signature is needed on the page,
which keeps the string short enough for bios with tight limits.

A client MAY check a proof, but only

- when the user asks for that link to be checked, never automatically;
- over Tor, never directly;
- by fetching `value` (or the URL the kind implies) and looking for the
  string.

It shows the result as "checked by you on <date>", kept locally, and
MUST NOT publish it. A failed check means only that the client could
not find the string; many services refuse Tor or need JavaScript.
Clients MUST show unchecked links as stated by the identity, not as
belonging to it.

# 8. Pictures

An identity MAY have a small picture, shown next to its names in
clients that can show images. Every identity also has an **identicon**,
a pattern derived from its key, which clients show when there is no
picture or pictures are turned off. Pictures are optional and separate
from the text profile: an identity can have either, both or neither.

## 8.1 The Picture Object

A picture is a JSON object in canonical JSON:

| Field  | Type    | Req. | Meaning                                                  |
|--------|---------|------|----------------------------------------------------------|
| `v`    | integer | yes  | `1`                                                      |
| `type` | string  | yes  | `image/png`, `image/jpeg` or `image/webp`                |
| `px`   | integer | yes  | Width and height in pixels, 32 to 128                    |
| `data` | string  | yes  | b64 of the image file, at most 8192 octets before encoding |
| `alt`  | string  | no   | A short description, at most 128 characters              |

Unknown fields MUST be preserved and ignored. The image MUST be square,
`px` by `px`, and a single still frame: no animation. It is carried
inline rather than as a blob (section 12).

The client that creates a picture MUST produce it as UN-RFC 0027
section 9.1 requires for images: decoded and encoded anew from its
pixels, in sRGB, with no metadata of any kind. It scales the image to
`px` itself; it MUST NOT send the user's original file.

A client that receives a picture MUST treat it as UN-RFC 0027 section
9.2 requires for any file: determine the type from the content, decode
it only in a restricted process, and treat a picture as absent if the
content does not match `type`, the decoded image is not `px` by `px`,
or it has more than one frame.

## 8.2 The Avatar Group

An identity's public picture lives in the group it owns named `avatar`:

```
avatar@<fingerprint of the identity's key>
```

Its Group ID follows from the key, like the profile group's (section
5.1). Its manifest is as for the profile group, with `name`: `avatar`
and, instead of `profile`, the field

- `avatar`: the picture object of section 8.1.

Its `expires` and renewal follow section 5.4.

It is read, changed and removed as a public profile is (sections 5.2
and 5.3), and nothing published in it can be recalled either.

A picture is kept in its own group, not in the profile group, so that
a node operator can carry profiles without carrying pictures (section
10), and a reader's client can fetch text without fetching images.

## 8.3 Pictures in Private Profiles

A private profile (section 6) MAY carry a picture in the field
`avatar` of the profile object. Section 4.4 then applies to the profile
without that field, and the field itself MUST NOT exceed 11 264 octets.
The picture is shown only in the context the profile was sent in, as
for the rest of a private profile.

The profile object in a profile group's manifest MUST NOT have an
`avatar` field. A client MUST ignore one there.

## 8.4 Identicons

So that every client shows the same pattern for the same key, the
identicon of a public key `pk` is derived from

```
seed = H( DS("UNSEENET-IDENTICON-1") || pk )
```

(UN-RFC 0003 section 1) as follows:

- **Colour:** hue `h = (256 * seed[0] + seed[1]) mod 360` degrees, with
  saturation 55 % and lightness 50 % (HSL). A client MAY adjust
  lightness to its theme, but MUST keep the hue.
- **Pattern:** a grid of 5 × 5 cells, mirrored about its middle
  column. For `i` from 0 to 14, cell `i` lies in column `c = i div 5`
  and row `r = i mod 5`, and is filled when bit `i mod 8` (0 is the
  least significant) of `seed[2 + i div 8]` is 1. Column `4 - c` repeats
  column `c`. Filled cells take the colour; empty cells the background.

A terminal client MAY draw it with block characters, or show only the
colour. An identicon is a help for the eye, not a proof: different keys
can have similar identicons, and an attacker can search for a key with
a chosen one. Clients MUST show it together with the short form of the
fingerprint (UN-RFC 0019 section 8), never instead of it.

## 8.5 Showing Pictures

- A client MUST NOT publish a picture unless the user chooses one. The
  first time, it MUST tell the user, in plain words, that a photo of
  themselves, or a picture they also use elsewhere, can be found with a
  reverse image search and ties the identity to them or to their other
  accounts, and that a published picture cannot be fully taken back.
  It SHOULD suggest a drawing or the identicon instead.
- It MUST show the picture exactly as it will be published before
  publishing it.
- A picture is shown next to the identity's names and short form, never
  instead of them, and never as if it were part of a post.
- A client SHOULD let the user turn pictures off, and then shows
  identicons. It MUST NOT decode the picture of a key the user has
  hidden (section 9.2) or ignores.
- A client MAY warn when two different keys have the same picture
  (equal `data`), since a copied picture is the easiest impersonation.

# 9. Clients

## 9.1 Publishing

- A client MUST NOT publish a public profile unless the user creates one.
- Before publishing a public profile for the first time, and before
  adding a link of any kind but `onion` to it, a client MUST tell the
  user, in plain words, that
  - anybody who sees the identity's posts can read the profile;
  - a link ties this identity, and everything it has posted and will
    post, to that account;
  - a published profile cannot be fully taken back (section 5.3).
- A client SHOULD offer private profiles (section 6) as the alternative,
  and SHOULD make it easy to keep separate identities: one with a
  profile, one without.
- A client SHOULD NOT suggest a public profile for an identity used in
  closed groups or for anonymous posts, as with names (UN-RFC 0019
  section 12).

## 9.2 Showing

- A client SHOULD let the user open the profile of any author, member
  or name holder, showing in this order: the names of UN-RFC 0019
  section 8, the short form, `about`, `lang`, then the links.
- It MUST show `about` and links as text (4.1, 4.2) and MUST NOT show
  profile text as if it were part of a post.
- It MUST NOT open a link in a browser, fetch it, or fetch anything it
  points to, by itself. It MAY copy a link to the clipboard when asked,
  and MAY hand an `onion` link to Tor Browser when asked.
- It SHOULD cache profiles and MAY read the profiles of all authors in a
  group the user reads, rather than one at a time (section 13).
- It SHOULD let the user hide the profile of a key.

# 10. Nodes

A node carries profile groups like any other group; it needs nothing
new to do so. Because a profile group is small and holds no ordinary
articles, a node whose `new_groups` policy is `trusted` or `manual`
(UN-RFC 0004 section 3.3) SHOULD still accept profile groups with a
valid manifest, unless its operator has chosen not to carry them. The
same holds for avatar groups once the operator has turned them on.

A node says whether it does in its node information (UN-RFC 0011
section 4), in the policy fields

| Field      | Type   | Meaning                                              |
|------------|--------|------------------------------------------------------|
| `profiles` | string | `accept`: carries profile groups; `refuse`: does not |
| `avatars`  | string | `accept`: carries avatar groups; `refuse`: does not  |

Avatar groups (section 8.2) carry images, and no node should carry
images it has not chosen to (UN-RFC 0027 section 1). An implementation
MUST therefore ship with `avatars` set to `refuse`; the operator turns
it on. A node that does not state `avatars` is taken to refuse them.

A node that follows refusal lists (UN-RFC 0027 section 7.3) MUST also
apply them to pictures: it computes the blob ID of the decoded `data`
of an avatar manifest (UN-RFC 0027 section 3.1) and refuses the
manifest if that ID is listed. The same lists then cover a picture
whether it was posted as an attachment or as an avatar.

A node MAY refuse or remove the profile or avatar group of an identity it blocks
(UN-RFC 0018 section 8.2) or whose profile or picture breaks its rules or the law,
as with any group.

# 11. Signature Purposes

No new purposes. A public profile is signed as part of its manifest
(`UNSEENET-ARTICLE-1`), a private profile as part of its article or
inner article.

# 12. Rationale

- **Why in the manifest and not in an article?** A manifest is group
  state, which nodes keep until it expires (section 5.4), and of several
  manifests the newest wins on every node (UN-RFC 0004 section 3.2). An
  article would expire with the group's retention, so a person who is
  offline for a few months would lose their profile, and clients would
  have to choose between versions themselves.
- **Why one group per identity and not one shared group?** A shared
  `unseenet.profiles` group would need an owner who could ban people from
  having a profile, and would need new node rules to keep only the
  newest profile per key. A group per identity is owned by nobody but
  the identity, follows from the key like the personal inbox, and needs
  no new node rules. The cost is many small groups; they hold one
  manifest each.
- **Why pictures inline, and not as blobs?** A picture must last as
  long as the profile, and a manifest is the only thing nodes never
  expire. Manifests are control articles and cannot reference blobs
  (UN-RFC 0027 section 7.1), and blobs expire with the articles that
  reference them. At 128 × 128 pixels a picture fits easily in 8 KiB,
  which is cheap to carry inline.
- **Why a group of its own?** So that an operator can carry text
  profiles without carrying images, and a reader can fetch profiles
  without fetching pictures. It costs one more small group per identity
  that has a picture.
- **Why so small, and no animation?** Small pictures limit what abuse
  can show and what nodes must carry, and leave less room for hidden
  data; still images are calmer to read beside, and rule out the
  many-frame decompression attacks of UN-RFC 0027 section 9.2.
- **Why specify identicons?** If every client drew its own, the same
  person would look different in the TUI, the web client and on
  Android. A fixed derivation costs a few lines and gives everybody a
  recognisable mark without uploading anything.
- **Why do profiles expire?** They are per identity, and after some
  decades almost all of them would belong to forgotten keys. UN-RFC
  0029 gives all key-bound groups the same lifetime and renewal.
- **Why an open list of kinds?** Services come and go. A fixed field per
  service would need a protocol change for each new one; `kind` and
  `value` need none, and `x-` kinds can be tried before they are added.
- **Why proofs without signatures?** The profile is already signed by
  the key, so the page only has to point back. 16 characters of
  fingerprint are enough to make finding another key with the same
  fingerprint impractical, and short enough for a bio.
- **Why private profiles?** Many people want friends or a club to know
  who they are without telling the whole network. Closed groups and
  inboxes already give exactly that audience.
- **Why may clients not open links?** The client runs everything over
  Tor; a browser started from it would not. Opening a link should be a
  decision the user makes outside the client.

# 13. Security and Privacy Considerations

- **Linking.** This is the main risk. A profile, and above all a link to
  an account under a real name, ties the identity to a person. Section
  9.1 requires clients to say so before it happens. Users who need to
  stay anonymous should not publish a profile on that identity at all.
- **No recall.** Anything public can be kept by others (section 5.3).
- **What nodes learn.** A node sees which profile groups a client asks
  about, and so whose profiles a user looks at. Caching and reading the
  profiles of a whole group at once (9.2) make single lookups less
  telling. Private profiles are invisible to nodes.
- **Impersonation.** A profile can claim anything: a famous name in
  `about`, somebody else's accounts in `links`. Clients show names only
  from certificates and links only as stated (section 7); link proofs
  let real account owners confirm.
- **Misleading links.** A link can point somewhere other than it seems.
  Clients show `value` unchanged and warn when it does not match its
  kind (4.2, 4.3).
- **Terminal injection.** Profile text is untrusted. Clients MUST strip
  or replace control characters (4.1), so that a profile cannot move the
  cursor, change colours or set the terminal title.
- **Abuse.** A profile can contain threats or illegal content like any
  post. Nodes can refuse or remove the group (section 10), and readers
  can hide it (9.2). The size limit (4.4) keeps the damage small.
- **Pictures.** A picture can tell who somebody is as surely as a
  link: a photo of their face, or a picture they use on another
  account, found with a reverse image search. Section 8.5 requires
  clients to say so. Re-encoding (section 8.1) removes the metadata a
  file carries, but not what the image itself shows.
- **Hostile images.** A picture is decoded on the reader's machine,
  which makes it an attack on image parsers. Section 8.1 applies the
  receiving rules of UN-RFC 0027 section 9.2.
- **Copied pictures.** Anybody can use somebody else's picture.
  Clients show it only beside names and fingerprints and MAY warn about
  duplicates (section 8.5).
- **Renewal shows activity.** See UN-RFC 0029 section 11.
- **Proof checks.** Fetching a page leaks to the service that somebody
  checked it over Tor, and when. That is why it is never automatic.

# 14. Changes to Other Documents

- UN-RFC 0004 section 3.1: the manifest fields `profile` (object, only
  in profile groups), `avatar` (object, only in avatar groups) and
  `expires` (UN-RFC 0029) are added, and the channel fields `comments`
  and `comment_days` (UN-RFC 0030), which also adds `bot` here.
- UN-RFC 0008 section 3.1.1: profile and avatar groups are data groups.
- UN-RFC 0011 section 4: the policy fields `profiles` and `avatars`
  (section 10).
- UN-RFC 0000 section 6: 0022 is added to the index.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
