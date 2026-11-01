#!/usr/bin/env bash
# Install a registrar replica (no node) on Debian/Ubuntu, e.g. a small VM.
#
#   curl -fsSL https://raw.githubusercontent.com/unseenet/unseenet/main/deploy/install-registrar.sh | sudo bash
#
# Creates the user "unseenet", installs Tor, dig and Unseenet, and installs
# the systemd unit without starting it: the vault comes next
# (docs/project/registrar.md). Adds 1 GB of swap if there is none, so pip
# also works on a machine with 1 GB of memory.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
if [ "$(id -u)" -ne 0 ]; then echo "Run as root (sudo)." >&2; exit 1; fi
if [ ! -f /swapfile ] && [ -z "$(swapon --show --noheadings)" ]; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap -q /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
apt-get update -qq
apt-get install -y -qq tor dnsutils git python3-venv python3-pip >/dev/null
# The registrar runs its own private Tor; the system service is not needed.
systemctl disable --now tor >/dev/null 2>&1 || true
id unseenet >/dev/null 2>&1 || useradd -m -s /bin/bash unseenet
chmod 700 /home/unseenet
sudo -u unseenet bash <<'USER'
set -e
cd ~
[ -d unseenet ] || git clone -q https://github.com/unseenet/unseenet unseenet
cd unseenet && git pull -q
python3 -m venv .venv
.venv/bin/pip install -q -e .
USER
install -m 644 /home/unseenet/unseenet/deploy/unseenet-registrar.service /etc/systemd/system/
# Self-updating (UN-RFC 0062 section 6.1): on unless UNSEENET_SELF_UPDATE=no
install -m 644 /home/unseenet/unseenet/deploy/unseenet-update@.service \
               /home/unseenet/unseenet/deploy/unseenet-update@.timer /etc/systemd/system/
UPDATER=/home/unseenet/unseenet/.venv/bin/unseenet-service-update
case "${UNSEENET_SELF_UPDATE:-yes}" in
  [nN]*|0|false|off) "$UPDATER" off --service unseenet-registrar >/dev/null ;;
  *) "$UPDATER" on --service unseenet-registrar >/dev/null ;;
esac
systemctl daemon-reload
systemctl enable --now unseenet-update@unseenet-registrar.timer >/dev/null
echo "Installed Unseenet $(sudo -u unseenet git -C /home/unseenet/unseenet log -1 --format=%h)."
echo "Next: make or move the vault, then: systemctl enable --now unseenet-registrar"
