# Primary references consulted for 00.12.00

Accessed 2026-09-05. External references explain underlying behavior; they do not validate this implementation.

- Python `time`: https://docs.python.org/3/library/time.html — monotonic clock reference point, nanosecond clock API. Kernel boot identity is additionally required by this candidate before reusing elapsed-time values.
- SQLite transactions: https://www.sqlite.org/lang_transaction.html — BEGIN IMMEDIATE, commit/rollback and lock behavior.
- SQLite result codes: https://www.sqlite.org/rescode.html — BUSY, FULL and transaction outcomes.
- SQLite WAL: https://www.sqlite.org/wal.html — WAL reset defect, patch history, persistence limitations. No claim that the installed 3.46.1 library is patched; test-only consent remains.

Inherited sources for signature primitives, canonical encoding and recipient recovery are retained in the respective experiment directories. No third-party code or native binary is copied by this lane.
