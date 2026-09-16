# Primary references — checked 2026-09-05

- SQLite Transaction: https://www.sqlite.org/lang_transaction.html — BEGIN IMMEDIATE, commit/rollback and error behavior.
- SQLite Isolation: https://www.sqlite.org/isolation.html — separate connection writer serialization; do not assume isolation between writes on the same connection.
- SQLite WAL: https://www.sqlite.org/wal.html — WAL conditions, WAL-reset corruption issue; this runtime's SQLite3.46.1 is not qualified as a patched production target.

These references inform the candidate design. They are not evidence that the composed PAR protocol or host is qualified. The supplied tests execute real local SQLite/process faults; hardware power loss, current patched target runtimes and independent review remain unexecuted. Source links are references, not runtime network dependencies.
