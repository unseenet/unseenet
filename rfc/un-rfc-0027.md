```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0027                                              October 2026
Category: Standards Track
Status: Draft
Implemented: unseenet 0.4.0
Updates: 0001, 0002, 0004, 0005, 0011, 0012

                       Unseenet: Attachments
```

# Abstract

People in a discussion sometimes need to show something: a screenshot,
a photo of the thing they are talking about, a short animation, a PDF.
This document lets an article carry up to four small files as
**attachments**. A file is not put inside the article. It is stored as a
separate **blob**, named by the hash of its octets and referenced from
the signed article, so the article stays small text and the network's
text traffic is unchanged. Group owners decide whether a group allows
attachments, node operators decide whether and how much of them their
node carries, and blobs follow their article from node to node so that
no node can tell where a post entered the network. Clients strip
metadata before posting and never hand a received file to another
program without the user asking.

# 1. Motivation

UN-RFC 0001 section 1.1 makes binary file distribution a non-goal, and
UN-RFC 0002 limits an article to 64 KiB. That was deliberate, and the
reasons still hold: on Usenet the binary groups grew until they were
almost all of the traffic, most servers could not afford to carry them,
and the operators who did were exposed to whatever was posted.

But a discussion network with no way to show a picture forces people to
describe screenshots in words or link to clearnet image hosts, which the
client must not open (UN-RFC 0022 makes the same point for links). The
goal is therefore narrow: **small attachments to discussion**, not file
sharing.

The design follows from five requirements:

1. **Text stays text.** Articles keep their format and limit. Nodes and
   newsreaders that know nothing of attachments keep working.
2. **Nobody carries files unwillingly.** Carrying blobs is opt-in for
   every node, with its own limits, and a node can drop any blob without
   dropping the discussion.
3. **No new way to find the origin.** Nodes must not learn where an
   article entered the network (UN-RFC 0001 section 3). A blob that can
   only be fetched from the node it was posted to would tell everybody
   exactly that, so blobs travel the same way as their article
   (section 6.3).
4. **Closed groups and inboxes stay private.** Their blobs are
   encrypted; nodes carry ciphertext as they do for articles.
5. **Files are dangerous to the person who posts and to the person who
   opens them.** A photo carries GPS coordinates, a PDF its author's
   name, a screenshot the time zone in its file name; an image or PDF
   parser is a classic way to attack a reader. The client rules in
   section 9 are therefore as important as the wire format.

# 2. Terms

Attachment
: A file shown with an article: its blob and a description (type, size,
  name, alternative text).

Blob
: An octet string of at most 4 MiB stored by nodes outside the article.
  For a closed group or an inbox the blob is ciphertext.

Blob ID
: The name of a blob, derived from its octets (section 3.1).

Blob node
: A node that implements this document and carries blobs for a group
  (section 8).

Staging
: Holding blobs uploaded on a client connection until the article that
  references them is posted (section 6.2).

# 3. Blobs

## 3.1 Blob IDs

```
blob-id = "blob1:" b32( H( DS("UNSEENET-BLOB-1") || octets ) )
```

with `b32`, `H` and `DS` from UN-RFC 0003 section 1. The b32 part is 52
characters (256 bits); the whole ID is 58 characters. The prefix gives
algorithm agility as for keys (UN-RFC 0003 section 2). Implementations
MUST reject blob IDs with an unknown prefix.

Whoever receives a blob, node or client, MUST compute its ID and discard
the blob if the ID differs from the one asked for.

## 3.2 Sizes

- A blob MUST NOT exceed **4 194 304 octets** (4 MiB).
- An article MUST NOT reference more than **4** blobs, and their sizes
  together MUST NOT exceed **8 388 608 octets** (8 MiB).
- A blob node MUST accept blobs of at least 1 048 576 octets (1 MiB)
  and MAY set its limit anywhere up to 4 MiB.

The article itself remains subject to UN-RFC 0002 section 1; blobs do
not count towards its size.

## 3.3 Encrypted Blobs

In a closed group (UN-RFC 0004 section 6) and an inbox (UN-RFC 0009),
each file is encrypted before upload with a **fresh random 32-octet key**
used for that file only:

```
blob = nonce || XChaCha20-Poly1305( key, nonce, file,
                                    ad = DS("UNSEENET-BLOB-ENC-1") )
```

