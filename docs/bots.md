# Writing a bot

A bot is a program that posts by itself: release notes, a daily
picture, news from a feed. The Unseenet core has a small API for that,
`unseenet.core.poster`, which never asks anybody for anything.

## The smallest bot

```python
import asyncio
from unseenet.core.poster import Poster, load_key

GROUP = "alt.hello@<the channel's fingerprint>"

async def main():
    async with Poster(load_key(), from_name="Hello bot") as p:
        result = await p.post(GROUP, "Hello", "Hello from a bot.\n")
    print(result.message_id, "taken by", result.accepted or "nobody")

asyncio.run(main())
```

Run it with the key in the environment:

```sh
UNSEENET_SEED=<hex seed of the bot's key> python hello.py
```

That is all: the `Poster` starts its own Tor, posts the same article to
every node in the built-in list of known nodes, adds the postage each
node and the group ask for, and tries again later when a node says the
article cannot be taken yet.

## The key

Give the bot a key of its own. In a channel, the owner makes that key a
**poster** (command palette, *Make poster*); the owner's own key never
goes near the bot. If the bot's key leaks, the owner removes it from the
channel and makes a new one.

`load_key()` takes the first of:

- `key_file=`: a file with the seed in hex;
- `vault=`: an Unseenet vault, unlocked with the passphrase in
  `UNSEENET_VAULT_PASSPHRASE` (`identity=` picks one of its identities);
- `UNSEENET_SEED`: the seed in hex.

## Tor and nodes

`Poster(key, nodes=[...], tor=...)`:

- `nodes`: addresses (`xyz.onion` or `host:port`); the known nodes by
  default.
- `tor="auto"` (default): a Tor that is already running if
  `UNSEENET_TOR_SOCKS` names its SOCKS port, otherwise its own if any
  node is an onion service. `"own"`, `"none"` or a SOCKS port as a
  number choose directly.

## What a post looks like

`p.post(group, subject, body, kind="post", references=None,
content_type="text/plain; charset=utf-8")`:

- `kind="chat"` posts a chat line (no subject) instead of a post
  (UN-RFC 0028);
- `references` makes it a reply - in a channel open for comments, a
  comment (UN-RFC 0030).

The result says which nodes took it (`accepted`), which refused it and
why (`refused`), and which could not be reached (`unreachable`).

To avoid posting the same thing twice after a restart,
`await p.recent_threads(group)` lists the newest threads as
`(Message-ID, subject)`, and `await p.article(message_id)` fetches one.

## Be a good bot

- Say that you are a bot (a profile with `bot: true`, UN-RFC 0030
  section 6, once profiles are in the client), and name a person to
  contact.
- Post only what you may: credit the source and link to it, as its
  licence asks.
- Post rarely. A channel that floods is a channel people unsubscribe
  from.

Ready-made bots, and a runner for them, live in
[unseenet/unseenet-bots](https://github.com/unseenet/unseenet-bots).
