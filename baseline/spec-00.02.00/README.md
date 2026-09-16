# Peer Application Runtime — Specification 00.02.00

A fully open-source, local-first cooperative backend built from authorized participant devices.

This archive contains **design and normative candidates**, not a working SDK. It covers product guarantees, identity/authorization, crypto and wire candidates, document/event/blob synchronization, retention and recovery, platform lifecycle, SDK contracts, polishable UI architecture, operations, upgrades, security and production qualification.

Start with [the Japanese reading guide](START_HERE.ja.md). Detailed draft prose is Japanese. The English protocol publication is a pre-release work item, not already complete.

The first success scenario uses editors A/B, an opaque Keeper C, and a pre-authorized recovery identity B2. After A/B become unavailable, B2 restores from C and separately held recovery material. A Keeper must not mint new permissions merely because it stores ciphertext.

**State:** normative candidate, not frozen. Product implementation: not started. Product runtime tests and independent security review: not run. Specification-support validation is recorded separately in `evidence/`.

```sh
python3 tools/validate_spec.py
python3 tools/test_validator.py
python3 tools/check_assets.py
```

No network access is required by these checks. `check_assets` reports a blocked TypeScript lane when `tsc` is absent. Primitive KAT verification optionally needs an existing `cryptography` Python installation.

License: Apache-2.0 for original package material. Referenced external specifications retain their own licenses. The project name is provisional. No registry package, hosted service, GitHub repository or production release was published by creating this archive.
