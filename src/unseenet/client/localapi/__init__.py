"""The local client API (UN-RFC 0046): how a front end uses a client runtime.

``LocalAPI`` is what it does; ``server`` puts it on 127.0.0.1 over HTTP and a
WebSocket (needs aiohttp, ``pip install unseenet[api]``).
"""

from .api import API_VERSION, LocalAPI, Locked, NotFound

__all__ = ["API_VERSION", "LocalAPI", "Locked", "NotFound"]
