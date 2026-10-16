#!/usr/bin/env bash
# Install an Unseenet node on Debian/Ubuntu (e.g. a Proxmox LXC or a Raspberry Pi).
#
#   curl -fsSL https://raw.githubusercontent.com/unseenet/unseenet/main/deploy/install-node.sh | sudo bash
#
# Creates the user "unseenet", installs Tor and the node, and starts a systemd
# service. The node prints its .onion address in the journal:
#   journalctl -u unseenet-node | grep onion
set -euo pipefail

REPO="${UNSEENET_REPO:-https://github.com/unseenet/unseenet}"
NODE_NAME="${UNSEENET_NODE_NAME:-$(hostname)}"

if [ "$(id -u)" -ne 0 ]; then echo "Run as root (sudo)." >&2; exit 1; fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq tor git python3-venv python3-pip >/dev/null
# The node runs its own private Tor process; the system service is not needed.
systemctl disable --now tor >/dev/null 2>&1 || true

id unseenet >/dev/null 2>&1 || useradd -m -s /bin/bash unseenet
sudo -u unseenet bash -s "$REPO" <<'USER'
set -e
cd ~
[ -d unseenet ] || git clone -q "$1" unseenet
cd unseenet && git pull -q
python3 -m venv .venv
.venv/bin/pip install -q -e .
mkdir -p ~/node-data && chmod 700 ~/node-data
USER

if [ ! -f /home/unseenet/node.toml ]; then
  cat > /home/unseenet/node.toml <<TOML
[node]
name = "$NODE_NAME"
min_pow = 18
retention_days = 90
new_groups = "accept"

# Add peers like this, then: systemctl restart unseenet-node
# Swap onion addresses and node keys ("Node key:" in the journal) with the friend.
# [[peer]]
# name = "friend-node"
# address = "abcdef...xyz.onion:119"
# key = "ed25519:..."
TOML
  chown unseenet: /home/unseenet/node.toml
fi

if [ ! -f /etc/unseenet-node.env ]; then
  PASS="$(head -c 18 /dev/urandom | base64)"
  printf 'UNSEENET_NODE_PASSPHRASE=%s\nPYTHONUNBUFFERED=1\n' "$PASS" > /etc/unseenet-node.env
  chmod 600 /etc/unseenet-node.env
  echo "Generated a passphrase for the node's onion key in /etc/unseenet-node.env"
fi

install -m 644 /home/unseenet/unseenet/deploy/unseenet-node.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now unseenet-node >/dev/null
echo "Started. Waiting for the onion address (Tor bootstrap can take a minute) ..."
for _ in $(seq 1 90); do
  ADDR=$(journalctl -u unseenet-node -o cat --no-pager | grep -o '[a-z2-7]\{56\}\.onion' | tail -1 || true)
  [ -n "$ADDR" ] && break
  sleep 2
done
echo "Node address: ${ADDR:-not ready yet - check: journalctl -u unseenet-node -f}"
KEY=$(journalctl -u unseenet-node -o cat --no-pager | grep -o 'Node key: ed25519:[a-z2-7]*' | tail -1 | cut -d' ' -f3 || true)
echo "Node key:     ${KEY:-see: journalctl -u unseenet-node | grep 'Node key'}"
echo "Give both to the operators you peer with."
