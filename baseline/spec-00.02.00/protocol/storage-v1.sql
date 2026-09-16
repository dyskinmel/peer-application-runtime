-- PAR minimal native storage schema CANDIDATE.
-- Body bytes MUST already be encrypted. This DDL does not implement cryptography.
PRAGMA foreign_keys = ON;
CREATE TABLE store_metadata (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1),
  schema_version INTEGER NOT NULL CHECK(schema_version=1),
  generation BLOB NOT NULL CHECK(length(generation)=16),
  profile_digest BLOB NOT NULL CHECK(length(profile_digest)=32)
) STRICT;
CREATE TABLE spaces (
  space_id BLOB PRIMARY KEY CHECK(length(space_id)=32),
  app_id TEXT NOT NULL,
  control_head BLOB NOT NULL CHECK(length(control_head)=32),
  control_sequence BLOB NOT NULL CHECK(length(control_sequence)=8),
  content_epoch BLOB NOT NULL CHECK(length(content_epoch)=8),
  state TEXT NOT NULL CHECK(state IN ('ready','control-pending','key-pending','seed-pending','fork','read-only')),
  encrypted_metadata BLOB NOT NULL
) STRICT;
CREATE TABLE writer_fences (
  store_generation BLOB PRIMARY KEY CHECK(length(store_generation)=16),
  fencing_token BLOB NOT NULL CHECK(length(fencing_token)=16),
  owner_process BLOB NOT NULL CHECK(length(owner_process)=16)
) STRICT;
CREATE TABLE actor_states (
  space_id BLOB NOT NULL REFERENCES spaces(space_id),
  object_id BLOB NOT NULL CHECK(length(object_id)=32),
  actor_id BLOB NOT NULL CHECK(length(actor_id)=32),
  generation BLOB NOT NULL CHECK(length(generation)=16),
  last_sequence BLOB NOT NULL CHECK(length(last_sequence)=8),
  previous_envelope BLOB CHECK(previous_envelope IS NULL OR length(previous_envelope)=32),
  PRIMARY KEY(space_id,object_id,actor_id)
) STRICT;
CREATE TABLE envelopes (
  envelope_id BLOB PRIMARY KEY CHECK(length(envelope_id)=32),
  space_id BLOB NOT NULL REFERENCES spaces(space_id),
  object_id BLOB NOT NULL CHECK(length(object_id)=32),
  epoch BLOB NOT NULL CHECK(length(epoch)=8),
  actor_id BLOB NOT NULL CHECK(length(actor_id)=32),
  sequence BLOB NOT NULL CHECK(length(sequence)=8),
  change_hash BLOB NOT NULL CHECK(length(change_hash)=32),
  encrypted_bytes BLOB NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('pending','applied','quarantined','resource-blocked')),
  UNIQUE(space_id,object_id,epoch,actor_id,sequence)
) STRICT;
CREATE TABLE commit_ledger (
  operation_id BLOB PRIMARY KEY CHECK(length(operation_id)=16),
  input_digest BLOB NOT NULL CHECK(length(input_digest)=32),
  space_id BLOB NOT NULL REFERENCES spaces(space_id),
  commit_id BLOB NOT NULL UNIQUE REFERENCES envelopes(envelope_id),
  receipt_encrypted BLOB NOT NULL
) STRICT;
CREATE TABLE outbox (
  envelope_id BLOB PRIMARY KEY REFERENCES envelopes(envelope_id),
  operation_id BLOB NOT NULL REFERENCES commit_ledger(operation_id),
  attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0),
  next_attempt_local_ms INTEGER,
  state TEXT NOT NULL CHECK(state IN ('pending','in-flight','retained','rebase-required'))
) STRICT;
CREATE TABLE dependency_edges (
  envelope_id BLOB NOT NULL REFERENCES envelopes(envelope_id),
  required_change_hash BLOB NOT NULL CHECK(length(required_change_hash)=32),
  PRIMARY KEY(envelope_id,required_change_hash)
) STRICT;
CREATE TABLE catalog (
  space_id BLOB NOT NULL REFERENCES spaces(space_id),
  object_id BLOB NOT NULL CHECK(length(object_id)=32),
  kind INTEGER NOT NULL CHECK(kind BETWEEN 1 AND 5),
  schema_digest BLOB NOT NULL CHECK(length(schema_digest)=32),
  encrypted_snapshot_ref BLOB,
  tombstone INTEGER NOT NULL CHECK(tombstone IN (0,1)),
  encrypted_frontier BLOB NOT NULL,
  PRIMARY KEY(space_id,object_id)
) STRICT;
CREATE TABLE blocks (
  block_id BLOB PRIMARY KEY CHECK(length(block_id)=32),
  size_bytes INTEGER NOT NULL CHECK(size_bytes>=0),
  relative_object_path TEXT NOT NULL UNIQUE,
  published INTEGER NOT NULL CHECK(published IN (0,1)),
  storage_class TEXT NOT NULL
) STRICT;
CREATE TABLE root_sets (
  root_id BLOB PRIMARY KEY CHECK(length(root_id)=32),
  space_id BLOB NOT NULL REFERENCES spaces(space_id),
  root_generation BLOB NOT NULL CHECK(length(root_generation)=16),
  encrypted_descriptor BLOB NOT NULL,
  closure_state TEXT NOT NULL CHECK(closure_state IN ('unknown','byte-complete','semantically-verified','incomplete'))
) STRICT;
CREATE TABLE root_blocks (
  root_id BLOB NOT NULL REFERENCES root_sets(root_id),
  block_id BLOB NOT NULL REFERENCES blocks(block_id),
  PRIMARY KEY(root_id,block_id)
) STRICT;
CREATE TABLE pins (
  pin_id BLOB PRIMARY KEY CHECK(length(pin_id)=16),
  root_id BLOB NOT NULL REFERENCES root_sets(root_id),
  reason TEXT NOT NULL CHECK(reason IN ('local-active','outbox','user','lease','recovery','export','migration','quarantine'))
) STRICT;
CREATE TABLE reservations (
  reservation_id BLOB PRIMARY KEY CHECK(length(reservation_id)=16),
  operation_id BLOB NOT NULL UNIQUE CHECK(length(operation_id)=16),
  input_digest BLOB NOT NULL CHECK(length(input_digest)=32),
  space_id BLOB NOT NULL REFERENCES spaces(space_id),
  manifest_id BLOB NOT NULL CHECK(length(manifest_id)=32),
  reserved_bytes INTEGER NOT NULL CHECK(reserved_bytes>=0),
  boot_reference BLOB NOT NULL CHECK(length(boot_reference)=16),
  expiry_mono_ms INTEGER,
  state TEXT NOT NULL CHECK(state IN ('offered','reserved','committed','expiry-uncertain','released'))
) STRICT;
CREATE TABLE receipts (
  receipt_id BLOB PRIMARY KEY CHECK(length(receipt_id)=32),
  reservation_id BLOB NOT NULL REFERENCES reservations(reservation_id),
  signed_bytes BLOB NOT NULL,
  observed_boot BLOB NOT NULL CHECK(length(observed_boot)=16),
  observed_mono_ms INTEGER NOT NULL CHECK(observed_mono_ms>=0)
) STRICT;
CREATE TABLE recovery_sessions (
  session_id BLOB PRIMARY KEY CHECK(length(session_id)=16),
  source_root BLOB NOT NULL CHECK(length(source_root)=32),
  profile_digest BLOB NOT NULL CHECK(length(profile_digest)=32),
  recipient_device BLOB NOT NULL CHECK(length(recipient_device)=32),
  state TEXT NOT NULL CHECK(state IN ('fetching','verifying','rebuilding','ready','active','partial','failed')),
  encrypted_journal BLOB NOT NULL
) STRICT;
CREATE TABLE migration_journal (
  migration_id BLOB PRIMARY KEY CHECK(length(migration_id)=16),
  source_digest BLOB NOT NULL CHECK(length(source_digest)=32),
  target_version INTEGER NOT NULL,
  phase TEXT NOT NULL,
  encrypted_journal BLOB NOT NULL
) STRICT;
CREATE TABLE quarantined_inputs (
  input_id BLOB PRIMARY KEY CHECK(length(input_id)=32),
  space_id BLOB REFERENCES spaces(space_id),
  reason TEXT NOT NULL,
  encrypted_bytes BLOB NOT NULL,
  size_bytes INTEGER NOT NULL CHECK(size_bytes>=0)
) STRICT;
CREATE INDEX outbox_pending ON outbox(state,next_attempt_local_ms);
CREATE INDEX envelope_object ON envelopes(space_id,object_id,epoch);
CREATE INDEX required_dependency ON dependency_edges(required_change_hash);
CREATE INDEX catalog_scope ON catalog(space_id,kind,tombstone);

