# An Unseenet node in a container: unseenet-node, unseenet-monitor and Tor.
#
#   docker run -d --name unseenet-node -v unseenet:/data \
#       -e UNSEENET_NODE_PASSPHRASE=... ghcr.io/unseenet/node
#   docker exec -it unseenet-node unseenet-monitor
#
# No port to publish: the node is reached over Tor only. See docs/node/docker.md.
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

FROM docker.io/library/alpine:3.24
RUN apk add --no-cache python3 tor su-exec tini gmp libgmpxx libstdc++ \
 && addgroup -S -g 10001 unseenet \
 && adduser -S -D -H -u 10001 -G unseenet -h /data unseenet \
 && mkdir -p /data && chown unseenet:unseenet /data && chmod 700 /data
COPY --from=build /opt/unseenet /opt/unseenet
COPY docker/entrypoint.sh /usr/local/bin/unseenet-entrypoint
COPY docker/unseenet-monitor /usr/local/bin/unseenet-monitor
RUN chmod 755 /usr/local/bin/unseenet-entrypoint /usr/local/bin/unseenet-monitor
ENV PATH=/opt/unseenet/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    UNSEENET_DATA=/data \
    UNSEENET_MONITOR=/data/monitor.sock
VOLUME /data
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
