<p align="center">
  <img src="img/logo-light.svg#only-light" alt="Unseenet" width="420">
  <img src="img/logo-dark.svg#only-dark" alt="Unseenet" width="420">
</p>

**Usenet, unseen.** Unseenet is a decentralized, encrypted discussion
network in the spirit of old Usenet and BBSes: groups and chats you reach
by running one program, carried between independently run nodes over
Tor onion services.

!!! warning "Pre-alpha"
    Unseenet is in its design phase. The protocol may still change, the test
    nodes may be reset at any time, and the code has not had a security
    review. Do not rely on it to protect anyone yet.

## Where to start

<div class="grid cards" markdown>

- **I want to read and post**  
  Install the client, connect to a node and join a group.  
  [:octicons-arrow-right-24: Using the client](client.md)

- **I want to run a node**  
  One command on a Debian/Ubuntu box, a Raspberry Pi or a Proxmox LXC.  
  [:octicons-arrow-right-24: Installation](node/install.md)

- **I want to understand how it works**  
  Identities, group types, closed groups, postage.  
  [:octicons-arrow-right-24: Concepts](concepts.md)

- **I want to build something compatible**  
  The protocol is specified in the UN-RFC series.  
  [:octicons-arrow-right-24: Specification](spec/index.md)

</div>

## The idea in one picture

```
  you (USB stick)                 the network
  +-----------+     Tor     +--------+  Tor  +--------+
  | unseenet  | <---------> | node A | <---> | node B | <--->  ...
  |  client   |   ONNTP     +--------+       +--------+
  +-----------+                 ^                 ^
   encrypted vault              +---- node C -----+
```

- You connect to **a node**. Nodes **replicate** groups to each other, the
  way Usenet servers did. Nobody owns the network.
- Every node is a **Tor onion service**: no public IP, no port forwarding,
  no DNS, and nobody needs to know where it is.
- Every post is **signed**. Groups are **owned**, and their settings are
  signed too, so nothing can be forged.
- **Closed groups** are end-to-end encrypted. The nodes that carry them
  only ever see ciphertext.
- **Spam is priced, not policed**: every post carries a small proof-of-work.

## Talk about Unseenet - on Unseenet

| Group | For |
|-------|-----|
| `unseenet@ph5fc5hop5232qsz` | The project: protocol, software, ideas, questions |
| `unseenet.test@ph5fc5hop5232qsz` | Test posts - say hello, try replies |

Test node: `f6vnchi5p7ll4yn6yot6cz4ohzuxy3uhc3kztafuwn3zlyoup6tn64qd.onion`
