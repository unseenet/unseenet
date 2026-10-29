"""Unseenet - Usenet-style discussion network over Tor onion services.

The protocol is specified in the UN-RFC series in the ``rfc/`` directory.
This package is one implementation of it; the UN-RFCs are the authority.
"""

# Software version: semantic versioning, see docs/development.md#versioning.
__version__ = "0.6.4"

# Wire protocol version (the Unseenet-Version header, UN-RFC 0002). It changes
# only through a new UN-RFC and is independent of the software version.
PROTOCOL_VERSION = "1"
