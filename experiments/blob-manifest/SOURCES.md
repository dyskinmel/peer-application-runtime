# Sources and verification boundary — 2026-09-05

Primary references used for inherited durability/cryptography contracts:
- https://www.sqlite.org/wal.html — checked in this turn. WAL-reset fix3.51.3, backports3.44.6/3.50.7. Installed3.46.1 remains experimental/unqualified.
- https://www.sqlite.org/atomiccommit.html — checked in this turn. Storage flush/order assumptions do not turn process-kill tests into power-loss tests.
- ../g0-crypto/SOURCES.md — retained cipher/KDF/signature references and known-answer provenance.

Retrieval limitation: the libsodium XChaCha documentation page returned unsupported text/markdown in web retrieval in this turn. No new claim about its latest release was inferred. Reused the pinned provider and previously checked contract; no binary fetched or redistributed.

The file manifest/journal/export composition is new code by the same author as the tests. It is not independently audited and does not add a new cipher suite. The original product specification remains byte-identical.
