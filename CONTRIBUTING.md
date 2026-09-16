# Contributing

PAR is still pre-1.0. Contributions should preserve fail-closed verification and keep reference/local evidence separate from native/product qualification.

## Public-alpha validation

The source-only Alpha validation commands are:

```bash
python3 tools/test_runner.py
python3 tools/check_wire.py --suite python
python3 tools/verify_oss_prerelease_candidate.py <archive> --sha256-file <archive>.sha256
```

The standard runner selects only tests that are self-contained in the public source profile. Historical development tests that depend on internal planning, evidence, knowledge, or handoff material are intentionally outside the distributed Alpha test suite. Use broader Harness and impact selectors only in a complete internal development checkout when a change or milestone requires them; do not present known inapplicable store or crypto checks as Alpha acceptance.

## Development flow

- Work on a focused branch or isolated worktree.
- Add or update a failing regression test before behavior changes.
- Run the narrow checker for the area you changed.
- Keep commits reviewable and document contract changes.

## Pull requests

A PR should explain the problem, affected contracts, focused tests run, remaining NOT_RUN/BLOCKED items, and any compatibility/security implications. Do not claim native or production qualification from a local/reference test.

## Sensitive changes

Crypto provider/trust/key-lifecycle changes, wire-format compatibility changes, persistence/migration semantics, security boundaries, and evidence-promotion rules require additional review. Crypto changes must not auto-select or auto-upgrade a production provider.

## Native work

Native implementation changes should be developed in a Rust/Cargo-capable environment and verified against the checked-in contracts/corpora. Missing native tooling is a blocker for native qualification, not a reason to substitute source inspection.

## Documentation

Documentation-only changes should remain inside the public/source authority boundaries and pass the OSS boundary/scan checks. Internal agent/checkpoint/recovery material does not belong in the public source candidate.
