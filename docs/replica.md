# Running a replica

The names people use in Unseenet - `@lorensen`, `andlo@lorensen.dk` - are handed
out by a **registrar**. Unseenet's registrar has no owner: it is run by a
**council** of replicas on different machines, kept by different people, that
each make the same decisions and sign the same certificates. No single key -
the project's included - can give a name away, or decide who sits on the
council. The rules are in [UN-RFC 0054](https://unseenet.org/spec/un-rfc-0054/);
this page is about running one.

Anybody can run a replica, and nobody needs to know who you are. A new replica
starts as a **shadow**: it does the same work as the council but signs nothing,
and posts once a day what it would have decided. When it has agreed with the
council for 60 days, and its key is ripened, the members' own replicas let it
in - by themselves, nobody votes. It is then a member on probation, and after
180 days a full member that takes part in every decision about the council.

## What you need

- A small, always-on Linux machine: a **Raspberry Pi 4 or 5** with the 64-bit
  Raspberry Pi OS, a cheap **VPS** (1 GB of memory is enough), or a container
  in a homelab. It must be 64-bit (x86_64 or arm64).
- Debian, Ubuntu or Raspberry Pi OS, with systemd.
- No public IP address, no open ports and no domain: the replica reaches the
  network over Tor, like any client.
- About 1 GB of disk.

A replica uses little: a few minutes of work every few minutes, and one CPU core
at low priority while its key ripens (see below).

## Install

On the machine, as root:

```bash
curl -fsSL https://raw.githubusercontent.com/unseenet/unseenet/main/deploy/install-replica.sh | sudo bash
```

!!! info "Read before you pipe"
    Piping a script into `bash` runs it as root. If you prefer, download it
    first and read it:
    `curl -fsSLO https://raw.githubusercontent.com/unseenet/unseenet/main/deploy/install-replica.sh`

The script installs Tor and Unseenet in `/opt/unseenet-replica`, then runs
`unseenet-replica setup`, which:

1. makes the replica's **key**, and a **vault** for it in
   `/var/lib/unseenet-replica`, locked with a random passphrase that is kept in
   `/etc/unseenet-replica/passphrase` (readable by root only);
2. writes the replica's settings to `/var/lib/unseenet-replica/config.json`;
3. creates the system user `unseenet-replica`, and installs and starts the
   service `unseenet-replica`;
4. installs a **daily update** (`unseenet-replica-update.timer`), so the
   replica keeps up with the network by itself. It takes only releases the
   project key has signed, waits a random time of up to 48 hours after a release
   appears, and goes back to the version it ran if the replica does not come up
   ([UN-RFC 0062](https://unseenet.org/spec/un-rfc-0062/) section 6.1);
5. prints the replica's key.

Then, and at any time after:

```bash
unseenet-replica status
```

```text
This replica works for the council registrar unseenet.names@....
Its key: ed25519:q4v7x2...
It runs as a SHADOW: it decides every name claim like the council, issues
nothing, and posts what it decided once a day. After 60 days of agreeing,
the members' replicas let it in by themselves.
Reports in the last 60 settled days: 34 (55 are needed).
Its key is ripening: level 3 of the 4 the council asks for. This takes weeks and runs by itself.
The council has 3 members, 3 of them full.
Last round: 2 minutes ago. Software: unseenet-replica 0.7.0.
```

### Choices

Set these before running the script (`sudo -E bash` keeps them):

| Variable | Meaning |
|----------|---------|
| `UNSEENET_CHANNEL=main` | Install and update from the newest code on GitHub instead of releases. Only for testing. |
| `UNSEENET_GROUP=...` | Another council registrar than the project's. |
| `UNSEENET_HOLD=removal` | Changes you want to agree to yourself first (see [Holding](#holding)). |

Or run `sudo unseenet-replica setup --help` yourself in an existing
installation.

## In Docker

The replica is also a container image, `ghcr.io/unseenet/replica`, for amd64
and arm64: `unseenet-replica` and Tor on Alpine Linux, the same build as the
[node's image](node/docker.md). Save
[`docker-compose.replica.yml`](https://github.com/unseenet/unseenet/blob/main/deploy/docker-compose.replica.yml),
give the replica a passphrase in a file next to it, and start it:

```bash
echo 'a long passphrase only you know' > unseenet_replica_passphrase.txt
chmod 600 unseenet_replica_passphrase.txt
docker compose -f docker-compose.replica.yml up -d
docker compose -f docker-compose.replica.yml logs replica      # the replica's key
docker compose -f docker-compose.replica.yml exec replica unseenet-replica status
```

The first start makes the key and the vault in the volume, sealed with the
passphrase; the passphrase itself never goes into the volume. `status`,
`hold`, `agree`, `sign` and the other commands below work the same way with
`docker compose exec replica unseenet-replica ...`. After `sign`, restart the
container so that the replica works for the new council.

Running a node too? [`docker-compose.node-replica.yml`](https://github.com/unseenet/unseenet/blob/main/deploy/docker-compose.node-replica.yml)
starts both: the replica reads and posts through the node beside it, on a
Docker network of their own with no published port, and the node reaches
everybody else over Tor. Add other nodes' onion addresses to
`UNSEENET_REPLICA_NODES` before the first start, comma separated, so that no
single node can hide claims from your replica. Your replica's posts then
leave through your node, so whoever watches the node could link the two; on
its own, a replica reaches the network over Tor like any client.

| Variable (first start only) | Meaning |
|-----------------------------|---------|
| `UNSEENET_REPLICA_PASSPHRASE` | The passphrase, if you do not use the secret file (`docker inspect` shows it) |
| `UNSEENET_REPLICA_HOLD` | Changes you want to agree to yourself first, e.g. `removal` |
| `UNSEENET_REPLICA_GROUP` | Another council registrar than the project's |
| `UNSEENET_REPLICA_NODES` | Nodes to use, comma separated; by default the known nodes |

**Updating.** A replica in a container does not update itself:
`docker compose pull && docker compose up -d` gets the newest signed
release. Images are made for every release and signed (cosign).

!!! danger "One volume, one replica"
    The volume *is* the replica: its key, vault and state. Back it up (with
    the container stopped), but never start a second container on it or on a
    copy while the first still runs - not on another machine, not to try
    something out. Two replicas with one key can split the council; the
    replica stops signing when it sees it, and you then need `twin-gone`
    ([Looking after it](#looking-after-it)).

## What happens next

Nothing more is needed from you. In order:

1. **Ripening.** The council asks for keys that have done some work first
   ([UN-RFC 0025](https://unseenet.org/spec/un-rfc-0025/)), so that nobody can
   make shadows in bulk. The replica ripens its key at low priority beside its
   other work. To level 4, the usual minimum, this takes weeks on a Raspberry
   Pi. `status` shows how far it is.
2. **Shadow.** From the first day, the replica reads every public name claim,
   decides it by the same rules as the council, and posts a short report each
   day - a hash of each decision, never the reasons. A report for a day is
   posted 8 days later, once every claim of that day is settled, and only then.
   A day the replica was offline is lost; 5 lost days in 60 are allowed.
3. **Admission.** When the replica has reported on 55 of the last 60 settled
   days, every report agreeing with the council, and its key is ripe, the
   members' replicas each post the same new council manifest admitting it - at
   most one newcomer every 30 days, the one that started first.
4. **Probation.** Your replica now signs certificates for the names it decides,
   and answers the people who claimed them. It posts a short sign of life now
   and then. After 180 days it becomes a full member.
5. **Full member.** It now also takes part in every change of the council:
   admitting the next shadow, promoting, and removing members that sign
   certificates no claim explains, fall silent for 90 days, or step down.

If your replica disagrees with the council on a decision, it is not admitted
until 60 days without disagreement have passed. Decisions on domain names
(`andlo@lorensen.dk`) depend on DNS answers, which may differ from place to
place, and are not held against anybody.

## Founding a council

A new council is founded by the replicas that run at the time, at least
three, on different machines. Anybody may write the draft, also somebody who
is not a member, such as the founder:

```bash
unseenet council create unseenet.names --without-me --claims --groups \
    --member ed25519:<replica 1> --member ed25519:<replica 2> --member ed25519:<replica 3> \
    --founding 3 --founder ed25519:<founder> --min-level 3
```

`--claims` adds the group for public claims, `--groups` the groups for
proposals, talk and the log ([UN-RFC 0061](https://unseenet.org/spec/un-rfc-0061/)),
and `--founding` a founding period in which the founder can admit members
faster ([UN-RFC 0054](https://unseenet.org/spec/un-rfc-0054/) section 19).
Copy the draft file to each replica, and there run:

```bash
sudo unseenet-replica sign unseenet.names.council.json
```

It shows what the draft says and asks first. The service then posts the
replica's copy of the genesis with its key, and works for that council from
then on. The council counts once every member has posted the same. When the
council takes over a registrar (the project's moves this way, section 14), each
replica re-issues the old group's certificates that were valid at the genesis,
and the old group's owner posts a last manifest pointing to the council
(`tools/project/move_registrar.py`).

## Holding

The replica posts every change the rules call for by itself; that is what keeps
the registrar running when nobody looks. If you want a say, **hold** a kind of
change - `admission`, `promotion`, `removal`, or `all`:

```bash
sudo unseenet-replica hold removal
```

A held change then waits for you. `status` shows it, with the command to let it
go ahead:

```text
HELD, waiting for you: removal of ed25519:... - signed a certificate no claim explains.
  To let it go ahead:  sudo unseenet-replica agree removal:ed25519:...
```

Holding never blocks the council: the other members' replicas still decide, as
long as enough of them post. It is your own replica's voice you keep back.
Anybody can post an **objection** to a shadow or a member; `status` shows the
objections made by full members, so that you have the reason in front of you.
`sudo unseenet-replica hold none` lets everything go ahead again.

## Proposals and hearings

Some things no rule can decide: changing the council's own settings, or making
its founding period longer. For those the members make a **proposal**, which
stands in public for a **hearing** of at least 14 days. Anybody whose key has
ripened may object; if more people object than there are active members, it
fails. Otherwise the replicas apply it themselves on the same day.

Your replica's key *is* your member: you speak with it through the replica, which
posts what you queue at its next round.

```bash
sudo unseenet-replica talk "Hello" "Still here, and the replica runs fine"
sudo unseenet-replica propose --set min_level=3 --reason "Level 4 takes too long on small machines"
sudo unseenet-replica second <id>          # join a proposal another member made
sudo unseenet-replica object <id> "why"    # object to one
```

`status` shows open hearings and proposals waiting for more members. Only
**active** members - those who said something in the council's talk or proposals
group in the last 90 days - count when people decide; the replica keeps working
either way, and the council's log warns two weeks before a member stops being
active. To agree to each applied proposal yourself, `sudo unseenet-replica hold
proposal`.

Anybody, member or not, can follow the hearings with the ordinary client:

```bash
unseenet council hearings unseenet.names@...
unseenet council object unseenet.names@... <id> "why"
```

## The council's room

A council can have a closed **room** where the members talk. Nobody hands its key
over by hand: the replicas do it - a newcomer gets the key when it is admitted, and
when a member leaves, the others get a new key that the one who left does not have.
A member reads and writes the room with the same key its replica uses.

## Stepping down

```bash
sudo unseenet-replica resign
sudo systemctl disable --now unseenet-replica unseenet-replica-update.timer
```

The replica posts a signed `resign`, and the other members' replicas remove its
key. That cannot be undone: to come back, a new key starts again as a shadow. A
replica that is simply switched off is removed after 90 days of silence;
`resign` is the clean way.

## Looking after it

| | |
|---|---|
| How it is doing | `unseenet-replica status` |
| Its log | `journalctl -u unseenet-replica -n 100` |
| Restart | `sudo systemctl restart unseenet-replica` |
| Update now | `sudo systemctl start unseenet-replica-update` |
| What the update did | `/opt/unseenet-replica/bin/unseenet-service-update status --service unseenet-replica` |
| Stop updating by itself | `--channel off` at setup; it then only warns in its log when a release has been out 30 days |

**Back up** `/var/lib/unseenet-replica/replica.vault` and
`/etc/unseenet-replica/passphrase`. Together they are the replica: with them it
can move to another machine (install, stop the service, put both files back,
start it). Without them a new replica starts from the beginning.

**One key, one replica.** Never run two copies of the same replica - for example
the old machine still running after you moved it. Two replicas with one key can
sign two different versions of the council, and the council then stops. If a
replica sees a post with its key that it did not send, it stops signing and
`status` says so. Stop the other copy (or set this one up again with a new key),
then run the `twin-gone` command that `status` shows.

## Privacy

- The replica reaches the network only over Tor. Nobody learns from the network
  where it runs or who runs it; a member is just a key. Its signs of life are
  posted at random times, so they mark no schedule.
- Updates are fetched from GitHub and PyPI (only GitHub with `UNSEENET_CHANNEL=main`)
  over the ordinary internet. That shows the machine's address installs Unseenet, not that
  it runs a replica. If that matters to you, turn the timer off and update by
  hand over Tor.
- Name claims are public by design: anybody can see which key claimed which
  name. Your replica sees nothing that others cannot.

## Trying it out

To try a replica without systemd, as an ordinary user:

```bash
python3 -m venv ~/replica && ~/replica/bin/pip install unseenet
~/replica/bin/unseenet-replica --dir ~/replica-data setup --no-systemd
~/replica/bin/unseenet-replica --dir ~/replica-data run --passphrase-file ~/replica-data/passphrase
```
