# Running an entrance

A **web entrance** ([UN-RFC 0043](../spec/un-rfc-0043.md)) lets an ordinary
browser into Unseenet: anyone who opens its address gets the
[graphical client](../graphical.md), running in their own browser, with their
keys kept there. The entrance serves the client and carries its connections to
the nodes over Tor. It cannot read, change or forge anything: it only moves
bytes.

Every entrance that someone else runs makes Unseenet harder to block, so this
is one of the most useful things you can do for the network besides
[running a node](../node/install.md). The code is
[unseenet-entrance](https://github.com/unseenet/unseenet-entrance).

!!! warning "Pre-alpha"
    Neither the entrance nor the Unseenet core has had a security review.
    Read [Your responsibility](responsibility.md) before you open one to others.

## What an entrance does, and does not

- It tunnels a browser's WebSocket to a **known node's** onion service, each
  on a Tor circuit of its own, and copies bytes both ways, unchanged.
- It serves the web client, and the signed lists it reads from the network
  about once an hour: the entrances and the versions of the web client, as
  raw signed articles that clients check themselves.
- It writes nothing about visitors anywhere: no access log, no error that
  names an address. Limits are counted in memory, under a key made at start.
- It does **not** hold anyone's keys or vault, sign anything, or see what is
  in a closed group or a private post.

## Installation

On Debian 12/13 or Ubuntu 24.04+ - a free cloud VM is enough (1 GB of memory
carries a few thousand visitors) - with ports 80 and 443 open to the internet:

```sh
curl -fsSLO https://raw.githubusercontent.com/unseenet/unseenet-entrance/main/deploy/install.sh
sudo sh install.sh
```

That installs the newest release of the entrance and Tor, gives the entrance
an onion address, installs the newest signed version of the web client
through the network, gets a Let's Encrypt certificate for the machine's
**public IP address** (no domain needed; the 6-day certificates renew by
themselves), and runs it as its own user with the journal in memory only. At
the end it prints both addresses.

The choices you can give on the command line - HTTPS, a release mirror, the
journal - are in [Settings](settings.md); certificates in more detail in
[Certificates](certificates.md). Run the same command again to update the
entrance's own code (`REF=vX.Y.Z` installs another release); your settings
are kept.

## Being listed

Apps and the jump page find entrances in a signed list kept by the project
(`unseenet.entrances`, UN-RFC 0043 section 8.1). To have yours in it, open an
issue in [unseenet-entrance](https://github.com/unseenet/unseenet-entrance/issues)
with its addresses and who runs it. Set `ENTRANCE_OPERATOR` and
`ENTRANCE_CONTACT` first, so visitors can see that too.
