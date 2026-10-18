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
<!-- unseenet:versions -->
  </dl>
</div>

<h1 class="un-subject"><span class="un-subject__key">Subject:</span> Usenet, unseen.</h1>

<p class="un-lede">
Chat, real threaded discussion and private posts - in one network and one
program, in the spirit of Usenet and the BBSes, but with nobody owning the
network and nobody able to see who you are. The groups live on nodes that anyone can run, passed
between them over Tor onion services. You join with one program from a USB
stick: no installation, no account, nothing left behind.
</p>

<div class="un-actions">
  <a class="un-button un-button--primary" href="portable/">Portable (Linux, macOS, Windows)</a>
  <a class="un-button" href="bootable/">Bootable (USB, SSD etc.)</a>
  <a class="un-button" href="node/install/">Run a node</a>
</div>

<p class="un-status">
<strong>Pre-alpha.</strong> The protocol may still change, test nodes may be
reset, and the code has not had a security review. Do not rely on it to
protect anyone yet.
</p>

</div>

<div class="un-recordings">

<figure class="un-rec" id="see-portable">
  <div class="un-rec__head">
    <h2 class="un-rec__title"><a href="portable/">Portable (Linux, macOS, Windows)</a></h2>
    <button type="button" class="un-rec__size" aria-expanded="false" hidden>Larger</button>
  </div>
  <div class="un-term" data-cast="img/demo.cast" data-poster="npt:0:9.5">
    <noscript><img src="img/demo.gif" alt="The Unseenet terminal client: unlocking the vault, reading a thread, replying, chatting and browsing groups"></noscript>
  </div>
  <figcaption>
    Unzip and start, on a computer or from a USB stick. Unlock your vault, read
    a thread, reply, chat, find more groups. Recorded against a test node, so
    Tor starting (10-30 seconds) is left out.
  </figcaption>
</figure>

<figure class="un-rec" id="see-bootable">
  <div class="un-rec__head">
    <h2 class="un-rec__title"><a href="bootable/">Bootable (USB, SSD etc.)</a></h2>
    <button type="button" class="un-rec__size" aria-expanded="false" hidden>Larger</button>
  </div>
  <div class="un-media">
    <video class="un-video" src="img/boot.webm" poster="img/boot-poster.png"
           controls muted loop playsinline preload="none"
           aria-label="Booting the Unseenet stick in a virtual machine: the boot menu, the client, making a new vault and choosing a name"></video>
  </div>
  <figcaption>
    Boot from it and Unseenet runs from memory, touching nothing on the
    computer's disks. Same vault as the portable. The waiting is sped up, and
    the video stops where you pick a name, before Tor connects.
  </figcaption>
</figure>

</div>

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
  <dt>Chat and discussion, side by side</dt>
  <dd>Chat groups for quick talk, discussion groups with real threads and
  quoting, and private chats and posts - all in the same program.</dd>
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
  <dd>Closed groups, private chats and private posts are end-to-end encrypted. The
  nodes that carry them only ever see ciphertext.</dd>
  <dt>Spam costs something</dt>
  <dd>Every post carries a small proof-of-work, so flooding a group is
  slow and expensive.</dd>
</dl>

</div>

## How is it different? { #how-is-it-different }

<div class="un-cmp" markdown>

<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <symbol id="un-i-yes" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="currentColor"/><path d="M7 12.5l3.2 3.2L17.2 8.6" fill="none" stroke="#10302a" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></symbol>
  <symbol id="un-i-part" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 2a10 10 0 0 1 0 20z" fill="currentColor"/></symbol>
  <symbol id="un-i-no" viewBox="0 0 24 24"><path d="M8 12h8" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></symbol>
</svg>

<p class="un-cmp__kicker">Chat. Discussion. Private posts.</p>
<p class="un-cmp__headline">Everything in one place - <span>and nobody can see you there.</span></p>
<p class="un-cmp__lede">Other networks each do a few things well. Unseenet is the only one
that does all of it, in one program, without an account, over Tor.</p>

<div class="un-cmp__scroll">
<table class="un-cmp__table">
  <thead><tr><th scope="col" class="un-cmp__feat"><span class="un-sr">Feature</span></th><th scope="col" class="un-cmp__us"><span class="un-cmp__badge">Does it all</span><img src="img/icon.svg" alt="" width="34" height="34"><span class="un-cmp__name">Unseenet</span></th><th scope="col"><span class="un-cmp__mono" aria-hidden="true">D</span><span class="un-cmp__name">Discord</span></th><th scope="col"><span class="un-cmp__mono" aria-hidden="true">M</span><span class="un-cmp__name">Matrix</span></th><th scope="col"><span class="un-cmp__mono" aria-hidden="true">N</span><span class="un-cmp__name">Nostr</span></th><th scope="col"><span class="un-cmp__mono" aria-hidden="true">R</span><span class="un-cmp__name">Reddit &amp; forums</span></th><th scope="col"><span class="un-cmp__mono" aria-hidden="true">U</span><span class="un-cmp__name">Old Usenet</span></th></tr></thead>
  <tbody>
