# ADR-EVENT-CLIENT-0041 — explicit local client reconciliation

Owner approved continuing `plan/NEXT_EVENT_CLIENT_LIFECYCLE_0040.ja.md` in this environment.
Choose a bounded in-memory lifecycle over the existing `EventCommands`, not transport redesign or a new persistence subsystem.
Rebinding never publishes or inquires by itself. One retained original operation must be reconciled explicitly. Local absence does not authorize replay.
Compare complete context on rebind and fence by a locally monotonic connection generation as well as host identity.
A channel changes ownership only on successful rebind; release/abort/cleanup are bounded and observable. No control of synchronous owner execution is claimed.
Typed view data are separate from WP11 shared-document/private-draft state. No automatic ACK, native/browser qualification, public listener, key regeneration, restored-writer activation or baseline-spec edits.
Detailed contract and checkpoint plan: `product/wp10/CLIENT_LIFECYCLE.ja.md`.
