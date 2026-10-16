#!/bin/sh
# Start Unseenet from this folder (Linux). Run it from a terminal:
#     sh /path/to/Unseenet/start-linux.sh
# Extra arguments are passed on, e.g. "sh start-linux.sh --self-test".
HERE=$(cd "$(dirname "$0")" && pwd)
ARCH=$(uname -m)
case "$ARCH" in amd64) ARCH=x86_64 ;; arm64) ARCH=aarch64 ;; esac
BIN="$HERE/linux-$ARCH/unseenet"
if [ ! -f "$BIN" ]; then
    echo "Unseenet for Linux ($ARCH) is not in this folder." >&2
    exit 1
fi
if [ -x "$BIN" ]; then
    exec "$BIN" "$@"
fi
# FAT-formatted USB sticks are often mounted without execute permission;
# the system's program loader can still start the program.
for LD in /lib64/ld-linux-x86-64.so.2 /lib/ld-linux-aarch64.so.1 /lib/x86_64-linux-gnu/ld-linux-x86-64.so.2; do
    if [ -e "$LD" ]; then
        exec "$LD" "$BIN" "$@"
    fi
done
echo "Cannot start $BIN: the stick is mounted without execute permission." >&2
echo "Copy the Unseenet folder to your home directory, or remount the stick with 'exec'." >&2
exit 1
