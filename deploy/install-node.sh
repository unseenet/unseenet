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
.venv/bin/pip install -q -e ".[monitor]"
mkdir -p ~/node-data && chmod 700 ~/node-data
USER

# Pictures and small files (UN-RFC 0027), profile pictures (UN-RFC 0022) and sites
# (UN-RFC 0035). Off unless the operator says yes: a node that carries them keeps what
# strangers publish. Asked on the terminal; UNSEENET_BLOBS, UNSEENET_AVATARS and
# UNSEENET_SITES (yes|no) answer beforehand.
ask() {   # ask "question" -> 0 for yes; the recommended answer is yes
  local answer
  if [ ! -r /dev/tty ]; then return 1; fi
  read -r -p "$1 [Y/n] " answer </dev/tty || return 1
  case "$answer" in [nN]*) return 1 ;; *) return 0 ;; esac
}
yes_no() {   # yes_no VALUE "question"
  case "${1:-}" in
    [yY]*|1|true|accept) return 0 ;;
    [nN]*|0|false|refuse) return 1 ;;
    *) ask "$2" ;;
  esac
}
if [ ! -f /home/unseenet/node.toml ]; then
  echo
  echo "Pictures and small files: posts can carry screenshots, photos and small PDFs."
  echo "A node that carries them stores files strangers post, for 30 days at most."
  echo "Without them, people using this node see posts without their pictures."
  if yes_no "${UNSEENET_BLOBS:-}" "Carry pictures and small files (up to 1 MiB, 30 days, not encrypted ones)?"; then
    BLOBS_TOML='
# UN-RFC 0027: pictures and small files. "enabled = false" to stop carrying them.
[blobs]
enabled = true
max_size = 1048576
retention_days = 30
encrypted = false'
  else
    BLOBS_TOML='
# UN-RFC 0027: pictures and small files are not carried. To carry them:
# [blobs]
# enabled = true
# max_size = 1048576
# retention_days = 30
# encrypted = false'
  fi
  echo
  echo "Profile pictures: small pictures (at most 8 KB) people choose for themselves."
  if yes_no "${UNSEENET_AVATARS:-}" "Carry profile pictures?"; then AVATARS=accept; else AVATARS=refuse; fi
  # a group's emoji (UN-RFC 0056): small pictures too - as profile pictures unless UNSEENET_EMOJI says
  case "${UNSEENET_EMOJI:-$AVATARS}" in [yY]*|1|true|accept) EMOJI=accept ;; *) EMOJI=refuse ;; esac
  echo
  echo "Sites: small sets of pages (a person's homepage, a project's guide, a wiki)"
  echo "that stay until their owner changes them, at most 100 pages each."
  if yes_no "${UNSEENET_SITES:-}" "Carry sites?"; then SITES=accept; else SITES=refuse; fi
  cat > /home/unseenet/node.toml <<TOML
[node]
name = "$NODE_NAME"
min_pow = 18
retention_days = 90
new_groups = "accept"
avatars = "$AVATARS"
emoji = "$EMOJI"
sites = "$SITES"
$BLOBS_TOML

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
# "unseenet-monitor" for the operator: runs the monitor as the node's user
cat > /usr/local/bin/unseenet-monitor <<'MON'
#!/bin/sh
BIN=/home/unseenet/unseenet/.venv/bin/unseenet-monitor
SOCK=/home/unseenet/node-data/monitor.sock
if [ "$(id -un)" = unseenet ]; then
  exec "$BIN" --node "$SOCK" "$@"
fi
exec sudo -u unseenet "$BIN" --node "$SOCK" "$@"
MON
chmod 755 /usr/local/bin/unseenet-monitor
# Self-updating (UN-RFC 0062 section 6.1): on unless UNSEENET_SELF_UPDATE=no. The timer
# runs either way; turned off, it only tells you when a release has been out 30 days.
install -m 644 /home/unseenet/unseenet/deploy/unseenet-update@.service \
               /home/unseenet/unseenet/deploy/unseenet-update@.timer /etc/systemd/system/
mkdir -p /etc/unseenet-update
echo 'CHECK="--check tcp:127.0.0.1:1119"' > /etc/unseenet-update/unseenet-node.env
UPDATER=/home/unseenet/unseenet/.venv/bin/unseenet-service-update
case "${UNSEENET_SELF_UPDATE:-yes}" in
  [nN]*|0|false|off) "$UPDATER" off --service unseenet-node >/dev/null ;;
  *) "$UPDATER" on --service unseenet-node >/dev/null ;;
esac
systemctl daemon-reload
systemctl enable --now unseenet-node >/dev/null
systemctl enable --now unseenet-update@unseenet-node.timer >/dev/null
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
echo "Watch it with:  unseenet-monitor"
