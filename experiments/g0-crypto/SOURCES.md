# Primary sources — checked 2026-09-05

Original implementation references, not a security endorsement of this candidate.

| Source | Applied scope |
|---|---|
| https://www.rfc-editor.org/rfc/rfc9180.html | HPKE base-mode algorithms and Appendix A.2.1; suite KEM32/KDF1/AEAD3; manually transcribed hex KAT |
| https://www.rfc-editor.org/rfc/rfc8032.html | Ed25519 algorithm and existing baseline known-answer fixture |
| https://www.rfc-editor.org/rfc/rfc5869.html | HKDF-SHA256 and existing baseline Appendix A.1 fixture |
| https://datatracker.ietf.org/doc/html/draft-irtf-cfrg-xchacha-03 | Appendix A.1 XChaCha known values. This is an expired Internet-Draft, NOT an RFC |
| https://doc.libsodium.org/advanced/ed25519-curve25519 | Separate signature and encryption keys preferred; no implicit key conversion here |
| https://github.com/jedisct1/libsodium/releases | 1.0.21 point-validity security fix and later releases; installed 1.0.18 is not qualified |
| https://nodejs.org/docs/latest-v22.x/api/crypto.html | Built-in Ed25519/X25519/HKDF/ChaCha20Poly1305 interfaces; actual measured Node remains22.16.0 |
| https://sqlite.org/wal.html | WAL-reset issue; existing3.46.1 qualification remains unresolved |

Retrieval limitation: runtime DNS failed for raw.githubusercontent.com; explicit official libsodium1.0.22 archive download also failed. No dependency was silently fetched from another source. The C library image is external and pinned locally; no library/font binary is redistributed.

Fixture derivation: `hpke-base.json` and `xchacha.json` transcribe public test values; `composed-candidate.json` is newly generated public synthetic PAR material. None are user secrets. RFC code-component licensing, when applicable, follows IETF Trust Legal Provisions (https://trustee.ietf.org/license-info/); third-party RFC text is not reproduced as a whole.
