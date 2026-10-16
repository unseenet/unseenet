---
hide:
  - navigation
  - toc
---

<div class="un-hero" markdown>

<div class="un-hero__head">
  <img class="un-hero__icon" src="img/icon.svg" alt="" width="64" height="64">
  <dl class="un-headers" aria-label="Article headers">
    <dt>From</dt><dd>the Unseenet project</dd>
    <dt>Newsgroups</dt><dd>unseenet</dd>
  </dl>
</div>

<h1 class="un-subject"><span class="un-subject__key">Subject:</span> Usenet, unseen.</h1>

<p class="un-lede">
A discussion network in the spirit of old Usenet and BBSes. Groups, threads
and chats on nodes that anyone can run, passed between them over Tor onion
services. You join with one program from a USB stick: no installation, no
account, nothing left behind.
</p>

<div class="un-actions">
  <a class="un-button un-button--primary" href="portable/">Get the portable client</a>
  <a class="un-button" href="node/install/">Run a node</a>
</div>

<p class="un-status">
<strong>Pre-alpha.</strong> The protocol may still change, test nodes may be
reset, and the code has not had a security review. Do not rely on it to
protect anyone yet.
</p>

</div>

<figure class="un-demo">
  <div class="un-term" data-cast="img/demo.cast" data-poster="npt:0:9.5">
    <noscript><img src="img/demo.gif" alt="The Unseenet terminal client: unlocking the vault, reading a thread, replying, chatting and browsing groups"></noscript>
  </div>
  <figcaption>
    The real client from a USB stick: unlock your vault, read a thread, reply,
    chat, find more groups. Recorded against a test node on one machine, so
    Tor starting up (10-30 seconds) is left out.
    <a href="portable/">Start it from a stick</a>
  </figcaption>
</figure>

<figure class="un-boot">
  <video class="un-video" src="img/boot.webm" poster="img/boot-poster.png"
         controls muted loop playsinline preload="none"
         aria-label="Booting the Unseenet stick in a virtual machine: the boot menu, the client, making a new vault and choosing a name"></video>
  <figcaption>
    <strong>Or boot from the stick.</strong> Unseenet then runs from memory and
    touches nothing on the computer's disks. Your vault is the same one either
    way. The video speeds up the waiting for the computer and stops where
    you pick a name, before Tor connects.
    <a href="bootable/">The bootable stick</a>
  </figcaption>
</figure>

## How it fits together

<div class="un-how" markdown>

<figure class="un-diagram" aria-labelledby="un-diagram-cap">
<svg viewBox="0 0 560 300" role="img" aria-labelledby="un-diagram-title">
  <title id="un-diagram-title">Your client talks to one node over Tor; the nodes pass posts between themselves, also over Tor.</title>
  <g class="d-tor">
    <path d="M150 150 C 205 150, 215 150, 268 150"/>
    <path d="M318 132 C 360 90, 380 80, 420 76"/>
    <path d="M318 168 C 360 210, 380 220, 420 224"/>
    <path d="M452 104 L 452 196"/>
  </g>
  <g class="d-box">
    <rect x="20" y="112" width="130" height="76" rx="10"/>
    <circle cx="293" cy="150" r="25"/>
    <circle cx="450" cy="76" r="25"/>
    <circle cx="450" cy="224" r="25"/>
  </g>
  <g class="d-label">
    <text x="85" y="144">your client</text>
    <text x="85" y="164" class="d-small">on a USB stick</text>
    <text x="293" y="155">A</text>
    <text x="450" y="81">B</text>
    <text x="450" y="229">C</text>
    <text x="293" y="200" class="d-small">a node</text>
    <text x="508" y="155" class="d-small">and on</text>
  </g>
  <g class="d-note">
    <text x="209" y="140">Tor</text>
    <text x="378" y="66">Tor</text>
    <text x="378" y="246">Tor</text>
  </g>
  <rect x="34" y="198" width="102" height="22" rx="4" class="d-vault"/>
  <text x="85" y="213" class="d-small d-vault-text">encrypted vault</text>
</svg>
<figcaption id="un-diagram-cap">One program on your side; nodes run by anyone, linked over Tor.</figcaption>
</figure>

<dl class="un-points">
  <dt>Nobody owns the network</dt>
  <dd>You connect to a node. Nodes replicate groups to each other, the way
  Usenet servers did, and anyone can run one.</dd>
  <dt>Nothing to find</dt>
  <dd>Every node is a Tor onion service: no public IP, no port forwarding,
  no DNS, and nobody needs to know where it is.</dd>
  <dt>Nothing to forge</dt>
  <dd>Every post is signed. Groups are owned by a key, and their settings
  are signed too.</dd>
  <dt>Nothing to read</dt>
  <dd>Closed groups and private messages are end-to-end encrypted. The
  nodes that carry them only ever see ciphertext.</dd>
  <dt>Spam costs something</dt>
  <dd>Every post carries a small proof-of-work, so flooding a group is
  slow and expensive.</dd>
</dl>

</div>

## Where to start

<div class="grid cards" markdown>

- **I want to read and post**  
  Unzip and start on Linux, macOS or Windows, or boot from a stick. Tor is included.  
  [:octicons-arrow-right-24: Portable](portable.md) &nbsp;
  [:octicons-arrow-right-24: Bootable](bootable.md)

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

## Talk about Unseenet - on Unseenet

| Group | For |
|-------|-----|
| `unseenet@ph5fc5hop5232qsz` | The project: protocol, software, ideas, questions |
| `unseenet.test@ph5fc5hop5232qsz` | Test posts - say hello, try replies |

Test node: `f6vnchi5p7ll4yn6yot6cz4ohzuxy3uhc3kztafuwn3zlyoup6tn64qd.onion`
