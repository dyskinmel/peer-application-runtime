# Primary references checked 2026-09-06 UTC (2026-09-05 America/Chicago)
- Python OS API: https://docs.python.org/3/library/os.html — fsync and POSIX os.replace. Atomic pathname replacement does not by itself establish power-loss durability or an adversarial filesystem sandbox.
- SQLite WAL: https://www.sqlite.org/wal.html — WAL-reset advisory and patch branches. This container still uses SQLite3.46.1 with explicit disposable-fixture-only opt-in; no patched-target qualification.
- SQLite 3.51.3 release: https://sqlite.org/releaselog/3_51_3.html — upstream fixed version information; no assertion that this runtime is patched.
- Preserved internal baseline: baseline/spec-00.02.00. Local candidate contract resides in ADR-KEEPER-REPAIR-0014, not in upstream standards.
