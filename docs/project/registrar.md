# Running a registrar replica

The registrar gives out names for identities, such as `@lorensen`
([UN-RFC 0019](../spec/un-rfc-0019.md)). It runs as several **replicas**,
each on its own machine, so that names keep being given out and renewed
when one machine is gone. A replica is a client, not a node: it reads and
posts through whichever nodes are up, over Tor, and it needs no connection
to the other replicas.

Every replica reads the same claims from one shared claim inbox, handles
them in the same order, and signs its own certificate for each decision.
Because all of that comes from the network, a replica keeps nothing that
cannot be rebuilt: start it on a new machine and it catches up by itself.

## What a replica needs

- Python 3.11 or newer, Tor, and `dig` (for checking the DNS records of
  domain names). On Debian: `apt install tor dnsutils python3-venv`.
- Its own **registrar key**, made on its machine by `init`.
- The shared **inbox key**, from the owner of the registrar's group.

## Setting one up

1. Install Unseenet as for a node (see [Installation](../node/install.md)),
   as the user `unseenet`.
2. Make the replica's vault. Press Enter at the first question to make a
   new registrar key here; at the second, type the inbox key's seed, which
   the group's owner gets with `tools/project/setup_registrar.py
   --show-inbox-seed`:
   ```bash
   sudo -u unseenet /home/unseenet/unseenet/.venv/bin/unseenet-registrar init /home/unseenet/registrar.vault
   ```
   It prints the replica's registrar key. That key is public.
3. The group's owner adds it:
   ```bash
   python tools/project/setup_registrar.py --add ed25519:...
   ```
4. Put the vault's passphrase in `/etc/unseenet-registrar.passphrase`
   (owner root, mode `600`), install
   [`deploy/unseenet-registrar.service`](https://github.com/unseenet/unseenet/blob/main/deploy/unseenet-registrar.service)
   and start it:
   ```bash
   sudo cp deploy/unseenet-registrar.service /etc/systemd/system/
   sudo systemctl enable --now unseenet-registrar
   journalctl -u unseenet-registrar -f
   ```

Every five minutes the replica reads the group and the claim inbox,
handles the claims that are more than an hour old, follows decisions of
other replicas that win over its own, and renews domain names whose DNS
record is still there at the start of each month.

## Where to run replicas

Not on the project's nodes, and not all in one place: the point is that
taking one machine down does not stop the registrar. A small virtual
machine, a Raspberry Pi at home or a machine run by someone the project
trusts will do; each runs with its own key, and the group's owner can
remove any one of them without affecting the names the others signed.

## If a key is stolen

- **A registrar key:** the owner removes it with `setup_registrar.py
  --remove`. Its certificates stop counting; the same decisions, signed by
  the other replicas, stay valid.
- **The inbox key:** it opens claims, which say little that the
  certificates do not. The owner makes a new one; for now that means
  removing `registrar_inbox` from the owner vault and running
  `setup_registrar.py` again, then giving every replica the new seed.
