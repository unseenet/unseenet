# Docker

The node is also a container image, `ghcr.io/unseenet/node`, for amd64 and
arm64: `unseenet-node`, [`unseenet-monitor`](monitor.md) and Tor on Alpine
Linux. It runs anywhere Docker or Podman runs - a NAS, a small server, a
Raspberry Pi.

It needs **no published port**: the node is reached over Tor only, through
the onion service it creates itself.

## Start it

With Docker Compose - save
[`docker-compose.yml`](https://github.com/unseenet/unseenet/blob/main/deploy/docker-compose.yml)
and give the node a passphrase in a file next to it:

```bash
echo 'a long passphrase only you know' > unseenet_node_passphrase.txt
chmod 600 unseenet_node_passphrase.txt
docker compose up -d
docker compose logs node
```

The log shows the **node key** and the **onion address** - give both to the
operators you [peer with](peering.md).

Or with `docker run`:

```bash
docker run -d --name unseenet-node --restart unless-stopped \
  -v unseenet:/data -e UNSEENET_NODE_PASSPHRASE='a long passphrase' \
  ghcr.io/unseenet/node:latest
```

!!! warning "The passphrase"
    It seals the node key and the onion key in `/data`. Lose it and the node
    gets a new identity - a new onion address and node key your peers do not
    know. A Docker secret (as in the compose file) keeps it out of
    `docker inspect`; `UNSEENET_NODE_PASSPHRASE` is simpler but visible there.

## Watch it

```bash
docker exec -it unseenet-node unseenet-monitor
```

The image's health check reads the same stats: `docker ps` shows the node as
*healthy* when it answers and Tor runs.

## Configure it

The first start writes `/data/node.toml` from these variables; after that,
edit the file in the volume and restart the container:

| Variable | Default | |
|---|---|---|
| `UNSEENET_NODE_NAME` | `unseenet-docker` | How the node introduces itself |
| `UNSEENET_MIN_POW` | `18` | Minimum postage, bits |
| `UNSEENET_RETENTION_DAYS` | `90` | How long articles are kept |
| `UNSEENET_NEW_GROUPS` | `accept` | `accept`, `trusted` or `manual` |
| `UNSEENET_BLOBS` | `no` | `yes`: carry pictures and small files, 1 MiB, 30 days ([why it is a choice](install.md#pictures-and-files)) |
| `UNSEENET_AVATARS` | `no` | `yes`: carry profile pictures |
| `UNSEENET_SITES` | `no` | `yes`: carry sites, pages that stay ([UN-RFC 0035](../spec/un-rfc-0035.md)) |
| `UNSEENET_LISTEN` | `127.0.0.1:1119` | Read at every start. `0.0.0.0:1119` lets other containers on the same Docker network use the node, such as a [replica](../replica.md#in-docker) beside it. Publish no port |

```bash
docker run --rm -it -v unseenet:/data alpine vi /data/node.toml   # add [[peer]] sections
docker restart unseenet-node
```

The options of [Configuration](configuration.md) all apply. The node's own
commands work too, e.g. to prove you run it when you
[ask to be listed](operations.md):

```bash
docker run --rm -v unseenet:/data -e UNSEENET_NODE_PASSPHRASE=... \
  ghcr.io/unseenet/node --sign "unseenet-node-claim ..."
```

## The image

- `latest` and `<version>` (e.g. `0.3.0`) from releases; `dev` follows `main`
  - newest fixes, less tested.
- The node runs as the user `unseenet` (uid 10001), never as root; the
  start script only hands `/data` to that user and drops root. It works with
  a read-only root file system and almost no capabilities (see the compose
  file).
- `/data` holds everything: the sealed keys, the articles, Tor's state,
  `node.toml`. Back it up like any volume.
- Every image is built by GitHub Actions from this repository, with
  provenance and an SBOM, and signed with cosign (keyless):

    ```bash
    cosign verify ghcr.io/unseenet/node:latest \
      --certificate-identity-regexp 'https://github.com/unseenet/unseenet/' \
      --certificate-oidc-issuer https://token.actions.githubusercontent.com
    ```

## The other servers in Docker

Every Unseenet server has an image, built and signed the same way:

| Image | Server | Guide |
|---|---|---|
| `ghcr.io/unseenet/node` | A node | this page |
| `ghcr.io/unseenet/replica` | A council replica, alone or beside a node | [Running a replica](../replica.md#in-docker) |
| `ghcr.io/unseenet/entrance` | A web entrance | [Entrance](https://unseenet.org/entrance/#in-docker) |
| `ghcr.io/unseenet/gateway` | A gateway to Usenet, Matrix or Nostr | [Gateways](https://unseenet.org/gateways/#in-docker) |

None updates itself inside its container: `docker compose pull && docker
compose up -d` gets the newest release.
