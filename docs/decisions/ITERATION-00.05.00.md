# 00.05.00 execution plan — local store experiment

Goal: Implement the approved NEXT_G0_STORE scope using actual SQLite/files and subprocesses; preserve the 85-file baseline and keep G0/OD-04 unclosed.
Architecture: a typed opaque-input store, explicit transactions, exclusive cooperating-writer lock, a POSIX block publication port, restart audit, and snapshot/restore. Encryption, network auth and OS power-loss qualification are not implemented here.
Spec: baseline/spec-00.02.00/spec/09-local-storage.ja.md; spec05; plan/NEXT_G0_STORE.ja.md.
Environment measured: Python 3.13.5, SQLite 3.46.1, Node 22.16.0, Linux x86_64; rustc/cargo unavailable.

## Checkpoints and work units
- [x] S1 tests first: input contracts, atomic commit, replay, writer/epoch/actor CAS, nonce reservations. `python3 tools/check_store.py --suite core`. Missing implementation must fail before implementation.
- [x] S2 bounded POSIX block publish + all-or-nothing statement-boundary crash tests. `python3 tools/check_store.py --suite faults`. Test worker uses real processes and pipes; no wall-clock sleep as a correctness oracle.
- [x] S3 consistent SQLite backup, exact block manifest, read-only restored store, corruption-preserving recovery. `python3 tools/check_store.py --suite recovery`.
- [x] S4 register G0-STORE-LOCAL, exact test inventories, harness integration and fresh checkpoint/resume; rerun H0 and wire.
- [x] S5 candidate review, source bundle, new-copy execution, full ZIP readback and SHA-256.

Each unit: real failing assertion → implementation → positive/reject verification → source diff review → Git checkpoint. Test registration and guarded source changes use a fresh session, never a changed acceptance criterion in a running session.

## Scope refinements (candidate ADR-STORE-0001)
- Nonce issuance is durable BEFORE external encryption. Failed transaction must not un-issue a nonce. Opaque input remains a trust boundary, not proof of encryption or signing.
- No claim of physical power-cut safety from child-process SIGKILL.
- SQLite's current official documentation identifies WAL-reset corruption risk through 3.51.2, fixed in 3.51.3 and specific backports. This host's 3.46.1 is not verified patched. Require an explicit experiment-only opt-in; cooperating Store connections use a lifetime exclusive OS lock. Not a claim that arbitrary SQLite clients are safe or a production approval.
- Backup restore opens read-only, even with a copied nonce ledger. Activating a restored writer requires future rekey/new actor-generation policy, not automatic reuse of old key/nonce state.

## Interface to implement
`Store.create/open(root, allow_unpatched_sqlite=False)`, `configure_space`, `reserve_nonce`, `commit(PreparedCommit, fencing_token=...)`, `lookup_operation`, `pending`, `recover_outbox`, `advance_epoch`, `audit`, `collect_orphans`, `export_snapshot`, `restore_snapshot`.
`PreparedCommit` includes operation/input IDs, Space/object/actor/generation/seq/prev/epoch, nonce reservation, immutable opaque envelope/cache/receipt bytes, ordered dependencies and sealed block bytes.
Errors are typed codes with operation ID and known/unknown outcome; raw SQL parameters and payloads are not logged.

## Remaining external/full-G0 obligations
Native Rust adapter, actual AEAD/signature/actor integration, patched SQLite target qualification, OS/FS power-loss tests, independent reviewer, Keeper reconstruction, mobile/browser storage.

Final execution and distribution results are recorded in release/STATUS.json and the sibling ZIP.verification.json.

Preflight archive and fresh bundle clone: H0 115 registered results + wire262 + store163 all verified; checkpoint resume READY. Final delivery repeats these checks and records exact digest in release/STATUS.json / sibling report.
