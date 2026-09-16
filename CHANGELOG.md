# Changelog

This changelog summarizes externally meaningful prerelease milestones rather than every internal checkpoint.

## 0.1.0-alpha.1 — selected source-only Alpha

### Added

- Apache-2.0 license and NOTICE material in the source-only public boundary.
- Public-alpha wire-only verification and deterministic source archive verification.
- Explicit source-only release decisions while preserving false publication authorization.

### Release scope

- This Alpha contains no compiled binary, wheel, container image, native artifact, or native dependency bundle.
- Signing and hosted attestation are not release assets for this source-only Alpha.
- Hosted CI remains an external prerequisite before any public release.

### Security / compatibility

- Production crypto provider selection remains unresolved by design.
- Native, device, network, and external qualification results are not inferred from local/reference PASS results.
