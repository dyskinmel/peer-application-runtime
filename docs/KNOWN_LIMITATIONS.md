# Known limitations and non-claims

This `0.1.0-alpha.1` source-only Alpha is **not Production Qualified**.

The selected local source identity is Peer Application Runtime (PAR), licensed as Apache-2.0 with `Copyright 2026 dyskinmel`; the current name may change later. These selections do not authorize publication.

The following remain incomplete or unqualified:

- G0-ACTOR native qualification and real native actor/sequence/dependency closure.
- G0-WIRE native qualification and independent standards/conformance evidence.
- G0-STORE native qualification, native durability, and device-level crash/storage evidence.
- G0-CRYPTO production provider decision and production security closure.
- Native key protection and platform keystore qualification.
- Independent security review.
- Real Internet and network qualification, including real deployment/topology behavior.
- Long-duration soak and production performance qualification.
- Physical recovery qualification, including real power-loss/media-failure evidence.
- Hosted CI, the intended public repository, and GitHub private vulnerability reporting before public release.

Final native-SBOM finalization is `NOT_APPLICABLE` only because no native or binary artifact is distributed in this source-only Alpha. It is required before any native-artifact or binary distribution.

The source-only smoke command is wire-only: `python3 tools/check_wire.py --suite python`. `examples/store_demo.py` is not an acceptance command on macOS because `experiments/g0-store/par_store/fs.py:safe` currently rejects the platform `/var` alias. Local crypto checks may be `BLOCKED` when the unbundled pinned provider is unavailable or mismatched.

Release signing and hosted attestation are not release assets for this source-only Alpha. Reference/local implementations, fixtures, compatibility corpora, and deterministic Harness checks are useful engineering assets, but they are intentionally not promoted into the missing native/external qualification gates.
