# Initial UN-RFC Implementation Conformance Audit

**Status:** Preliminary; not a complete conformance audit  
**Reviewed snapshot:** `unseenet/unseenet` commit [`49658254fd5a924e10977d7521e1decb2d4e4fcb`](https://github.com/unseenet/unseenet/tree/49658254fd5a924e10977d7521e1decb2d4e4fcb) and `unseenet/unseenet-import` commit [`2f9c942f5659b8021cea63c64263be48cc61f5fd`](https://github.com/unseenet/unseenet-import/tree/2f9c942f5659b8021cea63c64263be48cc61f5fd)  
**Method:** Manual comparison of selected RFC requirements with source code and existing tests. No local test suite was run as part of this review.

## Summary

The reviewed code paths generally follow the architecture and protocol behavior described by the UN-RFCs. Existing tests provide useful coverage for article signing and validation, node acceptance, replication, transport parsing, imported-post dates and draft posting.

This review identified **three potential conformance issues for targeted verification**. They are not yet confirmed defects: each should be reproduced with a focused test and checked against the intended interpretation of the RFC before being filed as a bug.

The review is incomplete. It does not establish conformance across all RFC requirements, all repositories, or all edge cases.

## Potential findings requiring verification

### 1. UN-RFC 0002 §2.2: `From` and `Subject` length limits

The RFC limits `From` to 128 characters and `Subject` to 256 characters. The inspected article parser and `validate_structure()` check required headers, syntax, signatures, Message-IDs, size and dates, but I did not find enforcement of these two field-specific length limits in that validation path.

**Relevant code:** [`article.py`, parsing and structure validation](https://github.com/unseenet/unseenet/blob/49658254fd5a924e10977d7521e1decb2d4e4fcb/src/unseenet/core/article.py#L125-L152) · [`validate_structure()`](https://github.com/unseenet/unseenet/blob/49658254fd5a924e10977d7521e1decb2d4e4fcb/src/unseenet/core/article.py#L216-L246)  
**RFC requirement:** [UN-RFC 0002 §2.2](https://github.com/unseenet/unseenet/blob/49658254fd5a924e10977d7521e1decb2d4e4fcb/rfc/un-rfc-0002.md#L46-L58)

**Next check:** Add focused tests for over-limit `From` and `Subject` values submitted to a node. Confirm whether validation occurs elsewhere before recording this as a confirmed discrepancy.

### 2. UN-RFC 0002 §§2.1 and 2.5: `Date` timezone

The RFC specifies that an article’s `Date` is UTC. The inspected `parse_date()` uses Python’s email date parser and normalizes dates without a timezone to UTC, but the inspected validation code does not appear to reject a date carrying a non-UTC offset.

**Relevant code:** [`parse_date()`](https://github.com/unseenet/unseenet/blob/49658254fd5a924e10977d7521e1decb2d4e4fcb/src/unseenet/core/article.py#L38-L49) · [`validate_structure()`](https://github.com/unseenet/unseenet/blob/49658254fd5a924e10977d7521e1decb2d4e4fcb/src/unseenet/core/article.py#L216-L246)  
**RFC requirement:** [UN-RFC 0002 §2.1](https://github.com/unseenet/unseenet/blob/49658254fd5a924e10977d7521e1decb2d4e4fcb/rfc/un-rfc-0002.md#L34-L44)

**Next check:** Test signed articles with equivalent UTC instants expressed using non-zero offsets. Determine whether the RFC requires rejection or whether normalization is intentionally acceptable.

### 3. UN-RFC 0049 §4.2: generated `Origin-Date` may be later than article `Date`

`origin_headers()` permits an `Origin-Date` up to five minutes ahead of its `now` value. Article `Date` values are rounded down to a ten-minute boundary. Near a rounding boundary, this may allow a generated origin date later than the article’s `Date`, which §4.2 prohibits. The reader path ignores an origin date later than `Date`, but that does not prevent the client from producing the inconsistent article.

**Relevant code:** [`origin_headers()`](https://github.com/unseenet/unseenet/blob/49658254fd5a924e10977d7521e1decb2d4e4fcb/src/unseenet/core/origins.py#L84-L117) · [`format_date()`](https://github.com/unseenet/unseenet/blob/49658254fd5a924e10977d7521e1decb2d4e4fcb/src/unseenet/core/article.py#L38-L42)  
**RFC requirement:** [UN-RFC 0049 §4.2](https://github.com/unseenet/unseenet/blob/49658254fd5a924e10977d7521e1decb2d4e4fcb/rfc/un-rfc-0049.md#L155-L165)

**Next check:** Add a deterministic boundary test using a controlled `now` value near a ten-minute rounding boundary. Confirm whether the public posting APIs can actually produce this case, and fix or clarify the behavior if reproduced.

## Areas with positive, but incomplete, evidence

- **UN-RFC 0002 article handling:** The core implements parsing, canonicalization, signing, signature verification, Message-ID calculation and checks for required and forbidden headers. The node acceptance pipeline additionally applies duplicate, date, retention, postage and group-permission checks. [`tests/test_protocol.py`](https://github.com/unseenet/unseenet/blob/49658254fd5a924e10977d7521e1decb2d4e4fcb/tests/test_protocol.py#L20-L59) covers round trips, tampering, duplicate headers and canonicalization order. This does not cover every RFC boundary condition.
- **UN-RFC 0003 cryptography and UN-RFC 0004 groups:** The inspected core uses Ed25519 signatures with purpose separation, libsodium sealed boxes and XChaCha20-Poly1305. Group code implements manifests, closed-group epochs and member-signature checks. Existing protocol tests cover basic manifest, moderation and closed-group behavior; a full check against all normative requirements and test vectors remains outstanding.
- **UN-RFC 0005 ONNTP and UN-RFC 0006 postage:** Inspected node and core code implements the main command loop, capabilities, POST, peer streaming commands, article acceptance and proof-of-work checks. [`tests/test_node.py`](https://github.com/unseenet/unseenet/blob/49658254fd5a924e10977d7521e1decb2d4e4fcb/tests/test_node.py#L27-L49) covers basic acceptance and insufficient postage; its integration test exercises local client/node interaction and replication. The full command profile, malformed input handling, history retention and peer negotiation still need a systematic review.
- **UN-RFC 0049 imported posts:** Core code handles origin headers, invalid/future origin dates, “old on arrival,” ordering and notifications. The [`unseenet-import` posting code](https://github.com/unseenet/unseenet-import/blob/2f9c942f5659b8021cea63c64263be48cc61f5fd/src/unseenet_import/posting.py) contains draft and posting functionality, with tests for local encrypted drafts and posting through the shared core in [`test_draft_posting.py`](https://github.com/unseenet/unseenet-import/blob/2f9c942f5659b8021cea63c64263be48cc61f5fd/tests/test_draft_posting.py#L55-L100). Its README/status should be checked against the actual implemented UI and end-to-end user flow.
- **UN-RFC 0064 transport addresses:** Transport parsing, onion preference, test-address gating, multi-address handling and private-network peering have corresponding source and tests in [`transport.py`](https://github.com/unseenet/unseenet/blob/49658254fd5a924e10977d7521e1decb2d4e4fcb/src/unseenet/core/transport.py) and [`test_transport.py`](https://github.com/unseenet/unseenet/blob/49658254fd5a924e10977d7521e1decb2d4e4fcb/tests/test_transport.py). The RFC’s `Implemented:` line already identifies incomplete areas; verify the remaining council-list and related integration requirements rather than assuming they are complete.

## RFC implementation-status notes

UN-RFC 0005 and 0006 currently state `Implemented: unseenet 0.1.0`. The current code includes behavior added by later RFCs, but that alone does not establish that the lines are inaccurate: they may identify the first release implementing each RFC. Confirm the project’s convention before proposing edits.

UN-RFC 0064 explicitly marks some parts as partial. Its status should be re-evaluated only after checking the relevant council-list and cross-repository paths against the RFC’s exact requirements.

## Recommended next steps

1. Reproduce the three potential findings above with focused, deterministic tests.
2. Record each RFC requirement in a traceable matrix: RFC section, source location, tests, status and evidence.
3. Continue the audit through the rest of the core and node requirements, then the client/service repositories that implement RFC-defined behavior.
4. Update this report and issue [#907](https://github.com/unseenet/unseenet/issues/907) with verified results; create separate follow-up issues only for confirmed discrepancies.
5. Keep protocol changes on the process defined by UN-RFC 0000.
