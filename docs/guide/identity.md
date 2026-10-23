# Identity

On a platform, you are an account: a row in somebody's database, with a
password, an e-mail address and often a phone number. On Unseenet there
is no database and no account. You are a key. This chapter is about what
that means: where the key lives, how people recognise you, why a new key
has to wait before it can post cheaply, and what you can say about
yourself.

## You are a key

The first time you start a client, it makes a **key pair** for you: a
private key that never leaves your vault, and a public key that everyone
may see. Unseenet uses Ed25519, the same kind of key as modern SSH.

The public key is written like `ed25519:4bq5...`, sixty characters long,
and it *is* your identity. Everything you write is signed with the
private key, and anyone can check the signature against the public key.
So:

- nobody can post in your name, not even a node operator;
- nobody can change a word of what you wrote;
- you do not have to trust any server to know who wrote something.

Sixty characters are too long to look at, so clients show a
**fingerprint**: a short hash of the key, such as `2byg`, after the name
the person chose. `Maja~2byg` and `Maja~7f3a` are two different people,
however much they both like the name Maja.

### As many as you like

A key costs nothing to make, so you can have as many identities as you
want. That is a privacy tool in its own right: if you use one identity in
your local football group and another in a group about a health problem,
nothing in the network links the two. The client keeps them apart for you
and asks which one you want to use where.

## The vault

Your keys, the secrets of the closed groups you are in, the groups you
follow and what you have read are kept in one file: the **vault**. It is
encrypted with a key made from your passphrase (with Argon2id, which is
deliberately slow to guess), and it is only ever opened in memory. The
client writes nothing readable to the computer it runs on.

That is what makes it safe to carry Unseenet on a USB stick. If you lose
the stick, or it is taken from you while it is unplugged, whoever has it
sees an encrypted file and nothing else.

What the vault cannot protect against is just as important:

- a computer that is already compromised - a keylogger sees your
  passphrase as you type it, which is why the bootable stick exists;
- someone who forces you to give up your passphrase - that is a legal
  problem, not a technical one;
- losing the vault *and* every copy of it. There is no "forgot my
  password" link, because there is nobody to send it. Keep a copy.

!!! info "Coming in 0.5.0: your state in the network"
    Today, the groups you follow and what you have read live only in your
    vault, so a new stick or the browser client starts empty. From 0.5.0
    each identity can keep that state in the network itself, encrypted so
    only its key can read it, and the vault only has to hold the keys.

## Names

A fingerprint tells two Majas apart, but nobody can remember it. So an
identity may also have a **name**. A client shows the first of these that
applies:

1. **A petname** - a name *you* gave someone's key in your own client.
   It never leaves your computer, and it always wins, so nobody can trick
   you by taking a name that looks like your friend's.
2. **A domain name** such as `@lorensen.dk`, proven by a record in the
   domain's DNS.
3. **A name under a name** such as `sonia@lorensen`, given by whoever
   holds `@lorensen` - like an e-mail address. A domain can name people
   the same way: `andlo@lorensen.dk`.
4. **A registered name** such as `@lorensen`, first come, first served.
5. Otherwise the name the person chose, with the fingerprint:
   `Maja~2byg`.

Registered and domain names are given out by a **registrar** as signed
certificates. The identity carries its certificate along with its posts,
so a client can check a name without asking anyone. A registered name
lasts a year and is renewed by the client without you noticing; names
that are Internet top-level domains, such as `@dk` or `@microsoft`,
cannot be registered.

The registrar is not a central point of failure. It runs as several
**replicas** on different machines, any one of which can answer, and the
names already given out keep working even if every replica is off -
the certificates are in the posts. And a registrar has no power over
anyone: it cannot stop an identity posting, change a post or remove one.
An identity without a name can do everything an identity with one can,
and clients must not treat it as less trustworthy.

There is one thing to remember about names: a name links everything its
identity writes. Give one to the identity you want people to recognise,
not to the one you keep apart.

## Why a new key has to ripen

Free keys have a dark side. If keys cost nothing, a spammer can use a new
one for every post, and no ban ever catches up with them. Platforms solve
this by asking for a phone number. Unseenet will not do that, because it
would mean someone keeping a list of who is who.

Instead, a key **ripens**. From the moment a key is made, the client
works on a calculation that has to be done step by step - it cannot be
sped up by using many computers at once - and that anyone can check in
milliseconds. The result is published by the key itself, and the riper
the key, the less postage it pays:

| Ripeness | Takes about | Postage |
|----------|-------------|---------|
| Level 0 | 7 minutes | highest - roughly a minute of work per post in an open group |
| Level 3 | 2½ days | normal - about a second |
| Level 4 | 10 days | lowest |

*(Times measured on one core of a fast desktop. A small ARM server took
about half as long again; laptops, phones and Raspberry Pis are still to
be measured.)*

For you it means that a brand-new identity waits a few minutes before it
can post, and becomes cheaper to use over the following days while the
client runs. For a spammer it means that every throwaway key costs real
time, and a ban on a ripe key costs them days.

The important part is who decides: **nobody**. A key's ripeness is a
fact anyone can check from the key's own proof. No register, no company
and no government can grant it or take it away. A node may be stricter
than that for its own reasons, but it can never make anyone else's node
treat a key as less ripe than its proof says.

## Profiles

An identity may say something about itself in a **profile**: a short
text and a list of places to find it elsewhere - a web site, Mastodon,
Matrix, Facebook, TikTok. A profile can also have a small picture, and
every identity has an **identicon**, a pattern drawn from its key, so
it is recognisable even with no picture.

A public profile lives in a group of its own that the identity owns, so
anyone who knows the key can find it and nodes carry it like any other
group. A private profile is the same thing sent only to chosen people.
Clients never fetch anything from the ordinary web for a profile without
you asking: a link in a profile stays a link until you choose to open it.

Profiles do not last for ever. Your client renews yours whenever it
runs; the profile of a key nobody uses any more expires by itself after
at most two years, so the network does not fill up with the ghosts of
abandoned identities. The same goes for an identity's inbox and its
other personal groups.

!!! info "Coming in 0.6.0: attestations"
    A way for others to vouch for a key - "this really is the Andreas I
    know" - so that people who want to be recognised can be, without
    anyone central deciding who is real.

**Details:**
[UN-RFC 0003](../spec/un-rfc-0003.md) (keys, fingerprints, crypto),
[0007](../spec/un-rfc-0007.md) (the vault and data at rest),
[0019](../spec/un-rfc-0019.md) (names),
[0022](../spec/un-rfc-0022.md) (profiles),
[0025](../spec/un-rfc-0025.md) (key ripening),
[0029](../spec/un-rfc-0029.md) (key-bound groups and their lifetime),
[0036](../spec/un-rfc-0036.md) (attestations),
[0044](../spec/un-rfc-0044.md) (your state in the network).
