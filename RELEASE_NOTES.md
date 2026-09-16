# Release notes — 0.1.0-alpha.1 source-only Alpha

`0.1.0-alpha.1` is the selected source-only Alpha for Peer Application Runtime (PAR). It contains source, LOCAL/reference runtime candidates, deterministic verification tooling, contracts, corpora, and Native Readiness boundaries. It contains no compiled binary, wheel, container image, native artifact, or native dependency bundle.

## Limitations and prerequisites

This Alpha is not Production Qualified. Native foundation closure, production crypto provider/security closure, native/device/network qualification, independent security review, soak, and physical recovery qualification remain outstanding.

Signing and hosted attestation are not release assets for this source-only Alpha. Hosted CI remains an external prerequisite before any public release, alongside the intended public repository and GitHub private vulnerability reporting.

## Verify locally

```bash
python3 tools/check_wire.py --suite python
python3 tools/verify_oss_prerelease_candidate.py <archive> --sha256-file <archive>.sha256
```

Local technical validation does not set `publishable` or `release_authorized` to true.
