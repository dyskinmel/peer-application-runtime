# Codex OSS release handoff

The local environment has prepared and verified source-only technical evidence. Publication is authorized only for the GitHub Pre-release `v0.1.0-alpha.1`. `dyskinmel/peer-application-runtime` is the public archive-derived repository.

## Human/Codex decisions and external prerequisites

- **license**, **project name**, **version/tag**, and **copyright/NOTICE** are reviewed local decisions; retain their recorded values in the fresh archive-derived initial commit.
- **public repository** — completed and independently checked on 2026-09-16. Continue importing only reviewed source-archive contents; never push this development checkout, its Git history, or excluded internal paths.
- **security contact** — GitHub private vulnerability reporting is enabled. No email fallback is supplied.
- `main` protection and the required hosted `local-reference` CI check are enabled; hosted CI must pass for the exact release commit.
- Review/pin GitHub Actions and the conditional native runner/toolchain policy. The separate native lane is not a substitute for the local source-only contract.

## Verify imported source-only evidence

```bash
python3 -m unittest tests.test_oss_prerelease tests.test_public_alpha_release -v
python3 tools/check_public_preview_boundary.py
python3 tools/build_oss_inventory.py --check
python3 tools/build_public_preview_candidate.py --output peer-application-runtime-0.1.0-alpha.1-source.zip --sha256-file peer-application-runtime-0.1.0-alpha.1-source.zip.sha256
python3 tools/verify_oss_prerelease_candidate.py peer-application-runtime-0.1.0-alpha.1-source.zip --sha256-file peer-application-runtime-0.1.0-alpha.1-source.zip.sha256
```

The source-only release assets are `peer-application-runtime-0.1.0-alpha.1-source.zip` and `peer-application-runtime-0.1.0-alpha.1-source.zip.sha256`. Signing and attestation are not required assets for this source-only Alpha. The native dependency SBOM is `NOT_APPLICABLE` only because no native or binary artifact is distributed; a final native SBOM becomes required before native or binary distribution.

Run `python3 tools/test_runner.py` from the fresh extraction before committing it to the public repository. The public repository must retain clean archive-derived history and must not contain the development repository's `.git` directory.

## Authorized tag and pre-release publication

After hosted CI succeeds for the exact public commit, create `v0.1.0-alpha.1` as a GitHub **Pre-release** with the verified source-only assets and reviewed release notes. Do not mark it as stable/latest.

## Nonclaims

`publishable=true` and `release_authorized=true` apply only to the selected source-only Alpha Pre-release. This handoff does not establish release signing, hosted attestation, native/device qualification, independent security review, network qualification, soak, physical recovery qualification, or Production Qualification.
