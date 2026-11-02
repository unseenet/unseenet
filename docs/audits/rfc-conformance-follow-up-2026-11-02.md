# UN-RFC Implementation Conformance Audit — Initial Results

**Status:** Preliminary static audit; not a complete conformance assessment or security review.  
**Primary issue:** [unseenet/unseenet#907](https://github.com/unseenet/unseenet/issues/907)  
**Reviewed snapshots:** [`unseenet/unseenet` at `0cba7cd8daebc13902b9cd4229155314c6d7e736`](https://github.com/unseenet/unseenet/tree/0cba7cd8daebc13902b9cd4229155314c6d7e736); [`unseenet-import` at `2f9c942f5659b8021cea63c64263be48cc61f5fd`](https://github.com/unseenet/unseenet-import/tree/2f9c942f5659b8021cea63c64263be48cc61f5fd).  
**Method and limits:** Manual comparison of selected normative RFC requirements against source and existing tests. No test suite was executed in this review. A source-level observation is not a reproduced test failure. No independent implementation or interoperability testing was performed.

## Executive summary

The reviewed core paths are organized consistently with the RFC architecture: article and cryptographic primitives are in the core; the node applies article, group, postage and retention policy; clients share a session/core implementation; and import behavior uses the shared posting path. Existing tests exercise important happy paths and selected rejection cases.

The review has identified **four high-confidence source-level validation gaps** in the inspected article/origin paths. These should be converted into regression tests and confirmed on a runnable checkout before being called reproduced failures. None requires a change to protocol semantics: the RFCs already state the relevant requirements.

This report covers a selected slice, not all requirements in the first RFC series. In particular, it does not conclude that all other RFCs, all clients/services or their security properties conform.

## Findings to validate

### F-01 — Parsed article headers do not enforce the RFC’s forbidden value octets

**RFC:** UN-RFC 0002 §1 requires header values to contain no CR, LF or NUL.  
**Code:** `Article.set()` rejects these characters for locally constructed headers, but `Article.from_bytes()` parses wire headers directly, normalizes CRLF, and does not apply the same value validation to parsed values. The node acceptance path calls `Article.from_bytes()` before structural/signature validation.  
**Assessment:** High-confidence validation gap by static inspection. A lone CR or NUL in a parsed header value appears able to survive parsing. A valid signature over that canonical value would be needed to demonstrate end-to-end acceptance.  
**References:** [`article.py` setter/parser](https://github.com/unseenet/unseenet/blob/0cba7cd8daebc13902b9cd4229155314c6d7e736/src/unseenet/core/article.py#L86-L152); [`accepting.py`](https://github.com/unseenet/unseenet/blob/0cba7cd8daebc13902b9cd4229155314c6d7e736/src/unseenet/node/server/accepting.py#L167-L171); [UN-RFC 0002 §1](https://github.com/unseenet/unseenet/blob/0cba7cd8daebc13902b9cd4229155314c6d7e736/rfc/un-rfc-0002.md#L17-L30).  
**Verification:** Add parser tests for NUL and bare CR in header values, plus an end-to-end node test using an article signed over the parsed canonical form. Ensure normal CRLF remains accepted.

### F-02 — `From` and `Subject` length limits are not visible in article validation

**RFC:** UN-RFC 0002 §2.2 specifies `From` max 128 characters and `Subject` max 256 characters.  
**Code:** The inspected `validate_structure()` checks presence and article syntax but contains no length checks for these fields. No enforcement was located in the inspected node-acceptance call path.  
**Assessment:** High-confidence source-level gap in the reviewed validation path; confirm with signed over-limit articles against the node.  
**References:** [`validate_structure()`](https://github.com/unseenet/unseenet/blob/0cba7cd8daebc13902b9cd4229155314c6d7e736/src/unseenet/core/article.py#L216-L246); [UN-RFC 0002 §2.2](https://github.com/unseenet/unseenet/blob/0cba7cd8daebc13902b9cd4229155314c6d7e736/rfc/un-rfc-0002.md#L46-L58).  
**Verification:** Test values at the specified limits and one character beyond, including multibyte Unicode, and settle whether “characters” means Unicode code points as intended by the RFC.

### F-03 — `Date` with a non-UTC offset appears to be normalized rather than rejected

**RFC:** UN-RFC 0002 §2.1 requires UTC `Date`; §2.5 defines the time window.  
**Code:** `parse_date()` accepts email date forms and assigns UTC to naive values. The inspected validation checks parseability and the future limit, but does not appear to require an explicit zero UTC offset.  
**Assessment:** Likely conformance gap if “UTC” is intended as a wire-format requirement (as written). Confirm with a signed article containing a non-zero numeric offset.  
**References:** [`parse_date()` and validation](https://github.com/unseenet/unseenet/blob/0cba7cd8daebc13902b9cd4229155314c6d7e736/src/unseenet/core/article.py#L38-L49); [UN-RFC 0002 §2.1/§2.5](https://github.com/unseenet/unseenet/blob/0cba7cd8daebc13902b9cd4229155314c6d7e736/rfc/un-rfc-0002.md#L34-L44).  
**Verification:** Test `+0000`, `-0000`, a non-zero offset, and a naive date. Confirm the desired accepted syntax against the RFC’s RFC 5322 UTC example and update either implementation or spec through the normal RFC process.

### F-04 — Self-import origin date can be later than the rounded article date

**RFC:** UN-RFC 0049 §4.2 says `Origin-Date` MUST NOT be later than article `Date`.  
**Code:** `origin_headers()` accepts an origin date up to five minutes after its `now`; article `Date` is rounded down to a ten-minute boundary. Near a rounding boundary, an origin date accepted by the helper may be later than the subsequently generated article date. The reader correctly ignores origin dates later than `Date`, but that does not make the writer conformant.  
**Assessment:** High-confidence boundary-condition risk from source interaction. Reproduce deterministically before marking as confirmed.  
**References:** [`origins.py`](https://github.com/unseenet/unseenet/blob/0cba7cd8daebc13902b9cd4229155314c6d7e736/src/unseenet/core/origins.py#L84-L117); [`format_date()`](https://github.com/unseenet/unseenet/blob/0cba7cd8daebc13902b9cd4229155314c6d7e736/src/unseenet/core/article.py#L38-L42); [UN-RFC 0049 §4.2](https://github.com/unseenet/unseenet/blob/0cba7cd8daebc13902b9cd4229155314c6d7e736/rfc/un-rfc-0049.md#L155-L165).  
**Verification:** Add a controlled-clock test just before a ten-minute boundary, call the public import-posting builder, and assert `Origin-Date <= Date`. Ensure ordinary historical import dates still work.

## Other parser robustness question

`Article.from_bytes()` first replaces CRLF with LF and later `normalize_body()` also converts bare CR to LF. UN-RFC 0002 defines the article as CRLF-terminated UTF-8 lines. This may accept bare-CR or bare-LF wire forms that the RFC does not specify. Determine whether compatibility requires this permissiveness; add explicit tests and document the intended behavior. This is not currently classified as a confirmed defect.

## Selected coverage matrix

| RFC area | Inspected implementation and tests | Preliminary status |
|---|---|---|
| 0002 — syntax, canonical form, signatures, Message-ID | `core/article.py`; `tests/test_protocol.py` | Core path present; F-01/F-02 and UTC date need verification. Tests cover round-trip, tampering, duplicate headers and canonical header order, not all syntax boundaries. |
| 0003 — crypto and encodings | `core/crypto.py`, `core/encoding.py`, `core/groups.py`; `tests/test_protocol.py` | Uses the specified primitives and domain separators; no full RFC vector suite reviewed. Not a cryptographic security audit. |
| 0004 — manifests, posting permissions, closed groups, cancels | `core/groups.py`, `node/server/manifests.py`, `node/server/controls.py`; `tests/test_protocol.py`, `tests/test_node.py` | Important invariants and representative cases are implemented/tested; exhaustive malformed-input and state-transition coverage not reviewed. |
| 0005 — ONNTP | `nntp.py`, `node/server/connection.py`, `reading_commands.py`, `posting_commands.py`, `peering_commands.py`, `node/peering.py`; `tests/test_node.py` | Required command paths are present at a high level. Full reply codes, pipelining, malformed lines, limits, retries and restart behavior not yet checked requirement-by-requirement. |
| 0006 — proof-of-work postage | `core/pow.py`, `node/server/postage.py`, `node/server/accepting.py`; `tests/test_node.py` | Algorithm and acceptance path appear aligned at a high level. Peer advertised-minimum forwarding and exhaustive header/nonce boundaries remain to review. |
| 0049 — imported posts | `core/origins.py`, `client/session/posting.py`, `reading.py`, `notify.py`; `unseenet-import/posting.py`; `tests/test_origins.py`, `tests/test_origin_proof.py`, import `tests/test_draft_posting.py` | Significant client/import behavior and tests exist. F-04 needs a deterministic test. Importer requirements around deduplication, user preview, metadata removal, privacy and cross-source behavior need a full checklist. |
| 0064 — transport addresses | `core/transport.py`, `core/tor.py`, `known_nodes.py`, node config/announcement/list logic; `tests/test_transport.py` | Parser, onion preference and private/test address controls have coverage. Council list and cross-component requirements remain partial per RFC’s own `Implemented:` line. |

## Robustness and security review limits

- **Input validation:** The header parser findings above are the highest-priority robustness candidates. Additional fuzzing/property tests for malformed UTF-8, folded headers, CR/LF boundaries, pathological dates, JSON nesting/size and unusual encodings were not run.
- **Protocol state and resource limits:** The node applies line, article, block and manifest limits in several layers. This report has not tested cancellation during multiline reads, very long individual data lines, slow clients, connection exhaustion or memory behavior.
- **Crypto:** Source uses libsodium/PyNaCl primitives and strict signature verification. No independent cryptographic review, known-answer-vector audit across every operation, side-channel analysis or key-erasure assessment was performed.
- **Tor/privacy:** Code routes onion names via SOCKS with remote DNS and tests exercise a local SOCKS stand-in. This does not verify production Tor configuration, logging of every deployment layer, traffic correlation resistance or operator practices.
- **Cross-repository behavior:** Import core paths were inspected, but the GUI, TUI, entrance, gateway, bots, portable/bootable builders, helpbot, MCP and Home Assistant repositories have not been comprehensively audited.
- **Execution:** No code or tests were run in this review. All candidate findings require reproduction on a checkout before being reported as confirmed defects.

## Recommended next steps

1. Run targeted local tests for F-01 through F-04 and the bare-line-ending question; record exact commands and outcomes.
2. Add a row for every normative MUST/SHOULD in scope, with RFC section, implementation location, test, result and evidence.
3. Continue the audit through all remaining RFCs and their implementation repositories; explicitly mark unreviewed areas.
4. Open separate issues only for reproduced defects. Update RFC `Implemented:` lines only after confirming the project’s convention and actual shipped scope.
5. Keep protocol changes on the process defined by UN-RFC 0000.

GitHub code-search results can be incomplete. This audit relies on direct inspection of cited files for the reported items; search results were used only to discover relevant locations.
