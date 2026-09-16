# Peer Application Runtime (PAR) — Alpha source candidate

> **Status: Alpha / developer preview.** `Peer Application Runtime (PAR)` is the current project name and may change later. This source-only Alpha is **not Production Qualified** and is not authorized for public release.

PAR is an open-source-oriented runtime and protocol development kit for participant-owned application backends. The repository explores authenticated data exchange, deterministic wire formats, local durable storage, recovery semantics, authorization, synchronization boundaries, offline/host workflows, and verification evidence.

## Source-only Alpha contract

This selected `0.1.0-alpha.1` distribution is source-only and licensed under [Apache-2.0](LICENSE). It carries no compiled binary, wheel, container image, native artifact, or native dependency bundle. `NOTICE` accompanies the license material.

The source includes LOCAL/reference implementations, deterministic contracts, tests, fixtures, compatibility corpora, recovery/fault semantics, and Native Readiness tooling. It does not claim native foundation closure, production crypto provider selection, native/device/network qualification, independent security review, long soak, physical recovery qualification, signing, hosted provenance, or Production Qualification. See [Known limitations](docs/KNOWN_LIMITATIONS.md).

## Public-alpha verification

The public-alpha acceptance path is deliberately narrow:

```bash
python3 tools/test_runner.py
python3 tools/check_wire.py --suite python
python3 tools/verify_oss_prerelease_candidate.py <archive> --sha256-file <archive>.sha256
```

`tools/test_runner.py` automatically selects the self-contained public-alpha tests in this source profile. They cover the public policy, inventory, archive contracts, and the Python wire smoke check. The full development suite is not the public-alpha acceptance criterion. Historical development tests that require excluded `plan/`, `knowledge/`, `evidence/`, or handoff material are not distributed as public-alpha tests. In particular, do not treat `tools/harness.py validate`, `examples/store_demo.py`, `tools/check_store.py`, or `tools/check_crypto.py` as release-start commands for this Alpha.

A local PASS is evidence only for the exact source and environment checked. It does not replace native, device, network, security, or hosted qualification.

## Native readiness

The native implementation path remains separate. `python3 tools/harness.py native-resume` can inspect native-readiness blockers in a Rust/Cargo-capable environment; missing tooling or an unresolved crypto provider is a blocker, not a PASS substitute.

## Architecture and contribution

See [Architecture](docs/ARCHITECTURE.md), [Contributing](CONTRIBUTING.md), and [Security](SECURITY.md). Security-sensitive, persistence, evidence-promotion, wire-compatibility, and crypto changes require stricter review and focused regression.

## Release status

`publishable=false` and `release_authorized=false` remain in force. Before any public release, the intended repository, GitHub private vulnerability reporting, and hosted CI are external prerequisites. The intended future pre-release tag is `v0.1.0-alpha.1`; this source candidate does not create it.

## Next stage

The primary engineering path is native foundation work: G0-ACTOR, G0-WIRE, G0-STORE, and an explicitly reviewed G0-CRYPTO provider/security decision, followed by downstream integration and real-environment qualification. See [ROADMAP.md](docs/ROADMAP.md).
