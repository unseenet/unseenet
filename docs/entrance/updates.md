# New versions, the mirror, and blocking

## Two kinds of new version

**The web client** is the same build on every entrance, made by the
project's CI from released versions of unseenet and the graphical client, and
posted in the project channel `unseenet.releases` with the SHA-256 of every
file (UN-RFC 0043 sections 7.2-7.3). The entrance updates the client it
serves by itself - from the release on GitHub, or file by file from other
entrances - and uses a version only when every file matches the signed post.
No restart. `ENTRANCE_AUTO_UPDATE=off` stops it.

Visitors' apps update the same way, but only when they say so (*New version*
in the bar), and never go back to an older version.

**The entrance's own code** is never updated by itself. Run the install
command again to update it; it installs the newest release of
[unseenet-entrance](https://github.com/unseenet/unseenet-entrance/releases),
and its [changelog](https://github.com/unseenet/unseenet-entrance/blob/main/CHANGELOG.md)
says what changed.

Neither needs GitHub to stay reachable: the posts are read through the
network, and the files can come from any entrance.

## A mirror of the releases

An entrance can also mirror Unseenet's own releases, so that the portable
clients and sticks can update over Tor when GitHub is blocked:
`MIRROR=portable` (the portable zips and the USB zip, about 300 MB per
channel) or `MIRROR=all` (also a stick's update and image, about 1.1 GB).

It follows `unseenet.releases`, fetches each new version from GitHub or
another mirror, checks every file against the signed checksums, keeps only
the newest, and serves it at `/mirror/<channel>/` on its onion address and
its open address. Clients find it in the signed list of entrances and use
nothing that does not match the signature, so a mirror needs no trust.
`MIRROR=off` removes it.

## When an entrance is blocked

Every entrance serves the **jump page**, `/unseenet-entrances.html`: one
small file with the signed list of entrances inside. Opened from disk it
checks the list against the project key, shows which entrances answer, opens
a random one that does, and can fetch a newer list and save itself again.
Visitors get it from *Other entrances* in the bar; ask them to keep it and
pass it on.

An installed app does the same by itself: when its entrance does not answer,
it talks through another one from the list (UN-RFC 0043 section 8).

**The client in a file.** `python3 tools/build_web.py --file-from
https://an.entrance/` in the entrance's repository builds `unseenet-web.html`:
the whole web client and the signed list in one file of about 19 MB. Opened
from disk it picks an entrance that answers and uses it only as a tunnel; no
page is served, so a blocked address or a changed page does not matter.
