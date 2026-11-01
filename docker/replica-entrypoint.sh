#!/bin/sh
# Start a council replica in the container (see docs/replica.md, "In Docker").
#
#   (no arguments)   make the replica's key on the first start, then run it
#   anything else    run that command, e.g. "unseenet-replica status" or sh
#
# The volume /data IS the replica: its vault, key, settings and state. Never start
# two containers on one volume, or on copies of it: two replicas with one key can
# split the council, and the replica stops signing when it sees that (UN-RFC 0054
# section 7).
set -eu
DATA=${UNSEENET_REPLICA_DIR:-/data}

# Started as root (the default): make /data ours, then drop root for good.
if [ "$(id -u)" = 0 ]; then
    if [ "$(stat -c %u "$DATA")" != 10001 ]; then
        chown -R unseenet:unseenet "$DATA"
    fi
    chmod 700 "$DATA"
    # A secret file is mounted as it is on the host (often root's, mode 600), so the
    # replica's user may not read it: hand a copy on in /tmp (a tmpfs), readable by it only.
    for f in "${UNSEENET_REPLICA_PASSPHRASE_FILE:-}" /run/secrets/unseenet_replica_passphrase; do
        if [ -n "$f" ] && [ -r "$f" ]; then
            (umask 077 && cat "$f" > /tmp/unseenet_replica_passphrase)
            chown unseenet:unseenet /tmp/unseenet_replica_passphrase
            export UNSEENET_REPLICA_PASSPHRASE_FILE=/tmp/unseenet_replica_passphrase
            break
        fi
    done
    exec su-exec unseenet "$0" "$@"
fi

if [ -n "${1:-}" ]; then
    exec "$@"
fi

# The passphrase seals the replica's key: a secret file, or the environment.
PW_FILE=""
for f in "${UNSEENET_REPLICA_PASSPHRASE_FILE:-}" /run/secrets/unseenet_replica_passphrase; do
    if [ -n "$f" ] && [ -r "$f" ]; then
        PW_FILE=$f
        break
    fi
done
if [ -z "$PW_FILE" ]; then
    if [ -z "${UNSEENET_REPLICA_PASSPHRASE:-}" ]; then
        echo "unseenet-replica: no passphrase. Give it as a Docker secret (unseenet_replica_passphrase)," >&2
        echo "  as UNSEENET_REPLICA_PASSPHRASE_FILE, or as UNSEENET_REPLICA_PASSPHRASE." >&2
        exit 64
    fi
    PW_FILE=/tmp/replica-passphrase           # tmpfs: never in the volume
    (umask 077 && printf '%s\n' "$UNSEENET_REPLICA_PASSPHRASE" > "$PW_FILE")
    unset UNSEENET_REPLICA_PASSPHRASE
fi

# The first start makes the key and the vault, and writes config.json from these
# variables; after that, change it with unseenet-replica (hold, agree, ...) or in the volume.
if [ ! -f "$DATA/replica.vault" ]; then
    set -- --no-systemd --passphrase-file "$PW_FILE" --channel off
    [ -n "${UNSEENET_REPLICA_GROUP:-}" ] && set -- "$@" --group "$UNSEENET_REPLICA_GROUP"
    [ -n "${UNSEENET_REPLICA_HOLD:-}" ] && set -- "$@" --hold "$UNSEENET_REPLICA_HOLD"
    for node in $(echo "${UNSEENET_REPLICA_NODES:-}" | tr ',' ' '); do
        set -- "$@" --node "$node"
    done
    unseenet-replica setup "$@"
    set --
fi

exec unseenet-replica run --passphrase-file "$PW_FILE"