(UN-RFC 0003 section 4.2). The key travels inside the encrypted article
(section 4.3), and the same file posted twice gives two unrelated blobs.

**Padding.** Before encryption, the client appends zero octets to the
file up to the next multiple of 64 KiB (65 536 octets), but not beyond
the group's `max_size` (section 5.1; nodes allow an encrypted blob 40
octets more, section 5.2), so that nodes, which see every blob's size,
cannot tell a file by its exact length (section 14). The file's own size is in the
inner `Attachment-<n>` header (section 4.2); after decryption the reader
takes that many octets and ignores the rest. A blob is therefore
`padded + 40` octets, where `size <= padded <= ceil(size / 65536) * 65536`.
Files in open groups are not padded: anyone can read them anyway.

Keys MUST NOT be derived from the file (convergent encryption). That
would let anyone who has a file confirm that a closed group or inbox
received it, and link the posts that carry it.

# 4. Referencing Blobs from an Article

An article with attachments carries two kinds of header: `Blobs`, which
tells nodes what to carry, and `Attachment-1` to `Attachment-4`, which
tell readers what the files are. Both are covered by the author's
signature (UN-RFC 0002 section 3), so nobody can swap a file after
posting, and by the postage (UN-RFC 0006).

## 4.1 The Blobs Header

```
Blobs: <blob-id>=<octets> *( SP <blob-id>=<octets> )
```

lists every blob the article references with its size in octets, as
stored (for encrypted blobs, the ciphertext size). It is always in the
outer header block, also in encrypted articles, because nodes need it.
The list has 1 to 4 entries, no blob ID twice, and sizes as in section
3.2.

Example:

```
Blobs: blob1:4f2c...q7=184213 blob1:mz9k...a2=1048576
```

## 4.2 Attachment Headers

Each attachment is described by a header `Attachment-<n>`, numbered from
1 without gaps, one per blob, in the order the client shows them:

```
Attachment-<n>: <blob-id>; type=<media-type>; size=<octets>
                [; name=<b64>] [; alt=<b64>] [; dim=<w>x<h>] [; key=<b64>]
```

(on one line; folding is forbidden, UN-RFC 0002 section 1).

| Parameter | Req.      | Meaning                                                   |
|-----------|-----------|-----------------------------------------------------------|
| `type`    | yes       | Media type of the file, without parameters, e.g. `image/png` |
| `size`    | yes       | Size of the file in octets (before encryption)            |
| `name`    | no        | File name, b64 of UTF-8, at most 128 octets before encoding |
| `alt`     | no        | Alternative text, b64 of UTF-8, at most 512 octets before encoding |
| `dim`     | no        | Width and height in pixels, for images                    |
| `key`     | encrypted | b64 of the 32-octet file key (section 3.3)                |

Unknown parameters MUST be ignored. `name` and `alt` are b64-encoded
because they are free text that may contain `;`, `=` or any script.

The alternative text describes the attachment in words. It is shown
where the file cannot be (a newsreader, a text-only terminal, a reader
who has not fetched it, a blind reader) and SHOULD be written by the
author. A client SHOULD prompt for it.

## 4.3 Where the Headers Go

| Article                         | `Blobs` | `Attachment-<n>`               |
|---------------------------------|---------|--------------------------------|
| Open, moderated, channel group  | outer   | outer                          |
| Closed group (UN-RFC 0004 6.5)  | outer   | inner, with `key`              |
| Inbox (UN-RFC 0009 2.3)         | outer   | inner, with `key`              |

In encrypted articles the `Attachment-<n>` headers MUST NOT appear in
the outer block: type, name and size of a file tell more about it than
its ciphertext does. Outside encrypted articles `key` MUST NOT appear.

## 4.4 Consistency

In articles whose `Attachment-<n>` headers are outer, a node MUST check
that the set of blob IDs in them equals the set in `Blobs`, and that
each `size` equals the size given in `Blobs`. In encrypted articles the
reader's client checks this after decryption, with each size in `Blobs`
being 40 octets more than the padded file (section 3.3): at least the
inner `size` plus 40, and at most `ceil(size / 65536) * 65536` plus 40.
The check does not depend on the group's current limit, so a later
change of it leaves earlier posts readable. A client MUST treat an
inconsistent article as having no attachments.

## 4.5 Postage

Attachments cost more than text. The difficulty an article with a
`Blobs` header must meet (UN-RFC 0006 section 3) is raised by