<tr><th scope="row"><span class="un-cmp__t">Chat</span><span class="un-cmp__sub">Quick talk in chat groups</span></th><td class="y"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-yes"/></svg><span class="un-sr">Yes</span></td><td class="y"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-yes"/></svg><span class="un-sr">Yes</span></td><td class="y"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-yes"/></svg><span class="un-sr">Yes</span></td><td class="y"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-yes"/></svg><span class="un-sr">Yes</span></td><td class="p"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-part"/></svg><span class="un-sr">Partly</span></td><td class="n"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-no"/></svg><span class="un-sr">No</span></td></tr>
<tr><th scope="row"><span class="un-cmp__t">Threaded discussion</span><span class="un-cmp__sub">Threads you can follow, replies that quote</span></th><td class="y"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-yes"/></svg><span class="un-sr">Yes</span></td><td class="p"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-part"/></svg><span class="un-sr">Partly</span></td><td class="p"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-part"/></svg><span class="un-sr">Partly</span></td><td class="p"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-part"/></svg><span class="un-sr">Partly</span></td><td class="y"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-yes"/></svg><span class="un-sr">Yes</span></td><td class="y"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-yes"/></svg><span class="un-sr">Yes</span></td></tr>
<tr><th scope="row"><span class="un-cmp__t">Private talk nobody else can read</span><span class="un-cmp__sub">End-to-end encrypted chats and posts</span></th><td class="y"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-yes"/></svg><span class="un-sr">Yes</span></td><td class="n"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-no"/></svg><span class="un-sr">No</span></td><td class="y"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-yes"/></svg><span class="un-sr">Yes</span></td><td class="p"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-part"/></svg><span class="un-sr">Partly</span></td><td class="n"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-no"/></svg><span class="un-sr">No</span></td><td class="n"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-no"/></svg><span class="un-sr">No</span></td></tr>
<tr><th scope="row"><span class="un-cmp__t">No account, email or phone number</span><span class="un-cmp__sub">You are your key</span></th><td class="y"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-yes"/></svg><span class="un-sr">Yes</span></td><td class="n"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-no"/></svg><span class="un-sr">No</span></td><td class="n"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-no"/></svg><span class="un-sr">No</span></td><td class="y"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-yes"/></svg><span class="un-sr">Yes</span></td><td class="n"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-no"/></svg><span class="un-sr">No</span></td><td class="p"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-part"/></svg><span class="un-sr">Partly</span></td></tr>
<tr><th scope="row"><span class="un-cmp__t">Nobody owns the network</span><span class="un-cmp__sub">No company to close it or sell it</span></th><td class="y"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-yes"/></svg><span class="un-sr">Yes</span></td><td class="n"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-no"/></svg><span class="un-sr">No</span></td><td class="y"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-yes"/></svg><span class="un-sr">Yes</span></td><td class="y"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-yes"/></svg><span class="un-sr">Yes</span></td><td class="n"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-no"/></svg><span class="un-sr">No</span></td><td class="y"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-yes"/></svg><span class="un-sr">Yes</span></td></tr>
<tr><th scope="row"><span class="un-cmp__t">Servers nobody can find</span><span class="un-cmp__sub">Nodes are onion services with no location</span></th><td class="y"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-yes"/></svg><span class="un-sr">Yes</span></td><td class="n"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-no"/></svg><span class="un-sr">No</span></td><td class="n"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-no"/></svg><span class="un-sr">No</span></td><td class="n"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-no"/></svg><span class="un-sr">No</span></td><td class="n"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-no"/></svg><span class="un-sr">No</span></td><td class="n"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-no"/></svg><span class="un-sr">No</span></td></tr>
<tr><th scope="row"><span class="un-cmp__t">Always over Tor</span><span class="un-cmp__sub">Nobody sees who talks to whom</span></th><td class="y"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-yes"/></svg><span class="un-sr">Yes</span></td><td class="n"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-no"/></svg><span class="un-sr">No</span></td><td class="n"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-no"/></svg><span class="un-sr">No</span></td><td class="n"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-no"/></svg><span class="un-sr">No</span></td><td class="n"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-no"/></svg><span class="un-sr">No</span></td><td class="n"><svg class="un-ic" width="20" height="20" aria-hidden="true"><use href="#un-i-no"/></svg><span class="un-sr">No</span></td></tr>
  </tbody>
  <tfoot><tr><th scope="row"><span class="un-cmp__t">Score</span></th><td class="un-cmp__win"><strong>7</strong>/7</td><td class=""><strong>1</strong>/7</td><td class=""><strong>3</strong>/7</td><td class=""><strong>3</strong>/7</td><td class=""><strong>1</strong>/7</td><td class=""><strong>2</strong>/7</td></tr></tfoot>
</table>
</div>

<p class="un-cmp__legend"><span><svg class="un-ic y" width="16" height="16" aria-hidden="true"><use href="#un-i-yes"/></svg> Yes</span>
<span><svg class="un-ic p" width="16" height="16" aria-hidden="true"><use href="#un-i-part"/></svg> Partly - there in some form, not the way Unseenet does it</span>
<span><svg class="un-ic n" width="16" height="16" aria-hidden="true"><use href="#un-i-no"/></svg> No</span></p>

