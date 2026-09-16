-- Candidate schema3. Typed IDs and raw-file locators must never be aliases by fiat.
CREATE TABLE blob_objects (
 typed_id BLOB PRIMARY KEY CHECK(length(typed_id)=32),
 locator BLOB NOT NULL UNIQUE REFERENCES blocks(block_id) CHECK(length(locator)=32),
 app_id TEXT NOT NULL,
 space_id BLOB NOT NULL REFERENCES spaces(space_id),
 epoch BLOB NOT NULL CHECK(length(epoch)=8),
 object_id BLOB NOT NULL CHECK(length(object_id)=32),
 object_kind INTEGER NOT NULL CHECK(object_kind=3),
 chunk_index BLOB NOT NULL CHECK(length(chunk_index)=8),
 key_generation BLOB NOT NULL CHECK(length(key_generation)=8),
 plain_size INTEGER NOT NULL CHECK(plain_size BETWEEN 0 AND 262144),
 sealed_size INTEGER NOT NULL CHECK(sealed_size BETWEEN 1 AND 266240),
 header_bytes BLOB NOT NULL CHECK(length(header_bytes) BETWEEN 1 AND 4096)
) STRICT;
CREATE TABLE blob_commit_roots (
 operation_id BLOB PRIMARY KEY REFERENCES commit_ledger(operation_id),
 envelope_id BLOB NOT NULL UNIQUE REFERENCES envelopes(envelope_id),
 mode INTEGER NOT NULL CHECK(mode IN (0,1)),
 manifest BLOB,
 CHECK((mode=0 AND manifest IS NULL) OR (mode=1 AND length(manifest) BETWEEN 1 AND 131072))
) STRICT;
CREATE TABLE blob_references (
 envelope_id BLOB NOT NULL REFERENCES blob_commit_roots(envelope_id),
 position INTEGER NOT NULL CHECK(position BETWEEN 0 AND 127),
 typed_id BLOB NOT NULL REFERENCES blob_objects(typed_id),
 PRIMARY KEY(envelope_id,position), UNIQUE(envelope_id,typed_id)
) STRICT;
