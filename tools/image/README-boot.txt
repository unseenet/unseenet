UNSEENET - BOOTABLE AND PORTABLE
================================

This stick (or card, or disk) can be used in two ways, with the same data:

1. Boot from it. Restart the computer and choose this stick in its boot menu
   (often F12, F11, F9, F8 or Esc right after switching on; on a Mac, hold
   Option). Unseenet starts in a text console and runs from memory: nothing
   is written to the computer's own disks.

   If the computer refuses to start it, turn off "Secure Boot" in its
   firmware settings (BIOS/UEFI setup).

2. Use it on a running computer. Open the stick and start
     Windows:  Start Unseenet.bat
     macOS:    Start Unseenet.command
     Linux:    sh start-linux.sh

Both use data/ on this stick: your vault (keys, groups, contacts), the offline
cache and Tor's state. The vault and the cache are encrypted with your
passphrase. To move to another stick or a portable installation, copy data/.

Documentation: https://unseenet.org/bootable/
