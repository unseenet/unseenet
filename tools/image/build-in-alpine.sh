#!/bin/sh
# Builds the bootable Unseenet image. Runs as root in an Alpine container
# (tools/image/build.sh starts it); the repository is mounted at /src.
#
#   /src/tools/image/build-in-alpine.sh OUT_DIR VERSION [PORTABLE_USB_ZIP]
#
# The result is one FAT32 partition, label UNSEENET, that is both
#   - bootable (BIOS: syslinux, UEFI: GRUB): Alpine in "diskless" mode, from RAM,
#     starting the Unseenet boot menu (unseenet.boot) on the console, and
#   - a portable Unseenet folder (Start Unseenet.bat / .command / start-linux.sh)
#     for a computer that is already running,
# sharing one data/ folder with the vault. Nothing here needs loop devices.
set -eu

OUT=${1:?out dir}
VERSION=${2:?version}
PORTABLE=${3:-}
ARCH=x86_64
LABEL=UNSEENET
W=/work
TREE=$W/tree             # what goes on the FAT partition
OVL=$W/overlay           # the apkovl: /etc, /opt and /usr/local of the running system
HERE=/src/tools/image

log() { printf '[image] %s\n' "$*"; }

# Wi-Fi and wired network firmware for common hardware; everything else is
# left out to keep the image small (see docs/bootable.md).
FIRMWARE="linux-firmware-intel linux-firmware-ath9k_htc linux-firmware-ath10k
  linux-firmware-ath11k linux-firmware-ath12k linux-firmware-qca linux-firmware-mediatek
  linux-firmware-rtlwifi linux-firmware-rtw88 linux-firmware-rtw89 linux-firmware-realtek
  linux-firmware-rtl_nic linux-firmware-brcm linux-firmware-cypress linux-firmware-libertas
  linux-firmware-mrvl linux-firmware-ti-connectivity linux-firmware-bnx2 linux-firmware-tigon"

# What the running system has (installed at boot from the image's own repository).
PACKAGES="alpine-base busybox-openrc busybox-mdev-openrc openrc kbd-bkeymaps
  python3 tor iwd dbus dhcpcd util-linux-misc blkid dosfstools ncurses-terminfo-base"

log "tools"
apk add --no-cache -q --no-scripts abuild apk-tools mkinitfs squashfs-tools syslinux grub-efi grub \
    mtools dosfstools sfdisk python3 py3-pip linux-lts kmod xz zip unzip $FIRMWARE >/dev/null

rm -rf "$W" && mkdir -p "$TREE/boot" "$TREE/apks/$ARCH" "$OVL" "$OUT"
KVER=$(ls /lib/modules | head -1)
log "kernel $KVER, Alpine $(cat /etc/alpine-release)"

