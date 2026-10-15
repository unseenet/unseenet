# Installing a node

A node is small: 512 MB of RAM, one CPU core and a few GB of disk are
plenty. A Raspberry Pi, an old laptop, a VPS or a container in a homelab
all work. It does **not** need a public IP address or any open ports -
it is reached as a Tor onion service.

## Quick install (Debian / Ubuntu)

As root on the machine that will be the node:

```bash
curl -fsSL https://raw.githubusercontent.com/andlo/unseenet/main/deploy/install-node.sh | sudo bash
```

!!! info "Read before you pipe"
    Piping a script into `bash` runs it as root. If you prefer, download it
    first and read it:
    `curl -fsSLO https://raw.githubusercontent.com/andlo/unseenet/main/deploy/install-node.sh`

The script:

1. installs `tor`, `git` and Python, and disables the system's Tor service
   (the node runs its own Tor process);
2. creates a user `unseenet` and installs Unseenet in
   `/home/unseenet/unseenet` (a git checkout with its own virtualenv);
3. writes a starter configuration to `/home/unseenet/node.toml`;
4. generates a random passphrase for the node's onion key in
   `/etc/unseenet-node.env`;
5. installs and starts the `unseenet-node` systemd service;
6. waits for Tor and prints the node's **onion address**.

```text
Node address: f6vnchi5p7ll4yn6yot6cz4ohzuxy3uhc3kztafuwn3zlyoup6tn64qd.onion
```

That address is what clients and peers connect to. It stays the same
as long as you keep the node's data directory (see
[Operations](operations.md#backup)).

## Proxmox LXC

The script works unchanged in an unprivileged Debian 12 or 13 container.
For example, on the Proxmox host:

```bash
pct create 160 local:vztmpl/debian-13-standard_13.1-2_amd64.tar.zst \
  --hostname unseenet-node1 --memory 512 --swap 512 --cores 1 \
  --rootfs local-lvm:4 --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 --features nesting=1 --start 1
pct exec 160 -- bash -c "apt-get update && apt-get install -y curl && \
  curl -fsSL https://raw.githubusercontent.com/andlo/unseenet/main/deploy/install-node.sh | bash"
```

## What is where

| Path | Contents |
|------|----------|
| `/home/unseenet/node.toml` | Configuration ([reference](configuration.md)) |
| `/home/unseenet/node-data/articles.sqlite` | Posts, history, groups, peer queues |
| `/home/unseenet/node-data/onion_key.vault` | The onion service key, encrypted |
| `/home/unseenet/node-data/tor/` | The node's private Tor data, including `tor.log` |
| `/etc/unseenet-node.env` | Passphrase for the onion key (root only) |
| `/etc/systemd/system/unseenet-node.service` | The service |

## Checking that it works

```bash
systemctl status unseenet-node
journalctl -u unseenet-node -f
```

A healthy start looks like:

```text
ONNTP listening on 127.0.0.1:1119
Starting Tor ...
Node is reachable at f6vnchi5....onion
```

Then connect to it with the [client](../client.md). A new node carries no
groups yet: create one, or [peer](peering.md) with a node that has some.

## Manual installation

On other systems, install Python 3.11+ and Tor, then:

```bash
git clone https://github.com/andlo/unseenet && cd unseenet
python3 -m venv .venv && .venv/bin/pip install -e .
UNSEENET_NODE_PASSPHRASE=choose-something .venv/bin/unseenet-node \
  --data ~/node-data --config ~/node.toml
```

Command line options:

| Option | Default | Meaning |
|--------|---------|---------|
| `--data DIR` | `node-data` | Data directory. Put it on an encrypted disk. |
| `--config FILE` | none | TOML configuration file |
| `--listen HOST:PORT` | `127.0.0.1:1119` | Local ONNTP address that Tor forwards to |
| `--tor PATH` | `tor` on `PATH` | The Tor binary (or set `UNSEENET_TOR`) |
| `--no-tor` | | Local only, for development |
| `-v` | | Debug logging |

The node asks for the onion key passphrase on start unless
`UNSEENET_NODE_PASSPHRASE` is set.
