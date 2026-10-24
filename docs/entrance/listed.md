# Being listed

Web clients and the jump page (`unseenet-entrances.html`) offer the entrances
on a list the project signs and posts in `unseenet.entrances`
([UN-RFC 0043](../spec/un-rfc-0043.md) section 8.1). The more entrances run
by different people, in different places, the harder it is to keep anyone out
of Unseenet. The list says who is known, not who is safe: no one can see
whether an entrance keeps logs, so it is only as good as the promise of
section 5 and the checks below.

## Asking

1. [Install the entrance](index.md#installation), and set `ENTRANCE_OPERATOR`
   (your own identity key) and `ENTRANCE_CONTACT` in
   `/etc/unseenet-entrance.env`, so visitors see who runs it.
2. Open an [Add my entrance](https://github.com/unseenet/unseenet/issues/new?template=add-entrance.yml)
   issue with its open-web address, its onion address (or both), your
   operator key and a few words about it.
3. A check runs at once and answers in the issue. It posts a **challenge**:
   add it to `/etc/unseenet-entrance.env` as
   `ENTRANCE_CLAIM="unseenet-entrance-claim ..."`, run
   `systemctl restart unseenet-entrance`, and comment in the issue. The
   entrance then shows it in `/.well-known/unseenet-entrance` - proof that
   whoever asked runs it.
4. When everything checks out, a maintainer accepts the request: the entrance
   is added to `src/unseenet/entrances.json` and the new list is posted. Remove
   `ENTRANCE_CLAIM` again.

## What is checked

At every address you give - over HTTPS, and over Tor for the onion, the way
visitors reach it:

- `/.well-known/unseenet-entrance` answers and names the operator key you
  gave (and, while asking, shows the challenge);
- **every file of the web client** it serves matches the SHA-256 that a signed
  post in `unseenet.releases` gives for the version in its `version.json`. The
  posts are read from the entrance's own `/.well-known/unseenet-releases.json`
  and checked against the project key, so an entrance cannot make one up. A
  test build (`BUILD=local`) is fine for trying things, not for the list;
- a WebSocket on `/onntp` reaches a known node and brings its greeting.

## Every day

The same checks run every day for every listed entrance
(`tools/entrance_health.py`):

- one that serves **files other than the signed client** is taken off the
  list **at once** (section 7.6);
- one that cannot be reached, does not tunnel or does not name its operator
  gets a note in its issue after **3 days**, and is taken off after **10**;
  when it passes again, the failure is forgotten;
- one that serves a version **no longer in the signed list** (old posts expire)
  gets a note to check that it updates itself. That alone never takes it off:
  nothing it serves is wrong.

If every entrance fails on the same day, the problem is almost certainly the
checker's own network, and nothing is counted.
