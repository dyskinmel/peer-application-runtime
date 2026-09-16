# Primary references checked for this candidate

Retrieved 2026-09-05/06 UTC during the local task. These describe primitives and limitations, not proof of the composed implementation.

- SQLite, Atomic Commit: https://sqlite.org/atomiccommit.html — database transaction boundaries do not automatically include external object files.
- SQLite, WAL: https://www.sqlite.org/wal.html — durability settings and WAL-reset fix information; current host remains experimental/unqualified.
- Python, os: https://docs.python.org/3/library/os.html — fsync, dir_fd, unlink, O_NOFOLLOW/platform-specific availability.
- Exact inherited contracts: `../keeper-retention/README.ja.md`, `../recovery-closure/README.ja.md`; public test keys only.