```
extra = 0                               if total <= 65 536
extra = ceil( log2( total / 65 536 ) )  otherwise
```

bits, where `total` is the sum of the sizes in `Blobs`: one bit per
doubling above 64 KiB. A 200 KiB screenshot costs 2 more bits (four
times the work), 1 MiB costs 4, and the largest possible article, with
8 MiB of blobs, costs 7. If UN-RFC 0025 (key ripening) is adopted,
`extra` is added after the reduction it gives a ripe key, so a ripe key
pays less for text but still pays for size.

Nodes compute `extra` from `Blobs` alone, so the rule works for
encrypted articles too.

# 5. Group Policy

## 5.1 The Manifest Field

A group allows attachments only if its current manifest (UN-RFC 0004
section 3) has the field

| Field         | Type   | Meaning                                    |
|---------------|--------|--------------------------------------------|
| `attachments` | object | Attachments allowed, under the rules below |

with members

| Member     | Type             | Req. | Meaning                                         |
|------------|------------------|------|-------------------------------------------------|
| `max_size` | integer          | yes  | Largest blob in octets, at most 4 194 304       |
| `types`    | array of strings | no   | Allowed media types; `image/*` allows a family  |

Without the field, attachments are not allowed. Without `types`, any
type is allowed. Unknown members MUST be ignored. A manifest with
`max_size` out of range is invalid.

The field applies to every group type, including chat groups (UN-RFC
0008), inboxes and local groups (UN-RFC 0009). A personal inbox that
allows attachments lets people send each other a screenshot privately.

## 5.2 Node Rules

A node that implements this document MUST reject (`441 permission`) an
ordinary article with a `Blobs` header when

1. the group's current manifest has no `attachments` field;
2. a size in `Blobs` exceeds `max_size` (for encrypted blobs, `max_size`
   plus 40);
3. the article breaks section 3.2 or 4.4; or
4. in an article whose `Attachment-<n>` headers are outer, a `type` is
   not allowed by `types`.

It MUST reject (`441 syntax`) `Attachment-<n>` headers without a `Blobs`
header. Control articles MUST NOT carry `Blobs`.

A node that does not implement this document passes `Blobs` and
`Attachment-<n>` on as unknown headers (UN-RFC 0000 section 5). Its
readers see the article without the files.

In encrypted articles nodes cannot see the types. Members' clients MUST
apply `types` themselves and treat a file of a type the group does not
allow as not attached.

## 5.3 Moderated Groups

A submission (UN-RFC 0009 section 3) carries the submitted article
inside an inbox article. The submitted article references its files as
plain blobs, as it will once approved. The submitter's client sends the
files to the moderators as encrypted blobs of the inbox article
(sections 3.3 and 4.3), so the nodes on the way see neither the files
nor that they belong to a submission.

Before approving, the moderator's client decrypts the files, computes
their plain blob IDs and MUST check that they equal the `Blobs` of the
submitted article. When it posts the approved article, it uploads the
plain blobs itself (section 6.2).

The inbox must allow attachments for this; a group's submissions inbox
SHOULD allow them whenever the group does, with `max_size` at least the
group's plus 40.

# 6. Transport

## 6.1 Capability

A node that implements this document adds to `CAPABILITIES` (UN-RFC
0005 section 2.3)

```
UNSEENET-BLOB <octets>
```

where `<octets>` is its largest accepted blob. A node that carries no
blobs at all MAY still implement section 5.2 and omit the capability.

## 6.2 Uploading: BLOBPOST and Staging

A client posts an article with attachments in two steps: it uploads each
blob, then posts the article.

```
C: BLOBPOST <blob-id> <octets>
S: 345 send blob
C: <exactly <octets> octets>
S: 245 blob staged
```

The node MAY refuse before the transfer, so the client does not send
megabytes in vain, and MUST check the ID and size after it:

| Response                      | Meaning                                       |
|-------------------------------|-----------------------------------------------|
| `245 blob staged`             | Received and held for this connection         |
| `445 size`                    | Larger than the node accepts                  |
| `445 limit`                   | Too much staged on this connection            |
| `445 hash`                    | The octets do not match the ID (after transfer) |
| `445 refused`                 | The node refuses this blob (section 7.3)      |
| `445 unsupported`             | The node carries no blobs                     |

A blob the node already stores is answered `245` at once, before any
transfer.

