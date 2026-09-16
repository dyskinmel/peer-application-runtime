# Primary sources and design inputs
Observed 2026-09-05; fetched docs are not proof of target execution.

- Python socket: https://docs.python.org/3/library/socket.html — AF_UNIX/timeout behavior; inherits existing service transport.
- Python socket HOWTO: https://docs.python.org/3/howto/sockets.html — partial send/receive and connection behavior.
- SQLite WAL: https://www.sqlite.org/wal.html — WAL-reset risk and patched versions. Actual experiment SQLite3.46.1 remains explicitly unqualified.
- SQLite release3.51.3: https://sqlite.org/releaselog/3_51_3.html — upstream fix, not installed/verified here.
- Local normative baseline: ../../baseline/spec-00.02.00/ (immutable).
- Existing service contract: ../keeper-service/README.ja.md
