#!/bin/sh
# Boot the image in QEMU and run its self-test on the serial console.
#
#   tools/image/boot-test.sh IMAGE [bios|uefi]
#
# A copy of the image boots the "Self-test" entry by itself; the test prints
# UNSEENET-SELFTEST-OK or -FAILED and shuts the machine down.
set -eu
IMG=${1:?image}
MODE=${2:-bios}
OUT=${OUT:-$(dirname "$IMG")}
TEST="$OUT/boot-test-$MODE.img"
LOG="$OUT/boot-test-$MODE.log"
export MTOOLS_SKIP_CHECK=1

cp --sparse=always "$IMG" "$TEST"
part="$TEST@@1M"
# make the self-test entry the default of both boot loaders, without waiting
mtype -i "$part" ::/boot/syslinux/syslinux.cfg \
    | sed -e 's/^DEFAULT .*/DEFAULT selftest/' -e 's/^TIMEOUT .*/TIMEOUT 1/' > "$OUT/syslinux.cfg"
mcopy -o -i "$part" "$OUT/syslinux.cfg" ::/boot/syslinux/syslinux.cfg
mtype -i "$part" ::/boot/grub/grub.cfg \
    | sed -e 's/^set default=.*/set default=2/' -e 's/^set timeout=.*/set timeout=1/' > "$OUT/grub.cfg"
mcopy -o -i "$part" "$OUT/grub.cfg" ::/boot/grub/grub.cfg
rm -f "$OUT/syslinux.cfg" "$OUT/grub.cfg"

FIRMWARE=""
if [ "$MODE" = uefi ]; then
    for f in /usr/share/OVMF/OVMF_CODE.fd /usr/share/edk2/ovmf/OVMF_CODE.fd \
             /usr/share/ovmf/OVMF.fd /usr/share/qemu/OVMF.fd; do
        [ -f "$f" ] && FIRMWARE="-bios $f" && break
    done
    [ -n "$FIRMWARE" ] || { echo "no OVMF firmware found" >&2; exit 2; }
fi
KVM=""
[ -w /dev/kvm ] && KVM="-enable-kvm -cpu host"

timeout "${TIMEOUT:-600}" qemu-system-x86_64 $KVM $FIRMWARE -m 2048 -smp 2 \
    -drive file="$TEST",format=raw,if=none,id=stick -device qemu-xhci \
    -device usb-storage,drive=stick,removable=on \
    -netdev user,id=net -device virtio-net-pci,netdev=net \
    -display none -serial file:"$LOG" -no-reboot || true
rm -f "$TEST"
tr -d '\r' < "$LOG" | sed -n '/UNSEENET-SELFTEST-BEGIN/,$p'
grep -q "UNSEENET-SELFTEST-OK" "$LOG"
