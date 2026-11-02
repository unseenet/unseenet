# UN-RFC Audit Follow-up — Core Protocol Review

**Status:** Preliminary static review; no tests were executed in this session. This supplements [`initial-rfc-conformance-review.md`](initial-rfc-conformance-review.md), not a final conformance claim.

**Source snapshot reviewed:** `unseenet/unseenet` commit [`0cba7cd8daebc13902b9cd4229155314c6d7e736`](https://github.com/unseenet/unseenet/tree/0cba7cd8daebc13902b9cd4229155314c6d7e736). Findings must be rechecked if the branch changes.

## Additional candidate: UN-RFC 0002 §1 header-value control characters

**Assessment: likely validation gap; confirm with a minimal test before treating as a confirmed defect.**

UN-RFC 0002 §1 forbids CR, LF and NUL in header values. `Article.set()` rejects these characters, but `Article.from_bytes()` constructs parsed header tuples directly and checks only the header name after splitting the line. It does not apply the same value-character check to untrusted wire input. A lone CR or NUL embedded in a header value may therefore survive parsing and proceed to signature validation. A valid article can be signed over that canonical value by an independent implementation; the node then invokes `Article.from_bytes()` followed by `validate_structure()` in its acceptance path.

- Parser and setter: [`src/unseenet/core/article.py`](https://github.com/unseenet/unseenet/blob/0cba7cd8daebc13902b9cd4229155314c6d7e736/src/unseenet/core/article.py#L86-L96), [`Article.from_bytes()`](https://github.com/unseenet/unseenet/blob/0cba7cd8daebc13902b9cd4229155314c6d7e736/src/unseenet/core/article.py#L125-L152)
- Node calls the parser then structural validation: [`src/unseenet/node/server/accepting.py`](https://github.com/unseenet/unseenet/blob/0cba7cd8daebc13902b9cd4229155314c6d7e736/src/unseenet/node/server/accepting.py#L167-L171)
- RFC requirement: [UN-RFC 0002 §1](https://github.com/unseenet/unseenet/blob/0cba7cd8daebc13902b9cd4229155314c6d7e736/rfc/un-rfc-0002.md#L17-L30)

**Suggested verification:** Add parser tests for NUL and bare CR in header values, and an end-to-end node acceptance test using an article signed over the parsed canonical form. Ensure ordinary CRLF line endings remain accepted. If reproduced, reject these characters during raw parsing and retain regression tests.

## Review notes: selected UN-RFC 0002–0006 behavior

| Area | Source/test evidence | Preliminary assessment |
|---|---|---|
| Article canonical form, signature, Message-ID | `core/article.py`; `tests/test_protocol.py` round-trip, tampering, duplicate-header and order tests | Core path present; raw header control-character check above needs testing. Date UTC and `From`/`Subject` lengths remain candidates from the initial report. |
| Ed25519, domain separation, sealed boxes, AEAD | `core/crypto.py`; `core/groups.py`; protocol tests include group encryption round trip | Implementation uses the specified primitives. This is not a cryptographic review or full vector audit. |
| Manifest ownership, permissions, closed-group epochs and cancels | `core/groups.py`; `node/server/manifests.py`; `node/server/controls.py`; `tests/test_protocol.py`, `tests/test_node.py` | Core invariants have direct checks and basic tests. Exhaustive malformed-manifest and epoch edge cases remain unreviewed. |
| ONNTP reader/peering commands and capabilities | `node/server/connection.py`, `reading_commands.py`, `posting_commands.py`, `peering_commands.py`; `tests/test_node.py` | Main required paths are present. Full RFC 3977/4644 error semantics and all command-state edge cases have not been checked. |
| Postage | `core/pow.py`; `node/server/postage.py`; `node/server/accepting.py`; `tests/test_node.py` | The hash construction and required-difficulty path appear aligned at a high level. Peer-specific minimum forwarding behavior and all proof encodings still need an explicit requirement audit. |
| Tor transport | `core/tor.py`; `tests/test_transport.py`, `tests/test_tor_config.py`, `tests/test_torconnect.py` | Remote `.onion` resolution through SOCKS and local test-transport paths are present. These tests are local stubs, not a review of production Tor behavior. |

## Verification limits and next actions

1. Run targeted local tests for the four candidates: `From`/`Subject` limits, non-UTC `Date`, `Origin-Date` versus rounded article `Date`, and CR/NUL header values.
2. Record actual test outcomes and distinguish rejected input from accepted input; do not convert static suspicions into confirmed findings without that evidence.
3. Continue the normative matrix through the remainder of UN-RFC 0002–0006 and then the later RFCs, including relevant client and service repositories.
4. Review privacy/anonymity requirements separately, including logging, Tor resolution, metadata exposure, and key/address linking.

The GitHub code-search result sets used during discovery may be incomplete. The audit should rely on direct RFC and source inspection for each item, not search results alone.
