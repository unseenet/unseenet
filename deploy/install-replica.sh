#!/usr/bin/env bash
# Install a replica of a council registrar (UN-RFC 0054) on Debian, Ubuntu or
# Raspberry Pi OS (64-bit) - a small VPS or a Raspberry Pi is enough.
#
#   curl -fsSL https://raw.githubusercontent.com/unseenet/unseenet/main/deploy/install-replica.sh | sudo bash
#
# Installs Tor and Unseenet in /opt/unseenet-replica (a virtualenv of its own), then
# runs "unseenet-replica setup", which makes the replica's key and vault, installs the
# service and a daily update, and starts it. Then: unseenet-replica status
#
# Choices, as environment variables before "sudo bash" (sudo -E keeps them):
#   UNSEENET_CHANNEL=stable|main   where the software and its updates come from
#                                  (default stable: releases on PyPI)
#   UNSEENET_GROUP=<group id>      the council registrar (default: the project's)
#   UNSEENET_HOLD=removal,...      changes you want to agree to first (default none)
# Adds 1 GB of swap if there is none, so pip works with 1 GB of memory.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
if [ "$(id -u)" -ne 0 ]; then echo "Run as root (sudo)." >&2; exit 1; fi
case "$(uname -m)" in
  x86_64|aarch64) ;;
  *) echo "This needs a 64-bit system (x86_64 or arm64); key ripening has no build for $(uname -m)." >&2
     echo "On a Raspberry Pi, use the 64-bit Raspberry Pi OS." >&2; exit 1 ;;
esac
CHANNEL="${UNSEENET_CHANNEL:-stable}"
case "$CHANNEL" in
  stable) SOURCE="unseenet" ;;
  main) SOURCE="git+https://github.com/unseenet/unseenet@main" ;;
  *) echo "UNSEENET_CHANNEL is stable or main" >&2; exit 1 ;;
esac
if [ ! -f /swapfile ] && [ -z "$(swapon --show --noheadings)" ]; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap -q /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
apt-get update -qq
apt-get install -y -qq tor dnsutils git python3-venv python3-pip >/dev/null
# The replica runs its own private Tor; the system service is not needed.
systemctl disable --now tor >/dev/null 2>&1 || true
python3 -m venv /opt/unseenet-replica
/opt/unseenet-replica/bin/pip install -q --upgrade pip
/opt/unseenet-replica/bin/pip install -q "$SOURCE"
ln -sf /opt/unseenet-replica/bin/unseenet-replica /usr/local/bin/unseenet-replica
echo "Installed $(/opt/unseenet-replica/bin/python -c 'import unseenet; print("Unseenet", unseenet.__version__)')."
ARGS=(--channel "$CHANNEL")
[ -n "${UNSEENET_GROUP:-}" ] && ARGS+=(--group "$UNSEENET_GROUP")
[ -n "${UNSEENET_HOLD:-}" ] && ARGS+=(--hold "$UNSEENET_HOLD")
exec /opt/unseenet-replica/bin/unseenet-replica setup "${ARGS[@]}"
