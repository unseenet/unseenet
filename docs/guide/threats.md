# The threat model in plain words

The earlier chapters say what Unseenet does. This one says what it
protects you against, what it does not, and which choices trade one for
the other. It is written to be honest rather than reassuring: a privacy
tool that oversells itself is dangerous to exactly the people who rely
on it most.

!!! warning "Before anything else"
    Unseenet is pre-alpha, and neither the protocol nor the code has had an
    independent security review. Everything below is what the design
    intends. Until it has been reviewed, do not rely on it to protect anyone
    whose safety depends on it - use tools that have been reviewed, such as
    Tor Browser, Tails and SecureDrop.

## What Unseenet is built to protect

1. **Where you are.** No node, peer, reader or group owner learns your IP
   address or location. Everything goes through Tor.
2. **Where the servers are.** Nodes are onion services with no address
   outside Tor, so they cannot be found, and the network cannot be
   switched off by taking down a few known machines.
3. **Who wrote what - from forgery.** Every post is signed. Nobody can
   post in your name or change what you wrote, and nobody has to trust a
   server to know it.
4. **What private things say.** Closed groups, inboxes and private posts
   are encrypted end to end. Nodes carry them but cannot read them.
5. **Where a post entered the network.** No route is recorded, and nodes
   wait a random time before passing posts on, so a node that receives a
   post cannot tell whether its peer wrote it down or passed it along.
6. **Your stick.** Everything a client keeps is in one encrypted vault;
   a lost or seized stick reveals nothing without the passphrase.
7. **Your voice.** Nobody can remove a post from the whole network, take
   a person off it, or stop anyone from running a node.

## Nobody to track or profile you

On today's platforms, being tracked is not a breach - it is the business.
Every account is tied to an e-mail address and usually a phone number.
What you read, what you like, how long you look at something, where you
are and which other sites you visit are collected, joined into a profile,
and used to decide which advertisements you see and what the feed shows
you next. The same profile can be handed to a government that asks, sold
to a data broker, or leaked.

None of that exists on Unseenet, because the things it is built from do
not exist here:

- **There is no account to tie you to.** No e-mail address, no phone
  number, no name, no payment card. A key is made on your own computer and
  says nothing about who holds it.
- **There is no company in the middle.** Nobody collects data from
  everyone, so nobody holds a database that could be sold, leaked or
  demanded. A government that wants to know who wrote something has no one
  to send the request to.
- **There is nothing that follows you around.** No tracking pixels, no
  cookies, no advertising IDs, no "log in with" buttons, no device
  fingerprinting. Clients fetch nothing from the open web unless you ask,
  so even a link in a post cannot report back that you read it.
- **There is no algorithm watching what you do.** Groups show posts in the
  order they were written, and the timeline is the feeds you chose,
  newest first. Nothing measures what you linger on, because nothing needs
  to: there are no advertisements to target and no engagement to sell.
- **No single node sees the whole picture.** The node you use knows which
  groups some client reads, but not who or where that client is, and it
  sees only its own users. No one sees everyone.

That does not make you invisible - nothing can. What you post in a public
group is public, and anyone may read it, keep it and study it, just as on
the old Usenet. Everything one key writes can be linked to that key, and
someone who reads it all may guess a lot from your writing, your topics
and your hours. The difference is who holds the pieces: on a platform the
owner holds all of them, about everyone, by design; on Unseenet nobody
does, and what can be linked to you is what you chose to publish under a
key - which is why it is worth keeping separate identities for separate
parts of your life.

## Who sees what

| Who | Can see | Cannot see |
|-----|---------|------------|
| **Your internet provider, the café Wi-Fi** | that you use Tor | which nodes you use, what you read or write |
| **The node you use** | which groups you read; that the posts you send came from *a* client connected to it, signed by your key | your IP address, your location, who you are unless you say |
| **Other nodes** | posts in public groups; which peer each post came from | where a post was written, which node its author uses |
| **Any node, for closed groups and inboxes** | that a group or inbox exists, roughly when and how much is posted | what is written; for inboxes, who sent it |
| **Readers of a public group** | what your key posted, and your name if you gave one | where you are, which node you use |
| **A web entrance** | the IP address of visitors who do not use Tor Browser | passphrases, keys, closed groups, private posts |
| **A gateway** | public posts of the groups it carries, like any node | where posts were written, who holds which key |
| **Someone who takes your stick** | an encrypted file | anything in it, without your passphrase |
| **Someone who seizes a running node** | the public groups it carries, the encrypted rest | anyone's keys or closed-group secrets - nodes never get them |

