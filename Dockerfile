# Unseenet's servers in containers, from one build (docs/docker.md):
#
#   node (the default target): unseenet-node, unseenet-monitor and Tor - ghcr.io/unseenet/node
#       docker run -d --name unseenet-node -v unseenet:/data \
#           -e UNSEENET_NODE_PASSPHRASE=... ghcr.io/unseenet/node
#       docker exec -it unseenet-node unseenet-monitor
#   replica (--target replica): a council replica, unseenet-replica and Tor - ghcr.io/unseenet/replica
#       docker run -d --name unseenet-replica -v replica:/data \
#           -e UNSEENET_REPLICA_PASSPHRASE=... ghcr.io/unseenet/replica
#       docker exec unseenet-replica unseenet-replica status
#
# No port to publish: both reach the network over Tor. See docs/node/docker.md
# and docs/replica.md.
FROM docker.io/library/alpine:3.24 AS build
# chiavdf (key ripening, UN-RFC 0025) has no musl wheels: built here, without its
# timelord client (BUILD_VDF_CLIENT=N, no boost needed)
RUN apk add --no-cache python3 py3-pip python3-dev cmake make g++ gmp-dev git
ENV BUILD_VDF_CLIENT=N
COPY pyproject.toml README.md LICENSE NOTICE /src/
COPY src /src/src
RUN python3 -m venv /opt/unseenet \
 && /opt/unseenet/bin/pip install --no-cache-dir "/src[monitor]" \
 && find /opt/unseenet -name __pycache__ -type d -prune -exec rm -rf {} +

# What both servers run on: Python, Tor, and a user that is not root.
FROM docker.io/library/alpine:3.24 AS base
RUN apk add --no-cache python3 tor su-exec tini gmp libgmpxx libstdc++ \
 && addgroup -S -g 10001 unseenet \
 && adduser -S -D -H -u 10001 -G unseenet -h /data unseenet \
 && mkdir -p /data && chown unseenet:unseenet /data && chmod 700 /data
COPY --from=build /opt/unseenet /opt/unseenet
ENV PATH=/opt/unseenet/bin:$PATH \
    PYTHONUNBUFFERED=1
VOLUME /data

# A council replica (UN-RFC 0054). Its volume IS the replica: never start two
# containers on one volume or one key (docs/replica.md, "In Docker").
FROM base AS replica
COPY docker/replica-entrypoint.sh /usr/local/bin/unseenet-replica-entrypoint
COPY docker/unseenet-replica /usr/local/bin/unseenet-replica
RUN chmod 755 /usr/local/bin/unseenet-replica-entrypoint /usr/local/bin/unseenet-replica
# /usr/local/bin first: unseenet-replica, run by docker exec as root, drops to the replica's user
ENV PATH=/usr/local/bin:/opt/unseenet/bin:$PATH \
    UNSEENET_REPLICA_DIR=/data \
    UNSEENET_CONTAINER=1
HEALTHCHECK --interval=5m --timeout=15s --start-period=30m \
  CMD python3 -c "import os, time; \
raise SystemExit(0 if time.time() - os.stat('/data/status.json').st_mtime < 1800 else 1)"
LABEL org.opencontainers.image.title="Unseenet council replica" \
      org.opencontainers.image.description="A replica of an Unseenet council registrar: decides name claims by public rules (UN-RFC 0054)" \
      org.opencontainers.image.source="https://github.com/unseenet/unseenet" \
      org.opencontainers.image.url="https://unseenet.org/replica/" \
      org.opencontainers.image.licenses="Apache-2.0"
ENTRYPOINT ["/sbin/tini", "--", "unseenet-replica-entrypoint"]

# A node - the last stage, so that a plain "docker build ." still makes it.
FROM base AS node
COPY docker/entrypoint.sh /usr/local/bin/unseenet-entrypoint
COPY docker/unseenet-monitor /usr/local/bin/unseenet-monitor
RUN chmod 755 /usr/local/bin/unseenet-entrypoint /usr/local/bin/unseenet-monitor
ENV UNSEENET_DATA=/data \
    UNSEENET_MONITOR=/data/monitor.sock
HEALTHCHECK --interval=60s --timeout=15s --start-period=180s \
  CMD python3 -c "import asyncio, os; from unseenet.node.stats import fetch; \
s = asyncio.run(fetch(os.environ['UNSEENET_MONITOR'])); \
raise SystemExit(0 if s['tor']['state'] in ('running', 'off') else 1)"
LABEL org.opencontainers.image.title="Unseenet node" \
      org.opencontainers.image.description="A node of Unseenet, a decentralized, encrypted discussion network over Tor" \
      org.opencontainers.image.source="https://github.com/unseenet/unseenet" \
      org.opencontainers.image.url="https://unseenet.org/node/docker/" \
      org.opencontainers.image.licenses="Apache-2.0"
ENTRYPOINT ["/sbin/tini", "--", "unseenet-entrypoint"]
