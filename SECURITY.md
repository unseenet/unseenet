# Security

Unseenet is meant to protect people who may be in danger, so weaknesses
matter more than usual. Thank you for looking.

## Reporting a problem

**Please do not open a public issue.** Report it privately instead:
[Security → Report a vulnerability](https://github.com/unseenet/unseenet/security/advisories/new).
Only the maintainers can read it.

Useful to include: what an attacker can learn or do, who that attacker is
(a node operator, someone watching the network, someone who has the USB
stick), and how to reproduce it.

We answer within a week, work out a fix with you, and credit you in the
release notes unless you would rather not be named.

## Supported versions

Unseenet is pre-alpha. Until 1.0:

- The **latest minor release** (now 0.3.x) gets security and bug fixes,
  until the next minor release comes out. Then upgrade.
- Fixes are made on `main` first and carried to a `release/0.x` branch,
  which is created the first time a fix is needed. That branch takes only
  fixes: no new features and no protocol changes.
- There is no compatibility guarantee before 1.0. A new minor release
  tries to keep talking to nodes of the previous one
  ([Versioning](docs/development.md#versioning)), but the network follows
  the newest version: the project's own nodes always run it.

## What counts

Anything that could reveal who someone is, where they are, what they read
or write, or who they talk to; that lets someone read a closed group or an
inbox they should not; that lets someone post as someone else; or that
leaves readable traces on a stick, a node or a computer. Weaknesses in the
UN-RFCs themselves count as much as bugs in the code.

Unseenet is pre-alpha and has not had an independent security review yet.
Do not rely on it where your safety depends on it.
