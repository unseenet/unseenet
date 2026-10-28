#!/bin/sh
# Start an Unseenet node in the container (see docs/node/docker.md).
#
#   (no arguments)        run the node
#   --show-key, --sign X, --drop-group G, ...   unseenet-node options, then exit
#   anything else         run that command (e.g. sh)
set -eu
DATA=${UNSEENET_DATA:-/data}
CONFIG=$DATA/node.toml

# Started as root (the default): make /data ours, then drop root for good.
if [ "$(id -u)" = 0 ]; then
    if [ "$(stat -c %u "$DATA")" != 10001 ]; then
        chown -R unseenet:unseenet "$DATA"
    fi
    chmod 700 "$DATA"
    exec su-exec unseenet "$0" "$@"
fi

case "${1:-}" in
    ""|--*) ;;
    *) exec "$@" ;;
esac

# The passphrase seals the node's keys: a secret file, or the environment.
if [ -z "${UNSEENET_NODE_PASSPHRASE:-}" ]; then
    for f in "${UNSEENET_NODE_PASSPHRASE_FILE:-}" /run/secrets/unseenet_node_passphrase; do
        if [ -n "$f" ] && [ -r "$f" ]; then
            UNSEENET_NODE_PASSPHRASE=$(cat "$f")
            break
        fi
    done
fi
if [ -z "${UNSEENET_NODE_PASSPHRASE:-}" ]; then
    echo "unseenet-node: no passphrase. Give it as a Docker secret (unseenet_node_passphrase)," >&2
    echo "  as UNSEENET_NODE_PASSPHRASE_FILE, or as UNSEENET_NODE_PASSPHRASE." >&2
    exit 64
fi
export UNSEENET_NODE_PASSPHRASE

# The first start writes node.toml from the environment; edit it in /data after.
if [ ! -f "$CONFIG" ]; then
    # pictures and small files (UN-RFC 0027), profile pictures (UN-RFC 0022): off unless
    # the operator says yes with UNSEENET_BLOBS=yes / UNSEENET_AVATARS=yes
    case "${UNSEENET_BLOBS:-no}" in [yY]*|1|true) BLOBS=true ;; *) BLOBS=false ;; esac
    case "${UNSEENET_AVATARS:-no}" in [yY]*|1|true|accept) AVATARS=accept ;; *) AVATARS=refuse ;; esac
    # a group's emoji (UN-RFC 0056) are pictures too: as profile pictures unless UNSEENET_EMOJI says
    case "${UNSEENET_EMOJI:-$AVATARS}" in [yY]*|1|true|accept) EMOJI=accept ;; *) EMOJI=refuse ;; esac
    case "${UNSEENET_SITES:-no}" in [yY]*|1|true|accept) SITES=accept ;; *) SITES=refuse ;; esac
    cat > "$CONFIG" <<EOF
# Unseenet node in Docker. See https://unseenet.org/node/configuration/
[node]
name = "${UNSEENET_NODE_NAME:-unseenet-docker}"
min_pow = ${UNSEENET_MIN_POW:-18}
retention_days = ${UNSEENET_RETENTION_DAYS:-90}
new_groups = "${UNSEENET_NEW_GROUPS:-accept}"
avatars = "$AVATARS"
emoji = "$EMOJI"
sites = "$SITES"

# Pictures and small files (UN-RFC 0027): files strangers post, kept 30 days at most
[blobs]
enabled = $BLOBS
max_size = 1048576
retention_days = 30
encrypted = false

# Peers: other nodes to exchange groups with.
# [[peer]]
# name = "friend"
# address = "....onion"
# key = "ed25519:..."
EOF
    echo "Wrote $CONFIG - edit it there (e.g. to add peers) and restart the container."
fi

if [ -n "${1:-}" ]; then              # an unseenet-node option such as --show-key
    exec unseenet-node --data "$DATA" --config "$CONFIG" "$@"
fi
NO_TOR=""
[ -n "${UNSEENET_NO_TOR:-}" ] && NO_TOR=--no-tor      # tests only: no onion service
exec unseenet-node --data "$DATA" --config "$CONFIG" --listen 127.0.0.1:1119 \
    --monitor "${UNSEENET_MONITOR:-$DATA/monitor.sock}" $NO_TOR
