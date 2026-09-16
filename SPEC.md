# Specification authority

`baseline/spec-00.02.00/START_HERE.ja.md` is the product specification entry.
The original 25 documents, 149 requirements, 149 acceptance contracts, 16 work packages, 12 gates and 11 open decisions are retained, not promoted.
`policy/baseline.json` binds the exact original file set; the source ZIP SHA-256 is recorded there.

Order: user-approved product constraints → reviewed normative contract/ADR overlays → acceptance contracts → task plan → knowledge cards → logs.
The harness may check this hierarchy but cannot authorize its own contract changes.
`docs/H0_DESIGN.ja.md` and `docs/HARNESS_CONTRACT.ja.md` specify the new H0 behavior.

H0 is NOT a second product spec. `plan/product-state.json` records the delivered state; H0 does not implement the production qualification engine.
Future product status must be derived from registered product tests and reviewed gate evaluation, not by changing a status string.
G0-WIRE-LOCAL is a separately registered experiment. Its local checks do not close OD-02 or product gates.
`plan/experiment-state.json` records this distinction; all full product gates and external reviews remain NOT_RUN.
Candidate wire overlays: `docs/decisions/ADR-WIRE-0001.ja.md` and `ADR-WIRE-0002.ja.md`; their bytes are bound by the experimental profile.

Space auth candidate overlays: `ADR-AUTH-0001..0003` in `docs/decisions/`. Public replay and opaque seed format are local candidates, not a protocol freeze. The standalone auth profile remains in-memory; the separate auth/Store candidate provides local durable integration, not native/product qualification.

Atomic Store overlays: `ADR-AUTH-STORE-0001..0003` in `docs/decisions/`. The exact local profile is `experiments/auth-store/profile.json`; no baseline requirement or full gate is auto-promoted.

Blob schema3 overlays: `docs/decisions/ADR-BLOB-STORE-0001.ja.md` and `ADR-BLOB-STORE-0002.ja.md`. `experiments/blob-store/profile.json` pins the candidate inputs. Signed attachment sidecar is not a baseline wire protocol or whole-file manifest.

00.11.00: local recipient recovery overlay: `docs/decisions/ADR-RECOVERY-0011.ja.md` and `experiments/recovery-closure/profile.json`. No immutable baseline change or product-gate promotion.

00.12.00: opaque Keeper overlay: `docs/decisions/ADR-KEEPER-0012.ja.md`, `experiments/keeper-retention/profile.json`. Scoped payload reservations, known-authority capabilities, local receipts and conservative retention. No automatic GC, network protocol freeze or product-gate promotion.

00.14.00 repair overlay: docs/decisions/ADR-KEEPER-REPAIR-0014.ja.md and experiments/keeper-repair/profile.json. Immutable baseline unchanged.

00.16.00 upload candidate overlay: experiments/keeper-upload/README.ja.md and docs/decisions/ADR-KEEPER-UPLOAD-0016.ja.md. New local profile only; original PAR wire and product qualification remain unchanged.

00.17.00: explicit staging retirement overlay is `docs/decisions/ADR-KEEPER-UPLOAD-RETIRE-0017.ja.md` with candidate profile `experiments/keeper-upload-retire/profile.json`. Not a product protocol freeze.

00.19.00 overlay: `experiments/upload-window-host/profile.json`, `docs/decisions/ADR-UPLOAD-WINDOW-HOST-0019.ja.md`. Separate private IPC + offline admin; no immutable baseline change.

00.20.00: exact positive signature verification reuse, not authority/state caching: `docs/decisions/ADR-HOST-SNAPSHOT-0020.ja.md` and `experiments/host-verified-snapshot/profile.json`. Shared bounded-reader correction is explicit; immutable baseline unchanged.

## 00.21.00 candidate overlay
Owner management jobs: [contract](experiments/host-management-jobs/README.ja.md) and [ADR](docs/decisions/ADR-MANAGEMENT-JOBS-0021.ja.md). Explicit reconciliation is not atomicity, cancellation is not rollback, and live scheduling is not implemented. Baseline remains unchanged.

## 00.22.00 candidate overlay
Actual owner-loop scheduling: [contract](experiments/host-job-scheduler/README.ja.md) and [ADR](docs/decisions/ADR-JOB-SCHEDULER-0022.ja.md). This adds real selector drain to the former owner jobs, not a management network API, preemption or public protocol. Original profiles and baseline remain unchanged.

## 00.23.00 candidate overlay
Private owner control: [contract](experiments/host-job-control/README.ja.md) and [ADR](docs/decisions/ADR-JOB-CONTROL-0023.ja.md). Pre-registered jobs only. Control acknowledgment is not job success. No baseline or product qualification change.

## 00.25.00 candidate overlay
[Dual-authorized submission retirement](experiments/job-submission-retire/README.ja.md) and [ADR](docs/decisions/ADR-SUBMISSION-RETIRE-0025.ja.md). Payload reclamation is not job cancellation or record GC; original baseline unchanged.

## 00.28 product component overlay
`product/wp11/README.ja.md` and `docs/decisions/ADR-REFERENCE-PRESENTER-0028.ja.md` define the partial Presenter/intent/draft contract. They do not supersede full UI/G6 or native runtime acceptance. Product component progress and qualification are recorded separately.

## 00.31 read-only runtime observation candidate
`docs/decisions/ADR-RUNTIME-OBSERVATION-0031.ja.md` and `product/runtime_read/README.ja.md`: fixed-scope owner observations and original-operation inquiries. No shared write, CRDT application, public transport or product gate promotion.

## 00.33 pending synchronization overlay
`product/wp04/INBOX.ja.md`, `inbox-profile.json`, `docs/decisions/ADR-SYNC-INBOX-0033.ja.md`. Per-scope encrypted pending bytes; no application commit, CRDT apply or network protocol freeze.


## 00.57.00 local migration rehearsal
`product/wp14/MIGRATION_REHEARSAL.ja.md`, `product/wp14/migration-profile.json` and `docs/decisions/ADR-LOCAL-MIGRATION-REHEARSAL-0057.ja.md` define a Python/SQLite/POSIX local candidate: read-only plan, verified backup/readback, exact durable-state shadow copy, unknown mandatory codec fencing, verified same-filesystem publication, atomic generation pointer switch and six real-process SIGKILL recovery boundaries. It does not modify the immutable baseline and is not Rust/native build, device durability, physical-power-loss, real CRDT migration, G9, independent-review or production-qualification evidence.

## 00.60.00 local owner consolidation / OSS preview boundary
`plan/LOCAL_CLOSURE_SPRINT_A_0060.ja.md`は既存candidateのowner-task provenance整理とpublic-preview境界を追加するが、immutable baseline要件を変更しない。`Peer Application Runtime`はprovisional functional descriptorであり、license/project name/security contact/public repository/release versionは未決定。Device/external handoff項目はlocal evidenceからqualificationへ昇格しない。
