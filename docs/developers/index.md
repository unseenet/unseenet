# Write a client

Every Unseenet client - the terminal client, the graphical client, the web
client, the command line, bots and gateways - is built on the same core:
`Session`, in the Python package `unseenet`. A client that uses it behaves
like the others without redoing the hard parts: keys and the encrypted vault,
Tor, postage and key ripening, checking signatures and manifests, closed
groups, edits, cancels and the offline cache.

There are three ways in:

| You write | Use | Read |
|---|---|---|
| A program in Python | `Session` (and `ClientRuntime`) | this page, then [the Session reference](session.md) |
| A program in any language | The local client API: HTTP and a WebSocket on 127.0.0.1 | [UN-RFC 0046](../spec/un-rfc-0046.md) and [Local client API](localapi.md) |
| Only reading, with a newsreader | ONNTP, which is NNTP over Tor | [Other newsreaders](https://unseenet.org/other-clients/) |

## A client in Python

```bash
pip install unseenet
```

A `Session` holds one vault - a person's keys, groups and settings, encrypted
([UN-RFC 0007](../spec/un-rfc-0007.md)) - and talks to nodes over Tor. It starts
its own Tor the first time it connects.

```python
import asyncio

from unseenet.client.session import Session
from unseenet.core.vault import Vault

GROUP = "test.unseenet@ph5fc5hop5232qsz"


async def main():
    vault = Vault.open("me.vault", "a long passphrase")   # made if it does not exist
    s = Session(vault)
    try:
        if not s.has_identity():
            s.new_identity("me", display="Me")
        if not s.nodes:
            s.add_node("<56 characters>.onion", default=True)

        s.subscribe(GROUP)
        await s.fetch_group(GROUP)                # new articles, checked and decrypted
        for msg, depth in s.threads(GROUP):       # as every client shows a group
            print("  " * depth + f"{msg.subject}  ({s.label_of(msg.author_key)})")

        # A new key works for a few minutes, once, before its first post
        # (key ripening, UN-RFC 0025); post() does that and the postage itself.
        msgid = await s.post(GROUP, "Hello", "My first post from Python.\n")
        print("posted", msgid)
    finally:
        await s.close()


asyncio.run(main())
```

What to know:

- **Everything that posts goes through `Session`**, so postage, ripening and
  the headers are the same in every client. A program that builds its own
  articles (a gateway, a bot) gives them to `post_article`.
- **Errors you should show** are `SessionError`, with a sentence meant for
  the user.
- **Before offering to write**, ask `write_permission(group)`: it says whether
  you may post or reply here, and if not, why, so people are told before they
  write.
- **A service with only a key** - a bot, a gateway - uses `Session.from_key`
  instead of a vault.

## Keeping up: `ClientRuntime` and events

A client that stays open uses `ClientRuntime`. It does the start-up steps in
the right order (the starter groups, the offline cache, the inbox, push from
each node) and fetches the groups you follow as posts arrive. What happens is
reported as events.

```python
from unseenet.client import events as ev
from unseenet.client.runtime import ClientRuntime

def on_event(event):
    if isinstance(event, ev.GroupUpdated):
        redraw(event.group_id)
    elif isinstance(event, ev.Status):
        show_status(event.text)

s.on(on_event)
runtime = ClientRuntime(s)
await runtime.start()      # runs until stop()
...
await runtime.stop()
```

The events are in `unseenet.client.events`: `GroupUpdated`, `GroupsChanged`,
`InboxReady`, `NodeState`, `TorState`, `Ripening`, `PowProgress`, `Status`,
`Refreshed` and `ReleaseOffer`.

## Words: "your", and "my" only when you speak

Every client words things the same way, so a person moving between them is not
surprised. Who is speaking decides, not who owns the thing:

- **The client speaks to you** - titles, navigation, dialogs, palette commands,
  messages: **your**. *Your feed*, *Your site*, *Your rules*, *Your nodes*,
  *Start your feed*, *Export your data*, *Show your key*. It matches *For you*
  beside them in the list.
- **You speak to the client** - a checkbox, a choice or a button in your own
  words: **my** is right. *Use my rules*, *My own bridges*, *Show on my posts*,
  and a message you send (*I restored my identity ...*).
- Without a pronoun when the label is clear without one: *Preferences*, *Edit
  profile*.
- Never both in one place: a list or a dialog says *your* or *my*, not each in
  turn.

This follows the Microsoft Writing Style Guide (second person; *my* sparingly, for
a person's control over an action) and Google's Material guidelines (*you* and
*your* for most text; do not mix *my* and *your* in the same context).

## Where things are

`Session` is one class, written in parts by area - groups, posting, private
posts, profiles and so on. [The Session reference](session.md) follows those
parts, and [The code](code.md) maps the whole package: where the core, the
client, the node and the command line live, and where new code goes.

The command line `unseenet` is itself a small client on `Session`, and a good
place to see how each function is used (`src/unseenet/cli/`).
