# The operator box

A server - a council replica, a node, a gateway, a spam-report issuer, an entrance, a
bot - sometimes needs a person: a change held for you, a hearing about to close, a disk
filling up. The **operator box** lets your servers tell you in your everyday client, a
phone through a web entrance included, and lets you answer them there. No SSH, no
program of its own. It is specified in UN-RFC 0065.

| Server | Operator box |
|--------|--------------|
| Council replica | Yes, from 0.8.0 - see [Running a replica](replica.md#from-your-everyday-client-the-operator-box) |
| Node, gateway, issuer (watchman), entrance, bots | Planned for 0.9 |

## In short

- The box is a **team inbox** (UN-RFC 0047): a mailbox that up to 16 keys read.
- **You own it**, with a key made for this and kept in a vault of its own. The owner
  key is needed only to change who reads, so it can stay offline.
- **Your servers read it**, each with a key it makes itself, and so do **you** and
  any other operators, each with a team key in their everyday client.
- The servers post **notices** there - once per matter, and again when it is over.
- You **answer a server's message** to give it a command: `status`, `help`,
  `agree ...`. The answer goes to that server only.
- To start a new message to one server, pick it as the recipient (in the command line:
  `unseenet operator say <box> <server> <text>`). Your client knows the box's servers
  by name, so you never have to remember them.
- `help`, `status` and `notices` written to nobody in particular are answered by every
  server - an easy way to ask how they all are.
- Anything that changes something asks for a **code**: `second ABCD` is answered
  "Second proposal ABCD ...? Answer *yes 4821* within 30 minutes". Anything else
  cancels it, so a typo never acts, and only the one who asked can confirm. A command
  over an hour old is not carried out.
- Some things are done only on the server itself, never from chat: anything that
  cannot be undone or that touches keys.
- **Notices only** is the default. Acting from chat is turned on per server.

## Setting it up

You need two things on your own computer:

- the `unseenet` command line (it comes with the client);
- **your everyday key** - the key of the identity your everyday client uses. In the
  command line: `unseenet whoami`. It looks like `ed25519:5snjk...`.

### 1. Make the box (once)

The box is owned by a separate **operator vault**, so the key that decides who reads
is not the one you use every day. Make it with a passphrase you keep:

```bash
V="--vault $HOME/operator.vault"
unseenet $V id-new operator --display "My servers"      # asks for a NEW passphrase
unseenet $V node-add <a node's onion address>           # e.g. the node you use every day
unseenet $V operator create operator --server-name "My servers"
```

`create` prints the box's **Group ID**, like `operator@4pqu54rxy3hl4zh5`. Write it down.

Every later `unseenet $V ...` asks for the **operator vault's** passphrase - the one
you chose just now, not your everyday one.

**Back up `operator.vault`.** Without it nobody can change who reads the box.

### 2. Add a server

Each server's page says how to give it the box. For a replica:

```bash
sudo unseenet-replica operator operator@4pqu54rxy3hl4zh5 --name replica1
```

A few minutes later, run `sudo unseenet-replica operator` again. It shows the
replica's **key** and the exact line to run on your computer:

```bash
unseenet $V operator add-server operator@4pqu54rxy3hl4zh5 ed25519:...
```

Do the same for each server, giving each its own `--name`.

### 3. Add yourself

```bash
unseenet $V operator add <your everyday key> --channels operator@4pqu54rxy3hl4zh5
```

The invitation lands in your everyday inbox. Accept it in your client (or
`unseenet team invitations` and `unseenet team accept <message-id>`). The box then
shows up among your inboxes, and each server says hello there. Answer a hello with
`status` to see that it works.

### Other operators

Add them the same way, with their everyday key. They see every notice and every
answer, so two people do not act on the same thing. Up to 16 keys read a box, servers
and people together.

```bash
unseenet $V operator add <their key> --channels operator@4pqu54rxy3hl4zh5
unseenet $V team readers operator@4pqu54rxy3hl4zh5     # who reads it, as team keys
unseenet $V operator remove <their team key> --channels operator@4pqu54rxy3hl4zh5
```

Removing a reader takes away their say at once.

## Useful commands

```bash
unseenet operator channels                         # the boxes you read or own
unseenet operator servers <box>                    # the servers in a box, by name
unseenet operator say <box> replica2 status        # a new message to one server
unseenet team reply <box> <message-id> status      # answer a server's message
```

## When a server should have a box of its own

One box links the servers in it: whoever sees the box sees one inbox serving all of
them, and **whoever seizes one server can read what all of them were told**, and learn
that one person runs them. For servers already known to be yours that costs nothing.

Give a server a box of its own (another `operator create`) when it has to stay apart:
a hidden server you do not want tied to your name, or a server you run with other
people. Your client shows all your boxes together.

## Good to know

- **Posting costs postage.** Each message a server posts is a sealed post with proof of
  work, which takes a small machine a few minutes. That is why notices are gathered:
  ordinary ones into a digest at most once an hour, warnings after a few minutes,
  alarms at once. A server never holds up its own work for it.
- **Timing.** A server posts when something happens to it, so somebody who can tell
  when a hidden server is up might link it to its box. Turn the box off
  (`--off`) where that matters more.
- **Keep messages short-lived** (30 days or less). If a server is seized, remove its
  key from the box (`operator remove`) and let it make a new one.
- **The owner is trusted** by everybody in the box: it chooses the readers, and could
  add a key of its own.
