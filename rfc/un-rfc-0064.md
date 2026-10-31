```
Unseenet Working Group                                     A. Lorensen
UN-RFC: 0064                                              October 2026
Category: Standards Track
Status: Draft
Implemented: -
Updates: 0005, 0010, 0020, 0055

                Transport Addresses and Transport Bindings
```

# Abstract

Unseenet articles are signed and self-contained; nothing in them
depends on how they travelled. Only the connections between clients
and nodes, and between nodes, depend on Tor. This document gives node
addresses an explicit transport scheme (`onion:`), says what any
transport must provide before ONNTP may run over it, and lets a node
list more than one address. It defines no new transport. Tor onion
services remain the only transport, and the only one clients use by
default.

The purpose is to keep the door open: once nodes, lists and councils
are in use after 1.0, adding a scheme to every address would be a
breaking change. Done now, a later transport (for example I2P) needs
only its own binding document.

# 1. Terminology

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are to be read
as in RFC 2119.

Transport
: A network that carries a byte stream between a client or node and a
  node, such as Tor onion services.

Transport binding
: A UN-RFC that defines how ONNTP (UN-RFC 0005) runs over one
  transport, and the address syntax for it.

Transport address
: A string naming one node on one transport, in the form of section 2.

# 2. Transport Addresses

A transport address is:

```
transport-address = scheme ":" transport-part
scheme            = 1*16( %x61-7A / DIGIT / "-" )   ; lowercase
```

The `transport-part` is defined by the binding for that scheme.

A bare onion address (`<56 base32>.onion`, optionally `:port`), as used
before this document, is the same as that address with `onion:` in
front. Software MUST accept both forms and SHOULD write the `onion:`
form.

Software MUST ignore, without error, an address whose scheme it does
not know. Such an address is not "invalid"; it is only unusable here.

## 2.1 Schemes

| Scheme  | Status   | Binding                                            |
|---------|----------|----------------------------------------------------|
| `onion` | Defined  | UN-RFC 0005 section 1: `onion:<56 base32>.onion[:port]`, default port 119 |
| `test`  | Defined  | Section 2.2 of this document                       |
| `i2p`   | Reserved | For a possible I2P binding                         |
| `rns`   | Reserved | For a possible Reticulum binding                   |

New schemes are added by the binding document that defines them.
Reserved schemes MUST NOT be used until such a document exists.

## 2.2 The `test` Scheme

`test:<host>:<port>` names a node reached by plain TCP, for development
and test networks only (for example `test:127.0.0.1:1119`). It replaces
the remark in UN-RFC 0010 section 2 that non-onion addresses are
allowed for testing. Clients MUST NOT offer `test:` addresses to
ordinary users, and nodes MUST NOT peer over them unless the operator
has turned on a test setting.

# 3. What a Transport Must Provide

A transport binding MUST NOT be defined unless the transport gives
all of the following. Each binding MUST say how it meets them.

1. **A reliable, ordered byte stream** in both directions, so that ONNTP
   runs unchanged.
2. **Encryption** of that stream between the two ends.
3. **An authenticated endpoint.** Reaching an address MUST prove that
   one is talking to the holder of that address, as an onion address
   does. If the transport cannot do this itself, the binding MUST
   require the node to prove its `node_key` (UN-RFC 0016) before
   anything else is exchanged.
4. **Location hiding for the node.** Knowing the address MUST NOT
   reveal the node's IP address or physical location.
5. **A threat model section** saying, in the style of the guide's
   threat model, what the transport hides from whom and what it does
   not, including what a global passive observer can see.

A transport that lacks point 4 (for example a mesh network that is
encrypted but not anonymous) MAY still get a binding, but it MUST be
marked *non-hiding* in the table in section 2.1, and clients MUST NOT
use it unless the user has chosen it in a setting that says plainly
that the node's location is not hidden.

# 4. Node Entries with Several Addresses

UN-RFC 0010 section 2 is updated. A node entry keeps its `address`
field and gains one optional field:

| Field       | Type            | Req. | Meaning                                    |
|-------------|-----------------|------|--------------------------------------------|
| `address`   | string          | yes  | The node's main transport address (section 2) |
| `addresses` | array of string | no   | Further transport addresses for the same node, at most 8 |

All addresses in one entry MUST reach the same node, and, when the
entry has a `node_key`, the node MUST be able to prove that key on each
of them.

An entry is usable if at least one of its addresses has a scheme the
reader supports. A client MUST prefer `onion:` addresses unless the user
has chosen otherwise.

The `address` of an entry in a list kept by a council (UN-RFC 0054)
MUST be an `onion:` address while `onion` is the only defined
hiding transport.

# 5. Nodes on More Than One Transport

A node MAY be reachable on, and MAY peer over, more than one transport.
Such a node:

1. MUST forward articles it accepts to its peers on every transport,
   regardless of which transport they arrived on. Articles carry no
   record of the transport, as they carry no `Path` (UN-RFC 0005).
2. MUST apply the same forwarding delay on every transport.
3. MUST NOT be reachable on any transport other than `onion` unless the
   operator has turned that transport on. The default is `onion` only.

**Linking.** Listing two addresses in one entry tells everyone that
they are the same node. Even without that, a node on two transports can
be linked across them by uptime and timing. An operator who needs one
of the addresses to stay unlinked MUST run separate nodes, with
separate node keys, on separate machines. Clients and node software
SHOULD say this where the setting is turned on.

# 6. Changes to Other Documents

- **UN-RFC 0005.** The abstract and introduction say that ONNTP runs
  over a transport binding (this document). Section 1, "Transport",
  becomes "The onion binding" and defines the `onion:` scheme.
  Everything after section 1 applies to every binding.
- **UN-RFC 0010.** The `address` field takes a transport address
  (section 2); the `addresses` field is added (section 4); the remark
  about non-onion test addresses is replaced by the `test:` scheme.
- **UN-RFC 0055.** A node announcement's `address` is a transport
  address, and it may carry `addresses` (section 4).
- **UN-RFC 0020.** The node list kept by a council takes `address` and
  `addresses` from announcements; replicas measure the `onion:` address,
  and `test:` addresses are never listed.
- **UN-RFC 0001.** The sentence "Every node is a Tor onion service"
  stays true; a note says that other transports may be added by
  binding documents (this document).

# 7. Not Covered Here

- **Carrying articles offline** (exporting a signed batch on a USB stick
  and importing it on another node) needs no transport address and
  belongs in its own document.
- **Web entrances** (UN-RFC 0043) are reached over HTTPS by browsers and
  keep their own address form. An entrance reaches nodes through a
  transport like any client.

# 8. Security Considerations

Every new transport adds code, attack surface and a different anonymity
set, and should be reviewed as carefully as the onion binding. The
requirements in section 3 are a floor, not a promise that a transport
meeting them is as strong as Tor.

A client that silently fell back to a weaker transport would mislead
its user. Section 3 forbids non-hiding transports by default, and
section 4 makes `onion:` preferred; clients MUST also show which
transport a connection uses whenever it is not `onion`.

Ignoring unknown schemes (section 2) means an attacker who can publish
to a list can add addresses that some readers will never try. This
gives them nothing beyond what an unusable address gives today.

# 9. Implementation Notes (non-normative)

For now this needs only: parsing `onion:` and bare onion addresses as
the same thing, writing the `onion:` form, ignoring unknown schemes in
node lists, accepting `addresses`, and replacing the special test-address
handling with `test:`. No new transport code is required.