<div class="un-cmp__cta">
  <a class="un-button un-button--primary" href="portable/">Try it now</a>
  <a class="un-button" href="why/">Why Unseenet - and what it costs</a>
</div>

</div>

## Where to start

Pick what you want to do. Each path lists the pages in the order to read them.

<div class="un-paths">

<section class="un-path">
  <h3 class="un-path__title">Read and post</h3>
  <p class="un-path__lede">Get Unseenet running and join the conversation. Tor is included.</p>
  <ol class="un-path__steps">
    <li><a href="portable/">Portable (Linux, macOS, Windows)</a> <span class="un-or">or</span> <a href="bootable/">Bootable (USB, SSD etc.)</a></li>
    <li><a href="client/#first-start">First start</a>: your vault, a name, a node</li>
    <li><a href="client/">Using the client</a>: groups, chat, discussion, private posts</li>
    <li><a href="updating/">Updating</a></li>
  </ol>
  <p class="un-path__more">Also: <a href="other-clients/">other newsreaders</a> · <a href="tor/">Tor and Tails</a></p>
</section>

<section class="un-path">
  <h3 class="un-path__title">Run a node</h3>
  <p class="un-path__lede">Carry groups for others. A Pi, a VM or an LXC is enough; no port forwarding.</p>
  <ol class="un-path__steps">
    <li><a href="node/responsibility/">Your responsibility</a>: read this first</li>
    <li><a href="node/install/">Installation</a> <span class="un-or">or</span> <a href="node/docker/">Docker</a></li>
    <li><a href="node/configuration/">Configuration</a></li>
    <li><a href="node/peering/">Peering</a> with other nodes</li>
    <li><a href="node/operations/">Operations</a> and the <a href="node/monitor/">monitor</a></li>
  </ol>
</section>

<section class="un-path">
  <h3 class="un-path__title">Understand how it works</h3>
  <p class="un-path__lede">What the network promises, and what it does not.</p>
  <ol class="un-path__steps">
    <li><a href="concepts/">Concepts</a>: nodes, identities, names, groups, postage</li>
    <li><a href="tor/">Tor and Tails</a></li>
    <li><a href="project/keys/">The project's keys</a> and <a href="project/nodes/">nodes</a></li>
    <li><a href="spec/un-rfc-0001/">UN-RFC 0001: Architecture</a></li>
  </ol>
</section>

<section class="un-path">
  <h3 class="un-path__title">Build something compatible</h3>
  <p class="un-path__lede">A node, a client or a tool of your own, from the specification.</p>
  <ol class="un-path__steps">
    <li><a href="spec/">The UN-RFC series</a> and <a href="spec/un-rfc-0000/">how it changes</a></li>
    <li><a href="spec/un-rfc-0002/">Article format</a> and <a href="spec/un-rfc-0003/">identities and crypto</a></li>
    <li><a href="spec/un-rfc-0005/">ONNTP transport</a> and <a href="spec/un-rfc-0006/">postage</a></li>
    <li><a href="development/">Development</a>: the reference code and its decisions</li>
  </ol>
</section>

</div>

<section class="un-talk" aria-labelledby="talk">
  <h2 id="talk" class="un-talk__title"><span class="un-talk__key">Followup-To:</span> Talk about Unseenet, on Unseenet</h2>
  <p class="un-talk__lede">Questions, ideas and test posts go here. Add the groups in the client
  (<kbd>g</kbd> Groups), or <a href="client/">see how</a>.</p>
  <ul class="un-groups">
    <li>
      <code class="un-groups__name">unseenet@ph5fc5hop5232qsz</code>
      <span class="un-groups__for">The project: protocol, software, ideas, questions</span>
      <button type="button" class="un-copy" data-copy="unseenet@ph5fc5hop5232qsz" hidden>Copy</button>
    </li>
    <li>
      <code class="un-groups__name">unseenet.help@ph5fc5hop5232qsz</code>
      <span class="un-groups__for">Help: ask anything about using Unseenet</span>
      <button type="button" class="un-copy" data-copy="unseenet.help@ph5fc5hop5232qsz" hidden>Copy</button>
    </li>
    <li>
      <code class="un-groups__name">unseenet.test@ph5fc5hop5232qsz</code>
      <span class="un-groups__for">Test posts: say hello, try replies</span>
      <button type="button" class="un-copy" data-copy="unseenet.test@ph5fc5hop5232qsz" hidden>Copy</button>
    </li>
  </ul>
  <p class="un-talk__node"><span class="un-talk__key">Test node:</span>
    <code>f6vnchi5p7ll4yn6yot6cz4ohzuxy3uhc3kztafuwn3zlyoup6tn64qd.onion</code>
    <button type="button" class="un-copy" data-copy="f6vnchi5p7ll4yn6yot6cz4ohzuxy3uhc3kztafuwn3zlyoup6tn64qd.onion" hidden>Copy</button>
  </p>
</section>
