# The project's nodes

The Unseenet project runs a few nodes of its own, listed in
`src/unseenet/nodes.json` with the project key as `operator`. They are the
first nodes new users are offered, so they must be connected to each other
and to every other listed node ([UN-RFC 0021](../spec/un-rfc-0021.md)).

| Node | Where | Status |
|------|-------|--------|
| `unseenet-node1` | the maintainer's Proxmox, Denmark | test node, may be reset |
| `unseenet-node2` | the maintainer's Proxmox, Denmark | test node, may be reset |
| `unseenet-node3` | Oracle Cloud Always Free (Ampere A1) | stable: kept running, not reset |
| `unseenet-node4` | Oracle Cloud Always Free (Ampere A1) | stable: kept running, not reset |

## Every project node peers with every other

The project's nodes form a full mesh: each has a `[[peer]]` for each of the
others, with `groups`, `pull` and `accept` all `"*"`. Nobody has to
remember who is missing:

```bash
cd /home/unseenet/unseenet
.venv/bin/python tools/project/project_peers.py unseenet-node1 --check /home/unseenet/node.toml
```

prints the sections the node is missing (and exits 1), or that it has
them all. Without `--check` it prints every section the node needs.

**When a project node is added** (the Oracle Cloud nodes, say):

1. Install it as any node ([Installation](../node/install.md)) and note
   its onion address and node key.
   In its `node.toml`, set `require_peer_auth = true` under `[node]` and
   add an `[operator]` section like the other project nodes: the project
   key, the project's contact inbox and a description saying whether the
   node is stable or a test node ([Configuration](../node/configuration.md#operator)).
2. Add it to `src/unseenet/nodes.json` with the project key as `operator`
   (by pull request, or the *Add my node* form). Until a project node is on
   the list, the tool does not know it.
3. On **every** project node, the new one included, update the checkout,
   run the tool with `--check`, add what it prints to `node.toml`, and
   restart: `sudo systemctl restart unseenet-node`.
4. Check the journal on the new node for `pulled ... from` lines, and that
   the next day's [health check](../node/operations.md#getting-your-node-listed)
   reports nothing.

## Peering with others

Anyone who asks to have a node listed can peer with the project's nodes -
the listing rules require a listed peer, and this way nobody is stuck.
When a request asks for it (the *Peers* field), add a `[[peer]]` for that
node on at least one project node, with the address and key from the
request, and tell the operator which node so they can add it back.
