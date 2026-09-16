# Primary references — checked 2026-09-05

These sources inform candidate decisions, not qualification of this implementation.
- SQLite WAL: https://sqlite.org/wal.html — WAL-reset bug, concurrency, sync settings and checkpoints. The documented fix is 3.51.3; listed backports 3.44.6 and 3.50.7. This host 3.46.1 is not verified patched.
- SQLite transaction: https://sqlite.org/lang_transaction.html — BEGIN IMMEDIATE, errors and transaction state. Code tests in_transaction and outcome uncertainty rather than assuming every error rolls back identically.
- SQLite online backup: https://sqlite.org/backup.html — snapshot uses backup API, not a raw live WAL DB file copy.
- SQLite PRAGMA: https://sqlite.org/pragma.html — settings readback and max_page_count used for actual SQLITE_FULL rejection.
- Python 3.13 sqlite3: https://docs.python.org/3.13/library/sqlite3.html — explicit transactions, backup and connection lifecycle. A Connection context manager does not close a connection.
- SQLite atomic commit: https://sqlite.org/atomiccommit.html — filesystem and power-loss assumptions are not established by this process-kill experiment.

Original spec sources remain immutable under baseline/spec-00.02.00/.
No full web pages are bundled. Consult references alongside the measured runtime identity.
