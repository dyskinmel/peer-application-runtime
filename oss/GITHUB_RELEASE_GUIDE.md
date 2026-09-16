# GitHub prerelease guide

This is a local-to-hosted publication handoff. `dyskinmel/peer-application-runtime` is the intended future repository; it is not represented here as an already-created or public repository. Local technical evidence does not perform any GitHub action.

## Required hosted setup before public release

1. Extract the verified source archive into a new empty directory, initialize a new Git repository there, and create the public repository's initial commit from those extracted files only. Do not push this development checkout, its Git history, or any path excluded from the verified archive. Use `dyskinmel/peer-application-runtime` as the intended repository and retain `main` as its default branch.
2. Enable GitHub private vulnerability reporting before any public release. No email fallback is supplied.
3. Configure protected-branch rules/rulesets and require the updated hosted CI to pass on the fresh archive-derived initial commit.
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

Before any GitHub action, verify the archive and its companion checksum, extract it into a new empty directory, and run `python3 tools/test_runner.py` from that extraction. The new repository must not preserve or import the development repository's `.git` directory or history.

## Future tag and pre-release

`v0.1.0-alpha.1` is a future pre-release tag. This handoff must not create it. After the hosted prerequisites are actually complete and independently reviewed, create a GitHub **Pre-release**, not a stable/latest release, using the verified source-only assets and reviewed release notes.

## Nonclaims

Local technical validation does not set `publishable` or `release_authorized` true. They remain false until the public repository, GitHub private vulnerability reporting, hosted CI, and any later distribution-specific requirements are actually completed and independently checked. This handoff does not establish production qualification, native/device qualification, independent security review, network qualification, soak, or physical recovery qualification.