Staged blobs belong to the connection. When the client then posts an
article whose `Blobs` lists them, and the node accepts it, they become
stored. Staged blobs that no accepted article references are deleted
when the connection closes, and at the latest one hour after upload. A
node MUST allow at least 4 staged blobs and 8 MiB per connection, and
MAY allow more.

A node MUST reject (`441 blobs`) a `POST` whose `Blobs` lists a blob it
neither has stored nor has staged on that connection. The node the
article was posted to therefore always holds its blobs.

Staging is what keeps uploads from being a free way to fill a node's
disk. Without an article there is no postage, and without postage
nothing is kept.

## 6.3 Blobs Follow Their Article

Blobs are not flooded on their own. A blob node that accepts an article
with a `Blobs` header from a peer fetches the blobs **from that peer**
(section 6.4), within its own limits, before it offers the article to
its own peers. It then waits the random delay of UN-RFC 0005 section 5.5
as usual. If the fetch fails, it tries the other peers that carry the
group, and after at most 10 minutes it forwards the article without the
blobs it could not get.

This way a blob spreads along exactly the path its article takes and is
held, at each step, by the node that offered the article. A node asking
for a blob learns nothing it did not already learn from receiving the
article. In particular it never has to ask "who has this?" across the
network and find that only one node has: the node where the post was
written.

A node that is not a blob node (for this group, or at this size)
forwards the article without fetching. Its peers then try their other
peers, as above.

## 6.4 Fetching: BLOB

```
C: BLOB <blob-id>
S: 226 <octets> <blob-id>
S: <exactly <octets> octets>
```

| Response                      | Meaning                                      |
|-------------------------------|----------------------------------------------|
| `226 <octets> <blob-id>`      | The blob follows, as raw octets              |
| `430 no such blob`            | Not here (never had it, deleted or refused)  |
| `436 try later`               | Still fetching it from a peer                |

`BLOB` is used by readers and by peers alike, on any connection that is
not in streaming mode. A node SHOULD answer peers it has configured
(UN-RFC 0005 section 5.1, UN-RFC 0016) and MAY limit others.

A node MUST NOT distinguish in its answer between a blob it never had
and one it refused or deleted: both are `430`.

Blobs are sent as raw octets, not dot-stuffed or base64-encoded, because
the size is known in advance and the content is checked by its hash. The
connection continues with the next command after the last octet.

# 7. Keeping and Removing Blobs

## 7.1 Retention

A node keeps a blob as long as it keeps at least one article that
references it, and no longer than its own blob retention (section 8),
whichever ends first. A blob no stored article references any more MUST
be deleted. The article is never deleted because its blob is.

Blobs are never part of a group's state (UN-RFC 0017 section 2), and
manifests and other control articles cannot have them.

## 7.2 Archives and Cancels

An archive node (UN-RFC 0012 section 5) MAY keep blobs as long as it
keeps their articles, and MUST NOT keep them longer than the replication
window when the article carries `No-Archive: yes` or the manifest has
`"archive": false`. Archiving articles does not oblige an archive to
keep their blobs.

When a node deletes an article because of a valid cancel (UN-RFC 0004
section 7), it deletes the article's blobs unless another article it
keeps references them, and MUST NOT serve them afterwards. A client that
honours a cancel deletes the blobs it fetched for the target.

## 7.3 Refusing Blobs

A node operator MAY refuse any blob at any time, for any reason: delete
it, refuse to stage or fetch it, and answer `430`. The article stays and
is forwarded as before; readers see that the file is not available. A
node MAY also refuse articles that reference a blob it refuses
(`441 refused`).

Operators MAY follow **refusal lists** published by people they trust:
articles with `Content-Type: application/x-unseenet-blob-refusals` and a
canonical JSON body (UN-RFC 0004 section 3)

```json
{"blobs":["blob1:...","blob1:..."],"reason":"...","v":1}
```

in a group of the operator's choosing, signed by a key the operator has
configured. `reason` is optional, at most 200 characters. A node MUST
NOT follow refusal lists from keys its operator has not configured. No
list is followed by default, and nobody can make a node follow one.

A node applies refusal lists, and its own refusals, to every picture it
carries: blobs, profile pictures (UN-RFC 0022 section 10) and group
emoji (UN-RFC 0056 section 5), by the blob ID of the decoded image -
also a node that carries no blobs. Its node information then says
`"refusal_lists": true` in `policy` (UN-RFC 0011 section 4), as `blobs`
does for a blob node (section 8).

