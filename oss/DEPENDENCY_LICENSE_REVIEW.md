# Source-only Alpha dependency license review

Reviewed on 2026-09-16 for the `0.1.0-alpha.1` source-only Alpha.
This is a factual upstream-license review, not legal advice or production
qualification.

| Dependency or tool | Upstream license | Alpha relationship | Official evidence |
| --- | --- | --- | --- |
| libsodium 1.0.18 local/reference candidate | ISC | Referenced system library; binary not bundled | [libsodium LICENSE](https://github.com/jedisct1/libsodium/blob/1.0.18/LICENSE) |
| SQLite | Public domain (`LicenseRef-SQLite-Public-Domain`) | Python/system runtime; library not bundled | [SQLite copyright](https://www.sqlite.org/copyright.html) |
| TypeScript compiler | Apache-2.0 | Development build tool; not bundled | [TypeScript LICENSE](https://github.com/microsoft/TypeScript/blob/main/LICENSE.txt) |
| Automerge | MIT | Future native dependency candidate; not selected or bundled | [Automerge LICENSE](https://github.com/automerge/automerge/blob/main/LICENSE) |
| Production crypto provider | Unknown | Future selection required; not selected or bundled | No upstream can be reviewed until a provider is selected. |

All checked-in `package.json` files declare `Apache-2.0` for their local PAR
components. No third-party binary, native dependency bundle, or resolved
transitive dependency graph is included in this Alpha.

No known license conflict was found for this source-only scope. A new review
is required before selecting or distributing a production crypto provider,
Automerge/native implementation, binary, native artifact, or resolved
third-party dependency bundle. Publication authorization remains separate and
blocked on the public repository, private vulnerability reporting, and hosted
CI prerequisites.
