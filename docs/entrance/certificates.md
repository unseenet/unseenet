# Certificates

A browser on the open web will only use an entrance safely over HTTPS (a page
served over plain HTTP works, but anyone on the way can read and change it).
That means a certificate. These are the ways to get one, without paying and
without handing TLS to someone else.

## The default: a certificate for the IP address

`install.sh` does this unless told otherwise. Let's Encrypt issues
certificates for bare IP addresses, so an entrance needs no domain at all:

1. it finds the machine's public IP address (or takes `ENTRANCE_PUBLIC_IP`);
2. the entrance answers Let's Encrypt's challenge on port 80;
3. certbot (5.6 or newer, installed in `/opt/certbot`) gets a 6-day
   certificate with the `shortlived` profile, without an e-mail address;
4. a timer renews it twice a day when it has less than two days left (about
   twice a week), and the entrance loads the new one without restarting.

Visitors then open `https://203.0.113.7/`. Ports 80 and 443 must be open to
the internet. If they are not, the script says so and runs plain HTTP on port
8043 until you run it again. On a machine whose own firewall rejects them
(Oracle Cloud's images do), the script opens them.

At home the IP address may change. The next renewal then fails; run the
script again, or use a dynamic DNS name (below).

## A domain name

Point the name straight at the machine, then
`sudo TLS=domain:entrance.example.org sh install.sh` does it with certbot.
`TLS=both:entrance.example.org` gets one certificate for the name and the IP
address: the name is the one to share, and it sends visitors on to the
address, so the app and a vault kept on the device live at one place that
still works when the name is blocked.

Or by hand, with Caddy in front of a plain (`TLS=none`) entrance:

```
entrance.example.org {
    reverse_proxy 127.0.0.1:8043
    log {
        output discard
    }
}
```

Set `ENTRANCE_TRUST_FORWARDED=1` in `/etc/unseenet-entrance.env` so limits are
counted per visitor, not per proxy.

## A free dynamic DNS name

No domain? A free dynamic DNS service (for example deSEC or DuckDNS) gives you
a name that follows a changing home IP, and Let's Encrypt issues certificates
for it like for any other name. This is the easy way for an entrance at home.

## No certificate: the onion address and the client in a file

Every entrance also has an onion address. Tor Browser users need no
certificate at all, and are hidden from the entrance too.

The client in a file (`unseenet-web.html`, UN-RFC 0043 section 8.7) is opened
from disk, so no page is served; it then needs only the WebSocket. Plain
`ws://` works from a file, but then the visitor's network can see which
groups they read (never their keys: those never leave the browser), so
`wss://` is still better.

## Not: a CDN or a proxying tunnel

Cloudflare's proxy and tunnels end TLS on Cloudflare's machines, which then
see every visitor's address and everything they read. UN-RFC 0043 section 5
forbids it for a real entrance. It is fine for a quick test with test
identities, and nothing else.
