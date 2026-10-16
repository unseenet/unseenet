# Your responsibility as a node operator

Running a node means storing and passing on posts written by other
people. That is worth thinking about before you start, especially if your
node is open to anyone.

## What Unseenet does to make this easier

- **Text only.** Posts are at most 64 KB. There are no binary files,
  images or attachments - the thing that got many Usenet servers into
  trouble.
- **You choose what you carry.** With `new_groups = "trusted"` or
  `"manual"` you decide which groups your node accepts, and with each
  peer's `groups` pattern you decide what you pass on. See
  [Configuration](configuration.md).
- **Everything is signed.** Nobody can make it look as if *you* wrote
  something, and posts cannot be changed in transit.
- **Closed groups are unreadable to you.** You carry ciphertext. You can
  still refuse to carry a closed group.
- **Cancels work.** An author, or a group's owner or moderators, can
  withdraw a post, and nodes delete it. An owner can also remove a whole
  group from the network.

## What you should do

- **Know your peers.** Peer with people you know, using node keys, and keep
  `require_peer_auth` on so only they can push posts to you.
- **Decide on a policy.** For a node among friends, `accept` is fine. For a
  node open to strangers, consider `trusted`, and say publicly which groups
  you carry.
- **Act on problems.** If a group carries content you do not want to
  host, drop it from your node with `--drop-group` (see
  [Operations](operations.md#dropping-a-group)). The node deletes it and
  refuses it from then on.
- **Read your contact inbox.** Readers can [report a post](../client.md#reporting-a-post)
  to you through your node's contact inbox (UN-RFC 0011). Look at reports
  and act on them: drop the group, or turn on
  [`honour_blocks`](configuration.md#honour_blocks-maintainers-blocks) to
  follow the blocks of hierarchy maintainers.
- **Know the law where you live.** Hosting other people's content is
  treated differently from country to country. Unseenet's design reduces
  the risk; it does not remove your responsibility.

## Privacy of your readers

Your node sees which groups a client reads (but not who the client is).
Do not log more than you need. The node does not log reading activity by
default; keep it that way.
