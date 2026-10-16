#!/bin/sh
# Boot the image in QEMU and take screenshots of the console (for the docs).
#
#   tools/image/screenshot.sh IMAGE OUT_PREFIX [SECONDS] [KEYS...]
#
# KEYS are QEMU sendkey names sent after SECONDS, one screenshot after each.
set -eu
IMG=${1:?image}
PREFIX=${2:?out prefix}
WAIT=${3:-45}
shift 3 || shift $#
TMP=$(mktemp -d)
cp --sparse=always "$IMG" "$TMP/disk.img"
KVM=""
[ -w /dev/kvm ] && KVM="-enable-kvm -cpu host"
qemu-system-x86_64 $KVM -m 2048 -smp 2 \
    -drive file="$TMP/disk.img",format=raw,if=none,id=stick -device qemu-xhci \
    -device usb-storage,drive=stick,removable=on \
    -netdev user,id=net -device virtio-net-pci,netdev=net \
    -display none -vga std -monitor unix:"$TMP/mon",server,nowait &
QEMU=$!
mon() { printf '%s\n' "$1" | socat - UNIX-CONNECT:"$TMP/mon" >/dev/null 2>&1 || true; }
sleep "$WAIT"
mon "screendump $PREFIX-0.ppm"
n=1
for key in "$@"; do
    mon "sendkey $key"
    sleep 2
    mon "screendump $PREFIX-$n.ppm"
    n=$((n + 1))
done
mon quit
wait $QEMU 2>/dev/null || true
rm -rf "$TMP"