## What Unseenet does not protect against

- **Yourself.** What you write, how you write it, the topics you know, the
  hours you are awake and who you tell can all give you away. A key you
  use for years becomes a name of its own.
- **Your own computer.** A computer with a keylogger, a screen recorder or
  malware sees everything you type and read. The bootable stick exists for
  this: a compromised Windows or macOS installation never runs.
- **Being forced.** Nothing technical helps if someone can make you give
  up your passphrase.
- **An adversary who can watch the whole internet at once.** Tor does not
  claim to defeat someone who can see traffic everywhere and correlate
  timing, and neither does Unseenet. The random delays make it harder; they
  do not make it impossible.
- **Your node knowing what you read.** The node you connect to learns which
  groups you follow. Subscribe to whole hierarchies, or use several nodes,
  if that matters to you.
- **Being seen to use Tor.** Your network sees Tor traffic. Where that is a
  problem, or Tor is blocked, use a bridge.
- **Old secrets after a key is lost.** There is no forward secrecy for
  inboxes and closed groups: someone who gets an owner's key can read what
  was stored for it. Keep retention short for sensitive inboxes.
- **What others already have.** A withdrawn post may still be kept by
  people who read it, by software that ignores the rules, and by
  archives. Someone removed from a closed group keeps what they already
  received.
- **Signatures cutting both ways.** A signed post is proof that your key
  wrote it - to anyone. A private post where you sign with your real key is
  provable to anyone its recipient shows it to. Leave the signature out
  where you need to be able to deny it.

## Nodes you do not trust

You do not have to trust nodes, but you depend on them to be served.
A dishonest node cannot forge or change posts - your client checks every
signature, every manifest and every withdrawal itself. What it can do is
**withhold**: not pass on, or not show you, some posts. The answer is the
same as on Usenet: posts reach many nodes by many paths, and a client can
use more than one node. A node can also try to profile its readers by what
they read, which is why logging is kept to a minimum and why reading whole
hierarchies hides interest.

## Choices that trade privacy for something else

Some features are worth having and cost a little privacy. Unseenet makes
them visible, and mostly lets you choose:

| Choice | What you gain | What it costs |
|--------|---------------|---------------|
| A **chat group** with fast delivery | messages in seconds | no random delay, so the point of entry is easier to guess |
| A **name** such as `@yourname` | people recognise you | everything that identity writes is linked to the name |
| A **profile** with links | people find you elsewhere | the links tie the key to those accounts |
| The **browser** through a web entrance | nothing to install | the entrance sees your IP address unless you use Tor Browser |
| Posting in a group with a **portal** | reach people on another network | your post is published outside Tor, possibly for years |
| A **file** on a post | show a picture or PDF | metadata is stripped, but what the picture shows is not |
| One identity **everywhere** | simplicity | everything you do can be linked; use one per part of your life |

## Spam and attacks on the network

- **Spam** costs postage - a small proof-of-work per post - and keys must
  ripen before they post cheaply, so throwaway keys are expensive. Nobody
  decides who may post; the cost is the same for everyone.
- **Flooding a node** with connections is limited by Tor's own
  proof-of-work defence for onion services, which nodes should turn on.
- **Fake nodes** on the list new users are offered are checked from
  outside: listed nodes must really exchange posts with the others.
- **Fake names** are what petnames are for: the name you gave someone in
  your own client always wins over any name a stranger claims.

## What you can do

- Use the **bootable** stick, or Tails, when it matters.
- Use **separate identities** for separate parts of your life, and give a
  name only to the identity you want recognised.
- Follow **whole hierarchies** rather than a single sensitive group.
- Wait before you reply to a private post if timing could link you.
- Keep **copies of your vault** somewhere safe - there is no recovery.
- Read what your client tells you: it says when a group is a fast chat,
  has a portal, or when you are on the open web.

**Details:**
[UN-RFC 0001](../spec/un-rfc-0001.md) section 7,
[0005](../spec/un-rfc-0005.md) section 7 (what nodes learn),
[0007](../spec/un-rfc-0007.md) (data at rest),
[0008](../spec/un-rfc-0008.md) (chat and timing),
[0009](../spec/un-rfc-0009.md) section 6 (inboxes),
[0023](../spec/un-rfc-0023.md) (gateways),
[0025](../spec/un-rfc-0025.md) (key ripening),
[0043](../spec/un-rfc-0043.md) (web entrances).
See also [Tor and Tails](../tor.md).
