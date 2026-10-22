# In your browser (also on phones and tablets)

The [graphical client](graphical.md) also runs in an ordinary browser - on a
phone, a tablet or any computer - with nothing to install. You open a **web
entrance** ([UN-RFC 0043](spec/un-rfc-0043.md)), for example the project's
own:

<p style="font-size:1.25em"><strong><a href="https://entrance.unseenet.net/">entrance.unseenet.net</a></strong></p>

It is the less hidden way in, on purpose: for people who will not install
anything. Read [What you give up](#what-you-give-up) before you rely on it.

!!! warning "Pre-alpha"
    Neither the web entrance nor the Unseenet core has had a security review.
    Play with it; do not rely on it to protect anyone yet.

!!! note "Reading, not posting yet"
    Nodes from Unseenet 0.4 take posts only from keys that have
    [ripened](spec/un-rfc-0025.md) - a few minutes of work, once per key. The
    browser cannot do that work yet (unseenet-gui#31), so in a browser you can
    read everything but not post on those nodes. The portable and bootable
    clients post as usual.

## What it is

It is the same graphical client as the portable and the bootable one - the
same groups, keys and vault - with its whole program, the Unseenet core
included, running **in your browser**. Your keys stay there: the page signs
your posts, checks everyone's signatures and pays the postage itself. The
entrance only carries the connection to a node, over Tor, and can neither
read nor change what goes through.

A bar at the top always says that you are on the open web.

## First visit

1. Open the entrance. The first time, the page loads about 15 MB - Python and
   the Unseenet core - and keeps it on the device.
2. Create a vault - a name and a passphrase - just as in the other clients,
   or open a vault file you already have (**Open vault file**). A vault from a
   stick or a portable folder works here too, and the other way round.
3. Decide where the vault lives:
   - **Keep on this device**: the browser keeps it, still encrypted with your
     passphrase, and saves every change by itself. Next time the page opens
     straight to your passphrase.
   - Or **Save vault file** at the end of every session, and open it next time.
     Without either, the vault is gone when you close the tab.

A long passphrase matters more here: whoever gets hold of the device can try
passphrases against a vault kept on it.

## As an app on a phone or tablet

Add the page to your home screen, and it starts like an app, from the
device, and finds your vault at once:

| | |
|---|---|
| **iPhone, iPad** (Safari) | Share → *Add to Home Screen* |
| **Android** (Chrome) | ⋮ → *Install app* or *Add to home screen* |
| **A computer** (Chrome, Edge) | the install icon in the address bar |

On a narrow screen the client shows one thing at a time: your groups, then a
group, then a post or the chat. **⋯** holds what does not fit, and when you
write, *Post* or *Send* is at the top, above the keyboard.

## When the entrance is gone or blocked

- **The app keeps working.** It runs from the device, and when its entrance
  does not answer it talks through another one from the project's signed list
  of entrances.
- **The list of entrances as a file.** *Other entrances* in the bar saves a
  small page with the signed list inside. Opened from disk, it shows which
  entrances answer and opens one. Keep it, and send it to friends.
- **In Tor Browser**, use the entrance's onion address (the project's:
  `qtxtye5sz4reskzdvnf3ih5oqyfvs5e22o3kcny3q3iy4bhr3ni437ad.onion`): then the
  entrance does not see your IP address either, and it cannot be blocked like
  an address on the open web.

## New versions

When there is a newer version, the bar shows **New version**. It is
installed only when you say so, and only after every file has been checked
against a signature from the Unseenet project - wherever the files came from.
The app never goes back to an older version, and warns if the entrance
serves something that is not signed.

## What you give up

| | Portable / Bootable | On the web |
|---|---|---|
| Groups and nodes can be removed by someone | No | No |
| Others can delete or change your posts | No | No |
| Nodes learn your IP address | No | No |
| The entrance learns your IP address | - | **Yes** (not in Tor Browser) |
| You trust code you did not install yourself | Once, signed | Signed versions - but the entrance serves part of the app |
| Someone can see that you use Unseenet | Hard | Your network sees you visit the entrance |

If you need to hide that you use Unseenet, or who you are, use the
[portable](portable.md) or [bootable](bootable.md) client instead.

## Run an entrance

Every entrance someone else runs makes Unseenet harder to block. An entrance
runs on a small cloud machine - a free one is enough - and installs with one
command; it can also mirror Unseenet's releases, so that the other clients
can update over Tor when GitHub is blocked. See
[Running an entrance](entrance/index.md).
