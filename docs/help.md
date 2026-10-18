# Getting help

## Ask in unseenet.help

New clients follow `unseenet.help` from the start - in the terminal client
and in the [graphical client](graphical.md). Ask there when something does not work or
is unclear: the client, the vault, nodes, names, groups. Say what you did
and what happened. Any question is welcome.

People answer when they can. The **help bot** steps in when nobody has:

| You write | The bot answers |
|-----------|-----------------|
| a new post (a thread) | after 30 minutes without a reply |
| a chat line that asks something | after 10 minutes without an answer |
| anything with `@helpbot` in it | right away |
| a reply to one of its answers | right away - ask your follow-up there |

Times in Unseenet are rounded to 10 minutes for privacy, so the wait can be
up to 10 minutes longer, and the answer itself takes the bot a minute or
two to write. When it finds nothing in the docs, it stays quiet - unless
you named it, then it says so.

## The help bot

*Unseenet help (bot)* is a program, not a person, and its profile says so.
It answers from what the project has written down:

- this documentation and the UN-RFCs,
- the README and other files of every public repository of the
  [Unseenet organisation](https://github.com/unseenet), new ones included,
- the issues and pull requests there - so it can say that something is a
  known problem, that it was fixed, or that it is planned for a coming
  version.

Every answer lists its sources with links, and when the bot cannot find
the answer it says so. It can still be wrong, so check the source when it
matters. It never gives its own advice on anonymity or protecting someone:
Unseenet is pre-alpha and not security reviewed.

The bot runs a small language model on the project's own server, so your
question is not sent to an AI company. It answers at most a few times per
thread and never another bot. Its code is
[unseenet/unseenet-helpbot](https://github.com/unseenet/unseenet-helpbot).

## Other places

- **`unseenet`** - talk about the project itself: the protocol, the
  software, ideas.
- **GitHub issues** - bugs and wishes for
  [the core, node and terminal client](https://github.com/unseenet/unseenet/issues),
  [the graphical client](https://github.com/unseenet/unseenet-web/issues) or
  [the gateways](https://github.com/unseenet/gateway/issues).
- **A security weakness** - report it privately, as described in
  [SECURITY.md](https://github.com/unseenet/unseenet/blob/main/SECURITY.md),
  not in a group or an issue.
- **[People](project/people.md)** - who is behind the project.
