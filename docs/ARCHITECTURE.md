# Architecture overview

PAR separates product contracts, reference/local implementations, native production work, and qualification evidence so that a convenient local implementation cannot silently become a production claim.

## Major layers

1. **Specification and authority** — the immutable baseline specification, reviewed ADR/contract overlays, schemas, and requirement mappings.
2. **Reference/local implementation** — deterministic Python/Node/SQLite/POSIX candidates used to exercise behavior, compatibility, recovery, and failure semantics before native closure.
3. **Native foundation** — G0-ACTOR, G0-WIRE, G0-STORE, and G0-CRYPTO. These are the foundation for the production-oriented runtime and are not yet fully qualified.
4. **Application/runtime work packages** — owner, synchronization, storage, event, presentation, management, migration, and related capabilities built above the foundation.
5. **Harness and evidence** — source-bound test selection, receipts, checkpoints, impact analysis, and fail-closed status handling. Missing tools, timeouts, stale evidence, or NOT_RUN results do not become PASS.
6. **External qualification** — real platform/network/security/soak/recovery/release gates. These remain separate from local/reference validation.

## Native readiness contracts

The source candidate includes executable contracts/corpora for actor semantics, wire compatibility, store recovery/fault behavior, and provider-neutral crypto boundaries. These are intended to be consumed by native implementations without rewriting the expected behavior from scratch.

## Source and evidence identity

Verification is tied to the exact source revision, tree, source digest, authority digests, environment, and test subject. Evidence from a prior source revision is historical evidence unless explicitly and safely re-established for the new revision.

## Persistence and recovery posture

Local reference code includes atomicity, stale-write, recovery, backup/shadow, and crash-boundary work, but local process and SIGKILL evidence is not a substitute for native filesystem durability or physical power-loss qualification.
