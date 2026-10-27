```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0052                                              October 2026
Category: Standards Track
Status: Draft
Updates: 0004, 0051

                     Unseenet: Tags
```

# Abstract

An author may tag their own post with a few words: its topics
(`politics`, `linux`) and, where it is needed, a content warning
(`spoiler`, `violence`). Tags are the author's own, signed with the post,
like the `Keywords:` header of Usenet or the hashtags of Mastodon. A
group's owner may give a group default tags. Tags let readers follow,
find, filter and score posts by topic with their own rules (UN-RFC 0051),
and let clients blur what an author warned about. Tags never change
postage, ripening or what a node carries. They live only in a header,
never in the text, so `#` keeps meaning a group reference.

# 1. Motivation

Feeds mix many kinds of content, and discussion groups drift. A reader
who follows two hundred feeds may want everything about Linux and
nothing about football; a reader of a film group wants to be warned
before a spoiler. The author knows best what a post is about and what it
shows, so the author says it.

Words others attach to a post - by hand or by a program - are labels,
with rules of their own (UN-RFC 0053). The same word can be both:
`politics` written by the author is a tag, `politics` set by a labeller
is a label. The content warnings are one shared set (section 4), so a
client treats an author's own warning and a labeller's warning alike.

# 2. Terms

Tag
: A word an author puts on their own post.

Topic tag
: A tag that says what a post is about.

Warning
: A tag from the fixed set of section 4, saying what a post shows.

Group tags
: Tags a group's owner gives every post in a group (section 5).

# 3. The Tags Header

An article MAY carry

```
Tags: politics, linux, spoiler
```

- 1 to 8 tags, separated by commas, each surrounded by optional white
  space;
- each tag 1 to 32 characters, in Unicode NFC: lower-case letters (any
  script), the digits `0`-`9` and `-`, beginning with a letter or a digit
  - so `økonomi` and `3d` are tags, `Linux`, `c++` and `two words` are
  not;
- no tag twice.

A header that breaks these rules is malformed (section 6). An author's
client lower-cases and normalises what the author types, and drops what
cannot be a tag, before it signs.

The header is part of the signed article (UN-RFC 0002). In a closed
group (UN-RFC 0004) and in a private post (UN-RFC 0009) it goes inside
the ciphertext with the other inner headers, so nodes never see it.

Tags are set where a post is written - in the compose box, not in the
text. A client MUST NOT read tags from a post's text: `#word` in the text
is a group reference (UN-RFC 0031) and nothing else. A client MAY offer,
while the author types `#word` that names no known group, to make it a
tag; the text the author sends is unchanged.

Tags belong on posts, chat lines, feed entries and comments. A manifest,
a control article and a reaction (UN-RFC 0048) have none.

# 4. Warnings

The warnings are a fixed set, shared with content labels (UN-RFC 0053):

| Warning     | The post shows or tells                          |
|-------------|--------------------------------------------------|
| `profanity` | Swearing, slurs, crude language                  |
| `sexual`    | Sexual content                                   |
| `nudity`    | Nudity, not sexual                               |
| `violence`  | Violence, also described                         |
| `gore`      | Blood, injury, death in detail                   |
| `spoiler`   | The plot or outcome of a film, book, game or match |

The set is small on purpose: a client must be able to offer a choice for
each. A new warning needs an amendment to this document.

What a client does with a warning is the reader's choice: show it, blur
it behind *Show anyway*, or hide it. Clients SHOULD blur by default, and
MUST NOT hide a post silently (as UN-RFC 0045 section 7.3): what is
hidden or blurred says why, one action from being shown. The reader's
own posts are never blurred or hidden for them.

A warning is not a sanction. It does not make a post less visible to
anyone who did not choose that, and it is never a reason to report a
post (UN-RFC 0045).

# 5. Group Tags

A group's manifest (UN-RFC 0004 section 4) MAY hold

| Field  | Type          | Meaning                                    |
|--------|---------------|--------------------------------------------|
| `tags` | list of tags  | 1 to 8 tags every post in the group has    |

for example `dk.politik` with `["politics"]`, or an adult group with
`["sexual"]`. A client treats a post as having its own tags and its
group's, and shows them apart: the author's as the author's, the group's
as the group's. A group's tags are the owner's statement about the
group, not the author's about the post.

# 6. Nodes

A node checks the form of a `Tags` header it can read (section 3) and
refuses an article with a malformed one (`441 syntax`), as it checks any
other header. It checks a manifest's `tags` the same way.

That is all a node does with tags. It MUST NOT carry, hide, forward,
delete or price an article differently because of its tags, and tags
MUST NOT change postage or ripening (UN-RFC 0025). A node MAY let
newsreaders ask for the header (`HDR Tags`, UN-RFC 0005).

# 7. Clients

A client:

- shows a post's tags, and its group's, near the post;
- lets the author set tags where they write - for example as chips
  under the text - with the warnings offered first;
- can show everything with a tag in the groups and feeds the reader
  follows;
- blurs or hides warnings as the reader chose (section 4);
- lets the reader's rules use tags (UN-RFC 0051, `tagged`).

# 8. Gateways

A gateway (UN-RFC 0024) maps the tags of the other network into the
`Tags` header: Nostr `t` tags, Mastodon and Matrix hashtags. It
lower-cases and normalises them, drops what cannot be a tag, and keeps
the first 8. Content warnings of the other network (Mastodon's
`spoiler_text`, Nostr's `content-warning`) map to the nearest warning of
section 4 where one fits, else to none.

# 9. Rationale

**Why only in a header.** In the text, `#` already means a group
reference (`#dk.snak.marsvin`, UN-RFC 0031); reading `#word` as a tag
too would make every unknown group name a tag and every tag a broken
link. A header keeps the text as the author wrote it, is signed with
it, and is what Usenet's `Keywords:` was.

**Why so few and so plain.** Eight tags is enough to say what a post is
about; more is keyword spam. A simple character set lets rules name tags
without quoting (UN-RFC 0051) and makes `Linux`, `linux` and `LINUX` one
tag.

**Why warnings are fixed.** A client offers a setting per warning. With
an open set, a reader could never know what they had chosen not to see.

**Why tags never sanction.** Tags are the author's own words. If they
could make a node or a price treat a post differently, honest authors
would stop warning.

# 10. Security and Privacy Considerations

- In open groups tags are public, like the post. They say what a post
  is about in a form a program reads easily; an author who does not want
  that leaves them out.
- In closed groups and private posts tags are inside the ciphertext.
- An author can mis-tag. Readers' rules weigh tags as the reader wants,
  and labellers (UN-RFC 0053) can say otherwise.

# 11. Changes to Other Documents

- UN-RFC 0004 section 4: a manifest may hold `tags` (section 5).
- UN-RFC 0051 sections 4.6 and 4.7: the condition `tagged` (a separate
  amendment).

# Copyright Notice

Copyright (c) 2026 the persons identified as the document authors.
This document is licensed under CC BY 4.0, see `rfc/LICENSE.md`.
