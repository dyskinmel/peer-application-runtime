# ADR-KEEPER-0012 — opaque retention candidate

Status: candidate, local experiment; no approved wire change. Previous baseline remains unchanged.

## Capability and authority
Known authority is an externally verified `(app,space,head,sequence,epoch,issuer public key)` supplied by the trusted host. Keeper does not derive authority from a client payload. Persisted authority must equal the host pin on reopening. Advancing it is a TRUSTED LOCAL operation after the host has verified the chain; this module does not verify that chain again. Stale tokens are denied on every call. A signed, non-delegating capability binds this authority, keeper key, subject signing key, exact index ID, methods and maximum lease duration. It has NO wall-clock expiry: revocation is by known-head change; remote freshness is not guaranteed. Subject proof binds method, lease, operation nonce and payload digest. Read proofs can be replayed within that exact scope; no global anti-replay/freshness claim.

## Retention vs recovery
The existing recovery index and Pin define a bounded opaque inventory. An authorized issuer signs a capability to that exact index; the Keeper checks structural shape and byte IDs, not CRDT or decryption semantics. A receipt binds exact inventory, index, original closure head/epoch, current grant authority, keeper, grant ID, original reservation request nonce, completion/renewal request nonce, boot scope, issue/deadline, generation and payload reservation. Only `OPAQUE_BYTES_RETAINED` is asserted. Receiver recovery verification remains separate.

## Storage and quota
New private POSIX root, one cooperating writer lock, new SQLite schema. Each lease has its own files; no cross-lease dedup. Payload reservation includes encrypted index plus all listed objects; all reservations, including expired/unknown/released, count until an independently designed GC exists. No automatic deletion and no quota refund on release. Counts bound metadata separately. Receiving an object syncs file then directory before acknowledging. Full receipt checks every object, inserts immutable response and lease state in one transaction, and acknowledges only after commit. An existing full receipt is not returned when current objects fail revalidation.

## Time
Default Linux clock is CLOCK_BOOTTIME with hashed kernel boot ID. Fallback uses a fresh process session and monotonic_ns; restart therefore becomes unknown. Different boot or backward clock yields `UNKNOWN_RETAINED`. No use of wall time for deletion or authorization. Explicit authorized renewal may re-establish a lease in a new boot after full byte audit. Expired leases remain readable to current authorized callers until explicit release, but are not reported active. Release stops GET/renew, never erases bytes. Caller-owned signed release is not administrative deletion.

## Residual risks
No OS sandbox, same-UID adversary protection, power-loss/media validation, independent audit, network authentication stack, publisher identity, trusted time, complete filesystem quota, DoS-resistant public service, or writeable recipient restoration. Control freshness depends on the trusted host. Synthetic signing keys exist only in tests/demos. Quotas and unavailable native providers do not justify false qualification.
