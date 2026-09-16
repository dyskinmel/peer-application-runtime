# Primary references — checked 2026-09-06

- SQLite PRAGMA data_version: https://www.sqlite.org/pragma.html#pragma_data_version — values compare only within the same connection; own commits do not change this value. Used only as a conservative invalidation hint, never as an integrity witness.
- Python 3.13 tracemalloc: https://docs.python.org/3.13/library/tracemalloc.html — Python allocation tracing, not total process RSS or all native allocations.
- Libsodium detached signatures: https://libsodium.gitbook.io/doc/public-key_cryptography/public-key_signatures — verification inputs are public key, message and detached signature. Exact-input reuse is this project's candidate design, not a libsodium security endorsement. Documentation found through its primary site's indexed extract; direct web fetch failed.

No dependency was upgraded or acquired during this implementation. Actual provider identity comes from the local environment and pinned policy, not current documentation.