log "signing key for the image's package repository"
export ABUILD_USERDIR=$W/abuild
mkdir -p "$ABUILD_USERDIR"
abuild-keygen -a -n -q >/dev/null 2>&1 || abuild-keygen -a -n
KEY=$(ls "$ABUILD_USERDIR"/*.rsa | head -1)
cp "$KEY.pub" /etc/apk/keys/          # mkinitfs puts /etc/apk/keys into the initramfs

log "packages"
apk fetch -q --recursive --output "$TREE/apks/$ARCH" $PACKAGES >/dev/null
( cd "$TREE/apks/$ARCH" && apk index -q --rewrite-arch $ARCH -o APKINDEX.tar.gz ./*.apk \
    && abuild-sign -q -k "$KEY" APKINDEX.tar.gz )
touch "$TREE/apks/.boot_repository"   # Alpine's init finds the boot medium by this

log "trimming what a text-only Unseenet machine does not need"
# Firmware: switches, cameras, sensors, Bluetooth; and only the newest Intel
# Wi-Fi firmware per device (the kernel loads the newest it supports).
F=/lib/firmware
rm -rf $F/mrvl/prestera $F/intel/ipu $F/intel/vsc $F/intel/ish $F/intel/vpu $F/intel/qat \
       $F/intel/ibt-* $F/LENOVO $F/dell $F/qca
find $F -iname 'BT_RAM_CODE*' -delete
python3 - "$F/intel/iwlwifi" <<'PY'
import re, sys
from pathlib import Path
best = {}
for f in Path(sys.argv[1]).glob("iwlwifi-*.ucode*"):
    m = re.match(r"(iwlwifi-.+)-(\d+)\.ucode", f.name)
    if m:
        name, api = m.group(1), int(m.group(2))
        best.setdefault(name, []).append((api, f))
for files in best.values():
    files.sort()
    for _, f in files[:-1]:
        f.unlink()
PY
# Modules: sound, cameras and video, InfiniBand, and the big GPU drivers (the
# console works with the UEFI/VESA framebuffer; "safe graphics" is nomodeset).
M=/lib/modules/$KVER/kernel
rm -rf $M/sound $M/drivers/media $M/drivers/infiniband $M/drivers/iio $M/drivers/isdn \
       $M/drivers/gpu/drm/amd $M/drivers/gpu/drm/i915 $M/drivers/gpu/drm/xe \
       $M/drivers/gpu/drm/nouveau $M/drivers/gpu/drm/radeon $M/drivers/gpu/drm/gma500
depmod -a "$KVER"
log "firmware $(du -sh $F | cut -f1), modules $(du -sh /lib/modules/$KVER | cut -f1)"

log "kernel, modules and firmware (modloop)"
cp /boot/vmlinuz-lts "$TREE/boot/vmlinuz-lts"
mkdir -p $W/modloop/modules
cp -a "/lib/modules/$KVER" $W/modloop/modules/
cp -a /lib/firmware $W/modloop/modules/firmware
mksquashfs $W/modloop "$TREE/boot/modloop-lts" -comp xz -noappend -quiet >/dev/null

log "initramfs"
mkinitfs -F "ata base cdrom ext4 keymap mmc nvme scsi squashfs usb virtio" \
    -o "$TREE/boot/initramfs-lts" "$KVER" >/dev/null

log "Unseenet itself (a Python environment for the running system)"
python3 -m venv /opt/unseenet
/opt/unseenet/bin/pip install -q --no-cache-dir "/src[tui,monitor]"
sed -i "s/^__version__ = .*/__version__ = \"$VERSION\"/" \
    /opt/unseenet/lib/python3*/site-packages/unseenet/__init__.py
find /opt/unseenet -name __pycache__ -type d -prune -exec rm -rf {} +

log "system configuration (apkovl)"
cp -a "$HERE/overlay/." "$OVL/"
mkdir -p "$OVL/opt" "$OVL/etc/apk/keys"
cp -a /opt/unseenet "$OVL/opt/"
cp "$KEY.pub" "$OVL/etc/apk/keys/"
printf '%s\n' $PACKAGES > "$OVL/etc/apk/world"
: > "$OVL/etc/apk/repositories"      # no network repositories: everything is on the medium
runlevel() {
    level=$1; shift
    mkdir -p "$OVL/etc/runlevels/$level"
    for s in "$@"; do ln -sf "/etc/init.d/$s" "$OVL/etc/runlevels/$level/$s"; done
}
runlevel sysinit devfs dmesg mdev hwdrivers modloop
runlevel boot modules hwclock hostname loopback sysctl bootmisc syslog seedrng
runlevel default dbus iwd dhcpcd local
runlevel shutdown killprocs mount-ro savecache
chmod 755 "$OVL"/usr/local/bin/* "$OVL"/etc/local.d/*
tar -czf "$TREE/unseenet.apkovl.tar.gz" -C "$OVL" --owner=0 --group=0 .

log "boot loaders"
CMDLINE="modules=loop,squashfs,sd-mod,usb-storage,vfat,nls_cp437,nls_iso8859-1 modloop=/boot/modloop-lts quiet loglevel=3"
mkdir -p "$TREE/boot/syslinux" "$TREE/boot/grub" "$TREE/EFI/BOOT"
for f in ldlinux.c32 libcom32.c32 libutil.c32 menu.c32; do
    cp "/usr/share/syslinux/$f" "$TREE/boot/syslinux/"
done
sed -e "s|@CMDLINE@|$CMDLINE|g" -e "s|@VERSION@|$VERSION|g" \
    "$HERE/syslinux.cfg" > "$TREE/boot/syslinux/syslinux.cfg"
sed -e "s|@CMDLINE@|$CMDLINE|g" -e "s|@VERSION@|$VERSION|g" \
    "$HERE/grub.cfg" > "$TREE/boot/grub/grub.cfg"
cat > $W/embed.cfg <<EOF
search --no-floppy --label $LABEL --set=root
set prefix=(\$root)/boot/grub
configfile (\$root)/boot/grub/grub.cfg
EOF
grub-mkstandalone -O x86_64-efi -o "$TREE/EFI/BOOT/BOOTX64.EFI" \
    --modules="part_msdos part_gpt fat search search_label normal linux echo all_video configfile" \
    --locales="" --themes="" --fonts="" "boot/grub/grub.cfg=$W/embed.cfg"

if [ -n "$PORTABLE" ]; then
    log "portable builds from $(basename "$PORTABLE")"
    mkdir -p $W/portable && unzip -q "$PORTABLE" -d $W/portable
    # FAT has no symbolic links (the macOS builds use some): copy what they point to
    cp -RL $W/portable/Unseenet/. "$TREE/"
else
    log "no portable builds given: boot only"
    touch "$TREE/UNSEENET-PORTABLE"
fi
mkdir -p "$TREE/data"
cp "$HERE/README-boot.txt" "$TREE/BOOT-README.txt"

log "FAT32 partition and disk image"
USED=$(du -sm "$TREE" | cut -f1)
SIZE=$(( USED + USED / 10 + 192 ))      # MB: what is there, plus room for data/
FAT=$W/fat.img
truncate -s "${SIZE}M" "$FAT"
mkfs.vfat -F 32 -n "$LABEL" "$FAT" >/dev/null
export MTOOLS_SKIP_CHECK=1
( cd "$TREE" && for f in *; do mcopy -s -i "$FAT" "$f" ::/; done )
mcopy -o -i "$FAT" "$TREE/apks/.boot_repository" ::/apks/.boot_repository
syslinux --install --directory /boot/syslinux "$FAT"

IMG="$OUT/unseenet-$VERSION-$ARCH.img"
rm -f "$IMG" "$IMG.xz"
truncate -s "$(( SIZE + 1 ))M" "$IMG"
printf 'label: dos\nstart=2048, type=c, bootable\n' | sfdisk -q "$IMG"
dd if=/usr/share/syslinux/mbr.bin of="$IMG" bs=440 count=1 conv=notrunc 2>/dev/null
dd if="$FAT" of="$IMG" bs=1M seek=1 conv=notrunc 2>/dev/null
if [ -z "${NOXZ:-}" ]; then              # NOXZ=1: skip it while trying things out
    log "compressing"
    xz -T0 -6 -f -k "$IMG"
fi
ls -l "$OUT"/unseenet-*
log "done: $IMG ($SIZE MB)"
