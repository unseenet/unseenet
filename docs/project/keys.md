# The project's keys

The Unseenet project owns a handful of groups on the network: the place to
talk, the announcements, the lists that clients read, and the registrar for
names. This page describes the keys behind them and how they are looked
after, so that anyone can check how the project works and do the same for a
project of their own.

## Who holds what

| Key | Kept | Can |
|-----|------|-----|
| **Project key** `ed25519:det5dxev...` (fingerprint `ph5fc5hop5232qsz`) | Only in the maintainer's encrypted owner vault, offline backups | Change the project's groups: who may post, the registrar's keys, the claim inbox |
| **GitHub poster** | Repository secret `UNSEENET_ANNOUNCE_SEED`, and the owner vault | Post in `unseenet.announce`, `unseenet.nodes`, `unseenet.hierarchies`, `unseenet.checkgroups` |
| **Release key** `ed25519:clbv6765...` | Repository secret `UNSEENET_RELEASE_KEY` only | Sign the checksums of development builds, which sticks accept only on the development channel |
| **Registrar keys**, one per replica | On each replica's machine, in its vault | Sign name certificates in `unseenet.names` |
| **Registrar inbox key** | The owner vault and every replica's vault | Open claims; nothing else |

The project key never touches GitHub, a node or a replica. Everything that
runs unattended uses a key that the project key has listed as a **poster**
in a group's manifest. If such a key leaks, the owner removes it from the
manifest and makes a new one: the groups, and the project key, are not at
risk.

## The owner vault

The project key lives in an Unseenet vault, encrypted with Argon2id and
XChaCha20-Poly1305 like every user's vault ([UN-RFC 0007](../spec/un-rfc-0007.md)),
on the maintainer's own computer (`~/.unseenet/owner.vault`, folder `700`,
file `600`). Its passphrase is kept in a password manager and is only ever
typed into a terminal.

Two copies of the vault file are kept on USB sticks in two different
places. They are useless without the passphrase. Losing every copy would
mean the project's groups could never be changed again.

## The scripts

The scripts in [`tools/project/`](https://github.com/unseenet/unseenet/tree/main/tools/project)
are what the maintainer runs with the owner vault. Each asks for the
passphrase in the terminal; none reads it from a file, the environment or
the command line.

| Script | Does |
|--------|------|
| `change_passphrase.py` | Encrypts the owner vault again under a new passphrase, checks that it opens, and keeps the old file until you delete it. |
| `create_groups.py` | Lists every group the project owns, with its type, posters, view and rules. Creates those that do not exist yet, and gives existing ones a new manifest when their view, title, description, rules or `min_pow` differ from the list. |
| `sign_release.py vX.Y.Z` | Signs a release's `SHA256SUMS.txt` with the project key and uploads `SHA256SUMS.txt.sig`, so [sticks](../bootable.md#updating) will update to it. Run it when the release's workflows are done. |
| `new_release_key.py` | Makes a new release key for development builds and puts it straight into the repository secret (never in a file); prints the public key to pin in `src/unseenet/update.py`. |
| `setup_registrar.py` | Creates the registrar's inbox key and claim inbox, and sets which replicas' keys may issue names (`--add`, `--remove`). |

`create_groups.py` and `setup_registrar.py` take `--dry-run`, which signs
everything and posts nothing. They post over Tor to every node in the
project's list.

## The groups

| Group | Type | Who posts |
|-------|------|-----------|
| `unseenet` | open | anyone |
| `unseenet.test` | open | anyone |
| `unseenet.announce` | channel | the GitHub poster: releases and news |
| `unseenet.nodes` | channel | the GitHub poster: the node list ([UN-RFC 0010](../spec/un-rfc-0010.md)) |
| `unseenet.hierarchies` | channel | the GitHub poster: the root list ([UN-RFC 0018](../spec/un-rfc-0018.md)) |
| `unseenet.checkgroups` | channel | the GitHub poster: the groups of `unseenet.*` (UN-RFC 0018 section 5) |
| `unseenet.names` | channel | the registrar's replicas ([UN-RFC 0019](../spec/un-rfc-0019.md)) |
| `unseenet.admin` | open | anyone: hierarchy requests and name disputes |

All have the fingerprint `ph5fc5hop5232qsz`, for example
`unseenet.announce@ph5fc5hop5232qsz`. The node list and the root list are
kept in the repository and posted automatically when they change and every
month.
