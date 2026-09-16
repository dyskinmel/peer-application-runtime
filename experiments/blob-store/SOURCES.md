# Primary references / checked 2026-09-05

- SQLite WAL: https://www.sqlite.org/wal.html — WAL transaction/checkpoint behavior and WAL-reset issue. Local host is NOT production-qualified.
- SQLite online backup: https://www.sqlite.org/backup.html — consistent database snapshot through the backup API; external Blob files need their own verified closure.
- Existing cryptographic contract: `../../baseline/spec-00.02.00/spec/05-cryptography.ja.md`.
- Candidate composition: `../../docs/decisions/ADR-BLOB-STORE-0001.ja.md` and `ADR-BLOB-STORE-0002.ja.md`.

Source descriptions are not runtime evidence. This candidate's tests and release logs state exactly what ran. No source claims the candidate attachment sidecar is a standard protocol.
