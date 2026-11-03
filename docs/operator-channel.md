# Operator channels

A server - a node, a council replica, a gateway, a spam-report issuer, an entrance,
a bot - sometimes needs a person: a disk filling up, a change held for you, a hearing
about to close. An **operator channel** lets the server tell you in your everyday
client, a phone through a web entrance included, and lets you answer it there. No
SSH, no program of its own. It is specified in UN-RFC 0065.

| Server | Operator channel |
|--------|------------------|
| Council replica | Yes, from 0.8.0: [Running a replica](replica.md#from-your-everyday-client-the-operator-channel) |
| Node, gateway, issuer (watchman), entrance, bots | Planned for 0.9 |

## How it works

The channel is a **team inbox** (UN-RFC 0047): a mailbox that up to 16 keys read.

- Its **owner** is a key of yours made for this, kept in a vault of its own. It is
  needed only to change who reads, so it can stay offline.
- Its **readers** are the server itself, with a channel key it makes and keeps, and
  each operator, with a team key in their everyday client.
- The server posts **notices** there - once per matter, and again when it is over -
  and reads its operators' **commands**, answering each one where every reader sees
  the answer.
- Anything that changes something needs a **confirmation code**: `second ABCD` is
  answered with "Second proposal ABCD ...? Answer *yes 4821* within 30 minutes".
  Anything else cancels it, so a typo never acts, and only the operator who asked can
  confirm. A command over an hour old is not carried out.
- Some commands are taken only on the server itself, never from chat: anything that
  cannot be undone or that touches keys.
- **Notices only** is the default. Operators can then ask `help`, `status` and
  `notices`; acting from chat is turned on per server (`--commands`).

Nobody learns from the channel who runs the server: inbox posts are sealed, the
manifest shows only keys made for this, and an answer says it came from the server's
name, not from the person who wrote it.

## One channel per server

Give each server a channel of its own, also when you run several. One channel for
all of them would tie them together - a hidden replica to a public node - and a
server seized by somebody would show them what the others were told. Your client
shows all your channels together, so you still see your servers in one place.

## Setting up (the owner)

Use the `unseenet` command line in a vault of its own for the owner key:

```bash
V="--vault $HOME/operator.vault"
unseenet $V id-new operator --display "My servers"          # a new vault and key
unseenet $V node-add <a node's onion address>
unseenet $V operator create operator.replica1 --server-name replica1
```

`create` prints the channel's Group ID. Give it to the server (each server's page
says how); the server then shows its **channel key**. List it:

```bash
unseenet $V operator add-server <group> <the server's channel key>
```

Then add yourself, with the key of the identity your everyday client uses:

```bash
unseenet $V operator add <your everyday key> --channels all
```

The invitation lands in your everyday inbox; accept it there (or
`unseenet team invitations` and `unseenet team accept <message-id>`).

**Back up the owner's vault.** Without it you can no longer change who reads.

## More operators

Each operator is a reader with a team key of their own, up to 15 per server. They
all see every notice and every answer, so two people do not act on the same thing.

```bash
unseenet $V operator add <their key> --channels operator.replica1@...,operator.node3@...
unseenet $V operator add <their key> --channels all          # every channel you own
unseenet $V operator remove <their team key> --channels all
unseenet $V operator channels                                # the channels you own or read
```

Removing a reader takes away their say at once. The owner is trusted by everybody in
the channel: it chooses the readers, and could add a key of its own.

## Privacy

- A server posts when something happens to it, so somebody who can tell when a hidden
  server is up might link it to its channel. Ordinary notices are gathered into a
  digest at most once an hour, and warnings wait a few minutes; alarms go at once.
  Leave the channel off where that matters more.
- A seized server gives away its channel key: whoever has it reads what was sent to
  the channel while it was a reader. Keep the channel's messages short-lived (30 days
  or less), and when it happens, remove the key and let the server make a new one.
