-- Additive LOCAL EXPERIMENT schema, not a migration of deployed PAR databases.
CREATE TABLE local_settings (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 read_only_restore INTEGER NOT NULL CHECK(read_only_restore IN (0,1))
) STRICT;
CREATE TABLE local_operation_intents (
 operation_id BLOB PRIMARY KEY CHECK(length(operation_id)=16),
 input_digest BLOB NOT NULL CHECK(length(input_digest)=32)
) STRICT;
CREATE TABLE local_nonce_reservations (
 reservation_id BLOB PRIMARY KEY CHECK(length(reservation_id)=16),
 operation_id BLOB NOT NULL REFERENCES local_operation_intents(operation_id),
 key_context BLOB NOT NULL,
 nonce BLOB NOT NULL,
 consumed_by BLOB REFERENCES envelopes(envelope_id),
 FOREIGN KEY(key_context,nonce) REFERENCES issued_nonces(key_context,nonce),
 UNIQUE(key_context,nonce)
) STRICT;
CREATE TABLE local_commit_meta (
 operation_id BLOB PRIMARY KEY REFERENCES commit_ledger(operation_id),
 prepared_digest BLOB NOT NULL CHECK(length(prepared_digest)=32),
 reservation_id BLOB NOT NULL UNIQUE REFERENCES local_nonce_reservations(reservation_id),
 actor_generation BLOB NOT NULL CHECK(length(actor_generation)=16),
 previous_envelope BLOB CHECK(previous_envelope IS NULL OR length(previous_envelope)=32),
 encrypted_cache BLOB NOT NULL,
 store_generation BLOB NOT NULL CHECK(length(store_generation)=16),
 storage_class TEXT NOT NULL,
 commit_order INTEGER NOT NULL UNIQUE CHECK(commit_order>0)
) STRICT;
CREATE TABLE envelope_blocks (
 envelope_id BLOB NOT NULL REFERENCES envelopes(envelope_id),
 block_id BLOB NOT NULL REFERENCES blocks(block_id),
 position INTEGER NOT NULL CHECK(position>=0),
 PRIMARY KEY(envelope_id,block_id), UNIQUE(envelope_id,position)
) STRICT;