Refusal lists can only name plain blobs. Encrypted blobs look like
random data and differ every time (section 3.3), so no list can find a
file in a closed group or an inbox. An operator who is not willing to
carry what cannot be checked turns off `encrypted` (section 8).

# 8. Node Policy

A node that carries blobs adds to the `policy` object of its node
information (UN-RFC 0011 section 4)

| Field   | Type   | Meaning                                      |
|---------|--------|----------------------------------------------|
| `blobs` | object | The node carries blobs, under these limits   |

with members

| Member           | Type    | Meaning                                              |
|------------------|---------|------------------------------------------------------|
| `max_size`       | integer | Largest blob, as in `UNSEENET-BLOB`                  |
| `retention_days` | integer | How long blobs are kept at most                      |
| `encrypted`      | boolean | Whether it carries blobs of closed groups and inboxes |
| `refusal_lists`  | boolean | Whether it follows refusal lists (section 7.3)       |
| `daily_per_key`  | integer | Blob octets accepted per author key per day (8.1)    |
| `daily_per_group`| integer | Blob octets accepted per group per day (8.1)         |

A node without `blobs` carries none. Carrying blobs is never the
default: an implementation MUST ship with blobs turned off, and the
operator turns them on, for all groups or for groups matching wildmats
(UN-RFC 0005 section 5.1). A RECOMMENDED first setting is 1 MiB, 30
days, and `encrypted` off.

Clients SHOULD show the policy when the user adds a node (UN-RFC 0011),
and SHOULD warn before posting attachments through a node without
`blobs`, since the post would then reach others without its files.

## 8.1 Daily Quotas

A blob node SHOULD limit how many blob octets it accepts in a day per
author key and per group. RECOMMENDED: 32 MiB per key and 256 MiB per
group. Over the limit:

- articles from the node's own clients are refused with `441 quota`;
- articles from peers are accepted and forwarded as usual, but their
  blobs are not fetched, so the discussion goes on without the files.

Quotas are a local choice that only makes posting dearer, so every node
may set its own (UN-RFC 0025 section 1). A quota per key alone is
evaded with new keys; the quota per group is what bounds a group made
for distributing files.

## 8.2 Which Groups

A group owner who allows attachments decides only that a group *may*
have them. Which groups' blobs are carried is the operator's choice
alone. Operators SHOULD carry blobs only for groups they have chosen,
or for groups whose owner key they trust. If UN-RFC 0025 is adopted, a
node MAY carry blobs only for groups whose owner key has reached a
standing the operator chooses, so that a group created yesterday by a
new key gets no files carried.

# 9. Clients

## 9.1 Before Posting: Remove What the File Tells

The posting client MUST remove identifying metadata from a file before
it is uploaded, and MUST show the user the file exactly as it will be
sent:

- **Images** MUST be decoded and encoded anew from their pixels, into
  PNG, JPEG or WebP (animated WebP or GIF for animations), with no
  metadata: no EXIF (camera, GPS, time), XMP, IPTC, comments or embedded
  thumbnails, and colour converted to sRGB. Re-encoding rather than
  editing the file is REQUIRED because metadata hides in many places and
  a stripper always misses one.
- **PDF documents**: the client MUST remove the document information
  dictionary and XMP metadata, and SHOULD offer to send the document as
  images of its pages instead, which also removes scripts, forms,
  embedded files and links. If it cannot clean a PDF, it MUST say so.
- **Other files** are sent as they are, and the client MUST warn that
  they may contain hidden information about the author.

The **file name** leaks too: `Screenshot from 2026-10-18 11-53-02.png`
reveals the language of the desktop, the time zone and when it was
taken. A client MUST NOT send the original name by default. It SHOULD
propose a neutral one (`image-1.png`) that the user may change.

The client SHOULD also remind the user, the first time, that a
screenshot shows whatever was on the screen: other windows, a user name
in a title bar, a clock, open tabs. People forget.

The `Date` of an article is rounded (UN-RFC 0002 section 2.5); the
client MUST NOT let a file's own timestamps undo that.

## 9.2 Receiving: Treat Every File as Hostile

A file from the network is untrusted input in the most dangerous form
there is: image and document parsers are among the most attacked code in
existence.

- A client MUST verify the blob ID (section 3.1) and the size, and in
  encrypted groups decrypt and check consistency (section 4.4), before
  doing anything else with a blob.
