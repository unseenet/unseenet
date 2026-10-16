#!/bin/sh
# Start Unseenet from this folder (macOS). Double-click it in the Finder.
# The first time, macOS may say the developer cannot be verified: right-click
# this file, choose Open, and confirm. See README.txt.
HERE=$(cd "$(dirname "$0")" && pwd)
case "$(uname -m)" in arm64) ARCH=aarch64 ;; *) ARCH=x86_64 ;; esac
BIN="$HERE/macos-$ARCH/unseenet"
if [ ! -f "$BIN" ]; then
    echo "Unseenet for macOS ($ARCH) is not in this folder."
    read -r _
    exit 1
fi
# Files from a downloaded zip are quarantined; allow this folder's programs.
xattr -dr com.apple.quarantine "$HERE/macos-$ARCH" 2>/dev/null
printf '\033]0;Unseenet\007'
"$BIN" "$@"
