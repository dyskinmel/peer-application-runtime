# Sources consulted for the local candidate

Checked 2026-09-05. The immutable `baseline/spec-00.02.00` defines project intent; the linked ADRs are draft overlays, not approved protocol replacements.

- PAR baseline: `spec/03-identity.ja.md`, `04-authority.ja.md`, `05-cryptography.ja.md`, `08-synchronization.ja.md`, `protocol/par-v1.cddl`.
- RFC8949 (CBOR and deterministic encoding): https://www.rfc-editor.org/rfc/rfc8949.html
- RFC9180 (HPKE and context separation; not a PAR protocol audit): https://www.rfc-editor.org/rfc/rfc9180.html
- libsodium official release history: https://github.com/jedisct1/libsodium/releases
- SQLite WAL official guidance and limitations: https://sqlite.org/wal.html

Membership paging rules, seed manifest, action restrictions, replay format and local permit sealing here are PAR experiment design choices, not properties supplied by those standards. Historical native-library limitations are retained; no new library qualification was performed. Public synthetic fixture keys must never be used for real data.
