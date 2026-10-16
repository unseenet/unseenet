"""Nodes a new client can start with, so nobody has to know an address first.

This is a starting point, like the bootstrap list of any network. It is not
a directory: anyone can run a node, and a client can use any node it is told
about (an ``unseenet:join`` link names one). A signed, updatable list is the
subject of a future UN-RFC (0010, node discovery).

Each entry gives the node key (UN-RFC 0016) as well, so that a client can check
it reached the node the list means.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnownNode:
    name: str
    address: str
    description: str
    node_key: str


KNOWN_NODES: tuple[KnownNode, ...] = (
    KnownNode("unseenet-node1",
              "f6vnchi5p7ll4yn6yot6cz4ohzuxy3uhc3kztafuwn3zlyoup6tn64qd.onion",
              "Project test node 1, Denmark - pre-alpha, may be reset",
              "ed25519:gh7y6uk2fe2zlzvai5qriq7m6jsgk57aoi3jfkhookv7v4pd7hka"),
    KnownNode("unseenet-node2",
              "ze4aqpjfyteij4tqaaztyujoj7wsjgbv4cliexljckdfp5eomkshfead.onion",
              "Project test node 2, Denmark - pre-alpha, may be reset",
              "ed25519:bulo5resazfbqmewywp7djguxghmbixpiwr6fert4xgt4ymbqu4a"),
)
