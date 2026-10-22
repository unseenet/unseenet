# Settings

## When installing

Given on the install command, for example
`sudo TLS=domain:entrance.example.org sh install.sh`:

| Setting | |
|---|---|
| `TLS=auto` (default) | A certificate for the public IP address; plain HTTP on port 8043 if that fails, with the reason |
| `TLS=domain:NAME` | A normal certificate for NAME (point it here first) |
| `TLS=both:NAME` | One certificate for NAME and the public IP address. NAME is the one to share; it sends visitors on to the address, so the app and a vault kept on the device live at one place, which still works when the name is blocked |
| `TLS=none` | Plain HTTP on port 8043: a LAN test, or your own proxy in front |
| `MIRROR=portable` or `all` | Also mirror Unseenet's releases - see [the release mirror](updates.md#a-mirror-of-the-releases) |
| `BUILD=local` | Build the web client here instead of installing the signed one (it then says it is not signed) |
| `JOURNAL=keep` | Leave the system journal as it is, on a machine that does other things too |
| `REF=vX.Y.Z` or `REF=main` | The entrance's code to install (default: the newest release) |

A Tor that is already running is reloaded, not restarted, so its other users
keep their circuits.

## Afterwards

In `/etc/unseenet-entrance.env`, then `sudo systemctl restart unseenet-entrance`:

| Setting | |
|---|---|
| `ENTRANCE_OPERATOR`, `ENTRANCE_CONTACT` | Who runs it, shown in `/.well-known/unseenet-entrance` |
| `ENTRANCE_AUTO_UPDATE=off` | Stop the web client from updating itself |
| `ENTRANCE_NODES=any` | Tunnel to any onion node, not only the known ones |
| `ENTRANCE_MAX_PER_VISITOR` | Open tunnels per visitor (6) |
| `ENTRANCE_MAX_TOTAL` | Open tunnels in all. `auto` (the default) allows what the available memory and the open-file limit carry, about 120 KB and two open files per tunnel, and prints the number at start; a number overrides it |
| `ENTRANCE_TRUST_FORWARDED=1` | A reverse proxy on this machine sits in front: count limits per visitor, not per proxy |
| `ENTRANCE_HOME` | A name that sends visitors on to the entrance's own address |

A visitor uses two tunnels per node (one for requests, one for watching), so
`ENTRANCE_MAX_TOTAL` is about twice the number of people at once. The unit
`install.sh` writes allows 65536 open files; with the system's default of
1024 the entrance would stop at about 500 tunnels. When it is full, it
answers new visitors with *429*, and their client tries another entrance.

Never put an entrance behind a CDN or a tunnel that ends TLS on someone
else's machine: they would see every visitor's address and everything they
read (UN-RFC 0043 section 5). See [Certificates](certificates.md).
