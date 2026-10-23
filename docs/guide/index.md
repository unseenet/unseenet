# The Unseenet guide

This guide explains Unseenet from end to end - why it exists, how a post
travels, what a node does, how the clients are built - in ordinary prose,
with the technical words introduced as they are needed. It sits between
[About Unseenet](../why.md), which is written for people who have never
heard of Tor, and the [UN-RFC series](../spec/index.md), which is written
for people who build nodes and clients.

!!! note "The specification decides"
    This guide is not normative. It simplifies on purpose, and it may lag
    behind a change. When the guide and a UN-RFC disagree, the UN-RFC is
    right - and the guide has a bug. Every chapter ends with the UN-RFCs it
    covers, for when you need the exact rules.

## Chapters

1. [Why it matters](why.md) - privacy, freedom, and why the shapes we know
   from Usenet, Discord, Facebook and Mastodon are worth having without an
   owner.
2. [A post's journey](journey.md) - one post followed from the keyboard to
   another reader's screen, and what everybody on the way learns.
3. [Identity](identity.md) - keys, the vault, names, key ripening and profiles.
4. [Groups](groups.md) - hierarchies, manifests, chats and posts, closed
   groups, feeds, pages and moderation.
5. *The node* - what it stores, peering, the known-node list, files, and
   what an operator can and cannot see. *(coming)*
6. *The clients* - one core shared by the terminal client, the graphical
   client, the CLI and others; portable and bootable. *(coming)*
7. *Out into the world* - web entrances, gateways to Usenet, Matrix and
   Nostr, and portals. *(coming)*
8. *The threat model in plain words* - what is hidden from whom, and what
   Unseenet does not protect against. *(coming)*
9. *Build your own* - which UN-RFCs to read, in which order, to write a
   node or a client. *(coming)*

Some of what the guide describes is still being built. Where that is so,
it says which release brings it.