- A client MUST determine the type from the content (its first octets),
  not from `type` or `name`, and MUST NOT display a file whose content
  does not match its declared type.
- A client MUST decode images and documents in a separate process with
  as few rights as the platform allows: no network, no access to the
  vault or other files, a memory and time limit. It MUST refuse images
  over 50 megapixels or with more than 1000 frames, which guards against
  "decompression bombs" that are small as files and huge in memory.
- A client MUST NOT render `image/svg+xml` as an image, since SVG can
  carry scripts and references to other resources. It MAY rasterize it
  in the restricted process.
- A client MUST NOT open a file in another program (an image viewer, a
  PDF reader, a browser, the operating system's "open") without an
  explicit action by the user each time, and MUST warn first that the
  program runs outside Unseenet and may connect to the internet without
  Tor. This matters most for the portable client, which runs on the
  host's own operating system.
- A client MAY fetch blobs automatically in groups the user reads, but
  MUST NOT decode them automatically from authors the user has chosen to
  ignore, and SHOULD let the user turn automatic display off.

A terminal client SHOULD show images with a terminal graphics protocol
(sixel, kitty, iTerm2) when the terminal supports one, and otherwise
show the alternative text, type and size, with a way to save the file.
A PDF SHOULD be shown as rendered page images, not opened.

## 9.3 Newsreaders

A newsreader that knows nothing of this document sees the `Attachment`
headers and the text. Authors SHOULD therefore write the text so that it
makes sense without the files. A local ONNTP proxy (as used for `tin`)
MAY offer the files as files in a directory the user chooses, applying
section 9.2.

# 10. Gateways

UN-RFC 0023 and 0024 keep binary content out of gateways in both
directions, and this document does not change that. A gateway MUST NOT
carry blobs to or from another network. When it exports an article with
attachments, it MUST drop `Blobs` and `Attachment-<n>` and MAY add a
line to the text saying how many files were not carried, including any
alternative text. Gateway profiles for other networks follow the same
rule unless they say otherwise.

# 11. Changes to Other Documents

- **UN-RFC 0001** section 1.1: the non-goal becomes "bulk binary file
  distribution". Small attachments to discussion are carried as opt-in
  blobs under this document.
- **UN-RFC 0002**: the headers `Blobs` and `Attachment-1` to
  `Attachment-4` are added (section 4). The article size limit is
  unchanged; blobs do not count towards it.
- **UN-RFC 0004**: the manifest field `attachments` (section 5) and the
  postage surcharge (section 4.5).
- **UN-RFC 0005**: the capability `UNSEENET-BLOB`, the commands
  `BLOBPOST` and `BLOB`, the responses `226`, `245`, `345`, `445`, and
  the posting refusals `441 blobs`, `441 refused` and `441 quota`
  (sections 6, 7.3 and 8.1).
- **UN-RFC 0011**: the policy field `blobs` (section 8).
- **UN-RFC 0012**: blob retention and archives (section 7).

# 12. Introducing Attachments (Informative)

Implementations are expected to arrive in two steps:

1. **Images.** `image/png`, `image/jpeg`, `image/webp` and `image/gif`,
   re-encoded as in section 9.1, shown in the client's restricted
   process. Nodes ship with blobs off; the project's own nodes turn
   them on for chosen groups.
2. **Documents.** `application/pdf` and plain text files, once page
   rendering in the restricted process and metadata removal work.

A group owner who wants only screenshots sets
`"attachments":{"max_size":1048576,"types":["image/*"]}`.

# 13. Rationale

**Why not MIME parts in the article, as in e-mail?** Every node would
store every file, whether anybody looks at it or not, and an operator
could carry text without files only by dropping whole articles. The
article limit would have to grow, for everybody. Separate blobs keep
both choices with the operator.

**Why not fetch blobs only when a reader asks, from whoever has them?**
Right after a post, only one node has its blobs: the one it was posted
to. The first node to ask around would find it, and so would anybody
watching who answers. That is precisely the information Unseenet
withholds by having no Path header and delaying forwarding. Letting
blobs follow their article (section 6.3) costs storage on blob nodes,
but it adds nothing to what peers already know.

**Why staging instead of postage on uploads?** The postage is computed
over the article, which names the blobs, so it already pays for them.
Holding blobs only for the connection that will post the article means
nobody can store anything without paying, and no second proof-of-work
is needed.

**Why SHA-256 and not a faster hash such as BLAKE3?** UN-RFC 0003 uses
SHA-256 throughout, and hashing 4 MiB with it takes milliseconds. The
`blob1:` prefix allows a change later.

**Why one blob per file, not chunks?** At 4 MiB a file fits easily in one
transfer over Tor, and a single ID per file keeps the headers, the
checks and the refusal lists simple. Larger files are not a goal.

**Why raw octets in BLOB and BLOBPOST?** Base64 would add a third to
every transfer over a network where bandwidth is scarce. The size is
announced in advance and the content checked by its hash, so there is
nothing for dot-stuffing to protect.

# 14. Security and Privacy Considerations

- **Metadata in files** is the main risk to the poster. Section 9.1
  makes removing it the client's job, but no client can remove what is
  visible in the picture itself: faces, a street, a screen.
- **Hostile files** are the main risk to the reader. Section 9.2 keeps
  decoding in a restricted process and never opens another program by
  itself. Programs outside Unseenet are a way out of Tor, especially for
  the portable client on Windows, macOS or Linux.
- **Sizes.** Nodes see the size of every blob, also of encrypted ones,
  and an exact size can identify a file (a known image has a known
  size). Encrypted files are therefore padded to a multiple of 64 KiB
  (section 3.3), which leaves a node only the size class. It costs at
  most 64 KiB per file, in storage, postage (section 4.5) and the daily
  quotas (section 8.1), which count the padded blob.
- **Linking.** The same plain file always has the same blob ID, so
  posting the same picture twice in open groups links the two posts.
  Encrypted blobs are always new (section 3.3).
- **Interest.** A reader's node learns which files the reader fetches,
  as it already learns which articles the reader reads (UN-RFC 0005
  section 7). Fetching automatically in subscribed groups hides which
  ones were looked at.
- **Origin.** Blobs follow their article (section 6.3); a design where
  they can only be fetched from the first node would reveal where the
  post was written. Implementations MUST NOT add "ask everybody" lookups
  for blobs.
- **Splitting files.** Anybody can write a client that skips section 9,
  create a group that allows attachments, and post a large file in
  pieces of 8 MiB. Nodes enforce postage, sizes, the manifest and
  staging, so this costs work, but SHA-256 is cheap on GPUs (UN-RFC 0006
  section 5): postage slows it down and does not stop it. Nor is the
  trick new: base64 or yEnc fits in text articles of 64 KiB just as well,
  and in an encrypted group no node can see it. This document does not
  make file distribution possible; it makes it something every operator
  can limit. What stops it is that blobs are off by default, carried
  only for groups the operator chooses (section 8.2), bounded by daily
  quotas (section 8.1) and short retention, and can be refused one by
  one or by list (section 7.3). A group made for distributing files
  reaches only nodes whose operators chose to carry it.
- **Storage exhaustion** is limited by the article limit on blobs
  (section 3.2), the postage surcharge (section 4.5), staging (section
  6.2), daily quotas (section 8.1) and each node's own limits
  (section 8).
- **Legal exposure of operators** is why blobs are off by default, why
  any blob can be refused without affecting the discussion, why refusal
  lists exist, and why carrying encrypted blobs, which no list can
  check, is a separate choice.

# 15. Example

A screenshot in an open group, with its alternative text. Lines are
shortened with `...`.

```
Unseenet-Version: 1
Message-ID: <k2m5a4e6rj2wl9zpn4c8y3h2t5vq3x7u@unseenet>
Newsgroups: dk.snak@ab3k5x7qwe2rtz4m
Date: Sun, 18 Oct 2026 10:00:00 +0000
From: Andreas
Subject: Sådan ser den nye trådvisning ud
Author-Key: ed25519:...
Content-Type: text/plain; charset=utf-8
Blobs: blob1:4f2cq7...=184213
Attachment-1: blob1:4f2cq7...; type=image/png; size=184213; name=aW1hZ2UtMS5wbmc; alt=VHLDpWR0csOmZXQgbWVkIHN2YXI; dim=1280x720
Signature: ed25519:...
Proof-Of-Work: sha256; bits=22; nonce=Qz81pa

Her er trådvisningen fra den nye klient (billedet er vedhæftet).
```

`name` decodes to `image-1.png` and `alt` to `Trådtræet med svar`.
The postage is the group's 20 bits plus 2 for 184 213 octets.

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
