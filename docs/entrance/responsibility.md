# Your responsibility as an entrance operator

An entrance lets people into Unseenet from the open web. It carries their
connections; it does not store what they write. That is a different role from
a [node's](../node/responsibility.md), and worth thinking about before you
open one to strangers.

## What the entrance does to make this easier

- **It holds nothing.** No posts, no groups, no vaults, no keys. Everything a
  visitor reads and writes is on the nodes and in their own browser.
- **It cannot read or change anything.** Posts are signed in the browser and
  checked there; closed groups and private posts are encrypted end to end.
  The entrance only copies bytes between the browser and a node's onion
  service.
- **It logs nothing about visitors.** No access log, no error that names an
  address; limits are counted in memory under a key made at start
  (UN-RFC 0043 section 5). `install.sh` keeps the system journal in memory
  only, unless you say `JOURNAL=keep`.
- **It only goes to known nodes**, unless you set `ENTRANCE_NODES=any`.

## What you should know

- **You see visitors' IP addresses**, for as long as they are connected. That
  is the price of the open web, and visitors are told it (the bar at the top,
  and [What you give up](../web.md#what-you-give-up)). Do not add logging,
  analytics or a CDN in front: they would keep what the entrance is built not
  to keep.
- **You serve code.** The web client you serve is the project's signed
  build; leave automatic updates on, or check new versions yourself. Never
  change the files you serve: apps warn about anything that is not signed.
- **Say who you are.** Set `ENTRANCE_OPERATOR` and `ENTRANCE_CONTACT`, so
  visitors and other operators can reach you.
- **Know the law where you live,** and where your machine is. Carrying
  encrypted connections for others is treated differently from country to
  country. Unseenet's design reduces the risk; it does not remove your
  responsibility.
- **Problems with what people post** belong to the nodes that carry it, the
  groups' owners and moderators, and the hierarchy maintainers - see
  [a node's responsibility](../node/responsibility.md). An entrance has no
  posts to remove, and by default it tunnels only to the project's list of
  known nodes, which must follow the rules for listed nodes.
