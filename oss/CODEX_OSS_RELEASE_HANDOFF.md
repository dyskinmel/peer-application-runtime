# Codex OSS release handoff

The local environment has prepared source-only technical evidence. Final publication is intentionally not authorized here. `dyskinmel/peer-application-runtime` is the intended future repository, not an already-created public repository.

## Human/Codex decisions and external prerequisites

- **license**, **project name**, **version/tag**, and **copyright/NOTICE** are reviewed local decisions; retain their recorded values in the fresh archive-derived initial commit.
- **public repository** — verify and extract the reviewed source archive into a new empty directory, initialize a new Git repository from those extracted files only, and use it for `dyskinmel/peer-application-runtime`. Never push this development checkout, its Git history, or excluded internal paths. Set `main` as the default branch.
- **security contact** — enable GitHub private vulnerability reporting before any public release. No email fallback is supplied.
- Apply branch protection/rulesets and require the updated hosted CI to pass on the fresh archive-derived initial commit.
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

Run `python3 tools/test_runner.py` from the fresh extraction before creating its initial commit. The public repository must begin with new Git history and must not contain the development repository's `.git` directory.

## Future tag and pre-release publication

`v0.1.0-alpha.1` is a future pre-release tag, and this task must not create it. Only after the external prerequisites are complete and independently checked may an authorized person create the GitHub **Pre-release** with the verified source-only assets and reviewed release notes.

## Nonclaims

Local technical validation does not set `publishable` or `release_authorized` true; both remain false. This handoff does not establish hosted CI success, GitHub configuration, release signing, hosted attestation, native/device qualification, independent security review, network qualification, soak, physical recovery qualification, or Production Qualification.
