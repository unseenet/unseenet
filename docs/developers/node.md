# Node reference

The node (`unseenet.node.server`) takes articles from clients and peers,
keeps them in its store (`unseenet.core.store`) and passes them on. This page
is for reading its code or writing a compatible node: what each part does,
generated from the docstrings. The rules themselves are in the UN-RFCs, above
all [UN-RFC 0005](../spec/un-rfc-0005.md) (ONNTP) and the documents each part
names.

To run a node, see [Running a node](../node/install.md).

## Node: taking and keeping articles

`Node` is one class written in parts. `accepting.py` decides the order of the
checks; each kind of article has its own part.

### The node

::: unseenet.node.server.node
    options:
      show_root_heading: false
      heading_level: 4

### The accept pipeline

::: unseenet.node.server.accepting
    options:
      show_root_heading: false
      heading_level: 4

### Blobs

::: unseenet.node.server.blobs
    options:
      show_root_heading: false
      heading_level: 4

## Session: one connection

Every command is a `cmd_<name>` method, in the part of its area.

### The command loop

::: unseenet.node.server.connection
    options:
      show_root_heading: false
      heading_level: 4

### Authenticating peers

::: unseenet.node.server.auth_commands
    options:
      show_root_heading: false
      heading_level: 4

### Lists and push

::: unseenet.node.server.lists_commands
    options:
      show_root_heading: false
      heading_level: 4

### Reading

::: unseenet.node.server.reading_commands
    options:
      show_root_heading: false
      heading_level: 4

### Peers and catching up

::: unseenet.node.server.peering_commands
    options:
      show_root_heading: false
      heading_level: 4

### Posting

::: unseenet.node.server.posting_commands
    options:
      show_root_heading: false
      heading_level: 4

## The store

`Store` (`unseenet.core.store`) is the node's SQLite database, written in parts
by area; the schema is in its `__init__.py`.

### Articles

::: unseenet.core.store.articles
    options:
      show_root_heading: false
      heading_level: 4

### The history

::: unseenet.core.store.base
    options:
      show_root_heading: false
      heading_level: 4

### Groups

::: unseenet.core.store.groups
    options:
      show_root_heading: false
      heading_level: 4

### Kept articles

::: unseenet.core.store.kept
    options:
      show_root_heading: false
      heading_level: 4

### Blobs in the store

::: unseenet.core.store.blobs
    options:
      show_root_heading: false
      heading_level: 4

### Cancels and edits

::: unseenet.core.store.withdrawals
    options:
      show_root_heading: false
      heading_level: 4

### Peer queues and pull state

::: unseenet.core.store.peers
    options:
      show_root_heading: false
      heading_level: 4

### Key-bound groups

::: unseenet.core.store.keybound
    options:
      show_root_heading: false
      heading_level: 4

### Numbers for the operator

::: unseenet.core.store.stats
    options:
      show_root_heading: false
      heading_level: 4
