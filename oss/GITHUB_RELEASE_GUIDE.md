# GitHub prerelease guide

This guide records the completed local-to-hosted publication handoff for `dyskinmel/peer-application-runtime`. The repository is public, GitHub private vulnerability reporting is enabled, and hosted CI has passed. Local technical evidence alone does not perform or prove those GitHub actions; their completion was independently checked on 2026-09-16.

## Completed hosted setup

1. The public repository was created from verified archive contents with clean Git history. This development checkout, its history, and excluded paths were not pushed. `main` is the default branch.
2. GitHub private vulnerability reporting is enabled. No email fallback is supplied.
3. `main` is protected and requires the hosted `local-reference` CI check; deletion and force-push are disabled.
4. Keep ordinary CI read-only (`contents: read`), secret-free, and without release uploads, attestations, or write permissions. Keep the conditional native lane separate; enable it only after its runner/toolchain policy is reviewed.

## Local source-only evidence to reproduce

```bash
python3 -m unittest tests.test_oss_prerelease tests.test_public_alpha_release -v
python3 tools/check_public_preview_boundary.py
python3 tools/build_oss_inventory.py --check
python3 tools/build_public_preview_candidate.py --output peer-application-runtime-0.1.0-alpha.1-source.zip --sha256-file peer-application-runtime-0.1.0-alpha.1-source.zip.sha256
python3 tools/verify_oss_prerelease_candidate.py peer-application-runtime-0.1.0-alpha.1-source.zip --sha256-file peer-application-runtime-0.1.0-alpha.1-source.zip.sha256
```

The source-only assets are `peer-application-runtime-0.1.0-alpha.1-source.zip` and `peer-application-runtime-0.1.0-alpha.1-source.zip.sha256`. Signing and attestation are not required assets for this source-only Alpha. Native dependency SBOM status is `NOT_APPLICABLE` only because this Alpha distributes no native or binary artifact; a final native SBOM is required before any native or binary distribution.

Before updating the public repository or its release assets, verify the archive and its companion checksum, extract it into a clean directory, and run `python3 tools/test_runner.py` from that extraction. Public commits must continue to contain only verified archive contents and must not import the development repository's `.git` directory or history.

## Authorized tag and pre-release

`v0.1.0-alpha.1` is authorized as a GitHub **Pre-release**, not a stable/latest release, after hosted CI succeeds for the exact public commit. Use only the verified source-only ZIP, its `.sha256` companion, and these reviewed release notes.

## Nonclaims

`publishable=true` and `release_authorized=true` apply only to `v0.1.0-alpha.1` as a source-only Alpha Pre-release. This handoff does not establish production qualification, native/device qualification, independent security review, network qualification, soak, or physical recovery qualification.
