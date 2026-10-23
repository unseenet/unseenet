"""Authenticating peers: AUTHINFO and node keys (XUN-PEER, UN-RFC 0016).

Part of ``Session`` (see __init__.py)."""

from __future__ import annotations

from . import *  # noqa: F403  - the module's names, as when this was one file
from .. import server as _s   # names tests patch on the module, read at call time


class AuthCommands:
    async def cmd_authinfo(self, args):
        if len(args) < 2:
            self.send("501 syntax")
        elif args[0].upper() == "USER":
            self._user = args[1]
            self.send("381 password required")
        elif args[0].upper() == "PASS" and self._user:
            for peer in self.node.config.peers:
                if (peer.name == self._user and peer.password
                        and hmac.compare_digest(peer.password.encode(), args[1].encode())):
                    self.peer = peer.name
                    self.node.stats.peer_authenticated()
                    self.send("281 authentication accepted")
                    return
            await self._auth_failed()
        else:
            self.send("482 authentication commands issued out of sequence")

    # --- peer authentication with node keys (UN-RFC 0016) ---
    async def cmd_xun_peer(self, args):
        """XUN-PEER <key>: a node claims a key; we answer with ours and a challenge."""
        if len(args) != 1:
            self.send("501 syntax: XUN-PEER <node key>")
            return
        try:
            claimed = crypto.key_from_text(args[0])
        except crypto.CryptoError:
            self.send("501 malformed key")
            return
        nonce = os.urandom(32)
        self._challenge = (claimed, nonce)
        # The same answer whether or not the key is a configured peer: no probing.
        self.send(f"383 {self.node.key.key_text} {crypto.b64(nonce)}")

    async def cmd_xun_peer_proof(self, args):
        """XUN-PEER-PROOF <signature> over nonce || our key || its key."""
        if self._challenge is None:
            self.send("482 XUN-PEER first")
            return
        claimed, nonce = self._challenge
        self._challenge = None                      # one attempt per challenge
        if len(args) != 1:
            self.send("501 syntax: XUN-PEER-PROOF <signature>")
            return
        peer = next((p for p in self.node.config.peers
                     if p.key and p.public_key() == claimed), None)
        try:
            sig = crypto.sig_from_text(args[0])
        except crypto.CryptoError:
            sig = b""
        message = nonce + self.node.key.public_key + claimed
        if peer is not None and sig and crypto.verify(claimed, crypto.PURPOSE_PEER_AUTH,
                                                       message, sig):
            self.peer = peer.name
            self.node.stats.peer_authenticated()
            self.send("281 peer authenticated")
            log.info("peer %s authenticated by key", peer.name)
            return
        await self._auth_failed()

    async def _auth_failed(self) -> None:
        self._auth_failures += 1
        await asyncio.sleep(min(self._auth_failures, 5))     # slow down guessing
        self.send("481 authentication failed")
        if self._auth_failures >= 3:
            await self.writer.drain()
            raise ConnectionError("too many failed authentications")