CREATE TABLE control_entries (
  control_id BLOB PRIMARY KEY CHECK(length(control_id)=32),
  space_id BLOB NOT NULL REFERENCES spaces(space_id),
  sequence BLOB NOT NULL CHECK(length(sequence)=8),
  previous_id BLOB NOT NULL CHECK(length(previous_id)=32),
  signed_bytes BLOB NOT NULL
) STRICT;
-- No UNIQUE(space,sequence): retain both valid forks for evidence and halt sharing.
CREATE INDEX control_position ON control_entries(space_id,sequence);
CREATE TABLE key_references (
  key_id BLOB PRIMARY KEY CHECK(length(key_id)=32),
  purpose TEXT NOT NULL,
  protection_class TEXT NOT NULL,
  encrypted_reference BLOB NOT NULL
) STRICT;
CREATE TABLE issued_nonces (
  key_context BLOB NOT NULL CHECK(length(key_context)=32),
  nonce BLOB NOT NULL CHECK(length(nonce)=24),
  payload_digest BLOB NOT NULL CHECK(length(payload_digest)=32),
  PRIMARY KEY(key_context,nonce)
) STRICT;
CREATE TABLE event_delivery (
  channel_id BLOB NOT NULL CHECK(length(channel_id)=32),
  delivery_sequence BLOB NOT NULL CHECK(length(delivery_sequence)=8),
  event_id BLOB NOT NULL CHECK(length(event_id)=32),
  retention_generation BLOB NOT NULL CHECK(length(retention_generation)=16),
  PRIMARY KEY(channel_id,delivery_sequence), UNIQUE(channel_id,event_id)
) STRICT;
CREATE TABLE subscriber_cursors (
  channel_id BLOB NOT NULL CHECK(length(channel_id)=32),
  subscriber_id BLOB NOT NULL CHECK(length(subscriber_id)=32),
  delivery_sequence BLOB NOT NULL CHECK(length(delivery_sequence)=8),
  retention_generation BLOB NOT NULL CHECK(length(retention_generation)=16),
  PRIMARY KEY(channel_id,subscriber_id)
) STRICT;
CREATE TABLE rpc_ledger (
  caller_id BLOB NOT NULL CHECK(length(caller_id)=32),
  operation_id BLOB NOT NULL CHECK(length(operation_id)=16),
  input_digest BLOB NOT NULL CHECK(length(input_digest)=32),
  state TEXT NOT NULL CHECK(state IN ('admitted','started','completed','failed-known','outcome-unknown','cancelled')),
  encrypted_result BLOB,
  PRIMARY KEY(caller_id,operation_id)
) STRICT;
