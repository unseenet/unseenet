# Out into the world

Inside Tor, Unseenet is a closed world: nodes have no address outside it,
and everyone who takes part runs an Unseenet client. That is what makes it
hard to watch and hard to switch off - but a network nobody can reach is
not much use either. This chapter is about the doors between Unseenet and
the rest of the internet: **web entrances**, which let an ordinary browser
in, and **gateways**, which connect Unseenet to other networks such as
Usenet, Matrix and Nostr.

<!-- unseenet:diagram world -->

Every door is optional, sits at the edge, and is run by someone who chose
to run it. None of them changes what happens inside: nodes stay hidden,
posts stay signed, and private things stay encrypted.

## Web entrances: a browser way in

Most people will not download a program or boot from a stick before they
have seen what a network is like. A **web entrance** lets them in from an
ordinary browser, on a computer, phone or tablet, with nothing to install.

What the entrance does is small on purpose. It serves the graphical
client to the browser, and then it carries the browser's connection to a
node over Tor, copying bytes both ways - nothing else. All the real work
happens in the browser: the client there opens the vault, signs,
encrypts, decrypts and pays the postage itself. So the entrance:

- never sees a passphrase, a private key, or what is in a closed group or
  a private post;
- cannot change or forge a post, because every post is signed and checked
  by the client;
- writes nothing about its visitors - no access log, no addresses in its
  errors.

### The honest price

An entrance stands on the open web, and that has a cost, which the
browser client shows in a bar at the top at all times:

- **The entrance sees your IP address** - unless you use Tor Browser and
  the entrance's onion address.
- **Your network sees you visit it**, so someone watching can tell you use
  Unseenet.
- **You trust code served from the web.** Versions of the client are
  signed, and clients check them, but the page is still delivered by the
  entrance.

What does not change is why Unseenet is worth using in the first place:
groups and nodes still cannot be removed by anyone, nobody can delete or
change someone else's post, and nodes still never learn where anyone is.
An entrance is for people who want that freedom more than full anonymity.
Those who need to hide that they use Unseenet at all should use the
portable or bootable client.

### When an entrance is blocked

An address on the open web can be blocked. Unseenet answers that with
numbers: anyone can run an entrance - one install command on a free cloud
VM - and the project publishes a signed list of known entrances in the
network. If the browser's entrance stops answering, the client switches to
another from the list. The list can also be saved as a small file, kept,
and passed to friends; opened from disk, it shows which entrances answer
and opens one. Every entrance someone else runs makes the network harder
to block.

## Gateways: other networks in

A **gateway** brings groups, rooms or areas from another network into
Unseenet, and can carry answers back. Each network has its own top-level
hierarchy, so a reader always sees where a group comes from:

| Network | In Unseenet | State |
|---------|-------------|-------|
| Usenet | `usenet.*`, e.g. `usenet.comp.misc` | import, in the lab |
| Matrix (public, unencrypted rooms) | `matrix.*` | import and export, tested |
| Nostr (NIP-29 groups) | `nostr.*` | import, export and portals, in the lab |
| FidoNet | `fido.*` | planned |

A gatewayed group is an ordinary **moderated** group whose moderator is
the gateway. That is the trick that makes gateways cheap: nodes and
clients carry such a group like any other and need to know nothing about
gateways. Every imported post is signed by the gateway and says where it
came from - the network, its ID and date there, and its author there. From
Nostr, where posts are signed too, the original signed event comes along,
so a reader can check that the gateway did not change it.

When you answer a gatewayed post from Unseenet, your answer goes to the
gateway as a submission, the way posts reach the moderators of any
moderated group, and the gateway sends it on under its own name.

### Consent, and more than one gateway

A gateway does not take a room or group without being asked. On Matrix,
the room's moderators invite the gateway's account, which is the room's
consent; the gateway's operator then approves it, and the room appears as
a group. Removing the gateway from the room stops it.

A group need not depend on one gateway. Several can serve the same group:
they take turns, carry each message once, and take over for one another
if one stops. Gateways announce themselves in a directory group, so people
on other networks can find one to invite, and a gatewayed group stays
active only while at least one of its gateways still announces it.

## Portals: Unseenet groups out

A **portal** goes the other way. An Unseenet group - say `dk.snak` - gets
a counterpart on another network, such as a Nostr group or a Matrix room,
where people can read and write without Unseenet software. Their messages
come into the Unseenet group through the gateway, marked with where they
came from.

A portal publishes what Unseenet authors wrote *outside* Tor, where it may
be kept and indexed for years. That is a different promise from the one
the group's authors chose, so:

- **only the group's owner can open a portal**, in the group's settings,
  and the gateway stops when it is removed;
- **authors are told**: before your first post in a group with a portal,
  your client says that it will also be published elsewhere;
- **only open groups** can have portals - never closed groups, inboxes or
  private posts.

## What never crosses a door

Some things stay inside whatever door is open:

- **Nothing encrypted** - no closed group, inbox or private post - is ever
  exported or published elsewhere.
- **No timing signals.** Other networks may show when someone is typing,
  has read a message or is online. A gateway never sends such signals for
  Unseenet authors, because they would reveal when someone is active and
  undo the random delays that hide where posts come from.
- **No origins.** A gateway receives posts from the network like any
  node: it does not learn where a post was written or who holds a key.
- **Withdrawals stay home.** A post withdrawn in Unseenet is withdrawn
  here; whether the other network forgets it is up to that network.

!!! warning "Where it stands"
    Entrances run, and the project runs one. Gateways run in the lab and
    against the project's own Matrix room; export to Usenet is not built
    yet, and nothing is connected to real Usenet peers. None of it has had
    a security review.

**Details:**
[UN-RFC 0023](../spec/un-rfc-0023.md) (gateways and portals),
[0024](../spec/un-rfc-0024.md) (Usenet),
[0026](../spec/un-rfc-0026.md) (Nostr),
[0037](../spec/un-rfc-0037.md) (Matrix),
[0038](../spec/un-rfc-0038.md) (several gateways, the directory),
[0043](../spec/un-rfc-0043.md) (web entrances).
For using and running them: [In your browser](../web.md),
[Running an entrance](../entrance/index.md) and
[Gateways to other networks](../gateways.md).
