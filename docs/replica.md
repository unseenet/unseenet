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
   replica keeps up with the network by itself;
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
| Stop updating by itself | `sudo systemctl disable --now unseenet-replica-update.timer` |

**Back up** `/var/lib/unseenet-replica/replica.vault` and
`/etc/unseenet-replica/passphrase`. Together they are the replica: with them it
can move to another machine (install, stop the service, put both files back,
start it). Without them a new replica starts from the beginning.

## Privacy

- The replica reaches the network only over Tor. Nobody learns from the network
  where it runs or who runs it; a member is just a key. Its signs of life are
  posted at random times, so they mark no schedule.
- Updates are fetched from PyPI (or GitHub with `UNSEENET_CHANNEL=main`) over the
  ordinary internet. That shows the machine's address installs Unseenet, not that
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
