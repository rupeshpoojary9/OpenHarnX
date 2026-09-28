# Walking skeleton (TDD §12 step 1)

```text
Task: thin end-to-end path over T06 to T11 (M1 TDD 0.3, build order step 1)
Status: done
Owner / reviewer: Rupesh Poojary
Environment: macOS 26.5.2 arm64; CPython 3.12.7; srt 0.0.77
```

## Delivered

`ohx init`, `ohx contract accept <file>`, `ohx verify [--sandbox auto|srt|none] [--json]`, `ohx report [--json]`, `ohx store check`.

- Pure kernel: canonical digests (RFC 8785), contract validation, gate with fixed precedence and no decision-provider input.
- Store outside the repository (`~/.openharnx` or `OHX_HOME`): SQLite journal with hash chain, content-addressed blobs.
- Protected acceptance material copied into the store at acceptance and digest-checked before every run.
- Candidate recomputed after verification; any change makes the run's observations `invalid`.
- Checkers run in the `srt` verifier sandbox when available, with an environment allowlist; the report states which protection applied.
- Markdown and JSON reports with the changelog entry, overhead line and limitations; zero model calls.

## Evidence

`uv run pytest`: 33 passed, 1 skipped (the sandboxed test, which runs with `OHX_SRT` set and passed separately).

| Fixture variant | Exit | Verdict |
|---|---|---|
| baseline | 10 | blocked |
| valid_fix | 0 | ready |
| incomplete_fix | 10 | blocked |
| access_breaking_fix | 10 | blocked |
| tampered_test_on_baseline | 10 | blocked |
| valid_fix with the store's protected copy altered | 10 | unknown |

Mutation checks, each caught by the suite: gate ignoring mandatory unknown; protected-copy tamper check removed; stale evidence accepted.

Manual demo on 2026-09-28 with `--sandbox srt`: baseline exit 10 (acceptance failed), valid fix exit 0, `ohx store check` reports the chain intact.

## Limits (deliberate, deepened in later steps)

- Observations are not signed; regression failures are not compared with a baseline, so the unit-test obligation is advisory.
- No agent adapter, cost ledger, CRs, handoff, export or outcomes yet.
- Record identifiers use UUIDv4, not the sortable UUIDv7 in the TDD.
