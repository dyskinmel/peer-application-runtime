-- Authority/Store overlay v1, PRAGMA user_version 2; base schema_version stays 1.
-- Public signed metadata and encrypted material only. No secret key/plain seed.
CREATE TABLE auth_spaces (
 space_id BLOB PRIMARY KEY REFERENCES spaces(space_id),
 app_id TEXT NOT NULL,
 replay BLOB NOT NULL CHECK(length(replay) BETWEEN 1 AND 900000),
 replay_digest BLOB NOT NULL CHECK(length(replay_digest)=32),
 head BLOB NOT NULL CHECK(length(head)=32),
 sequence BLOB NOT NULL CHECK(length(sequence)=8),
 epoch BLOB NOT NULL CHECK(length(epoch)=8),
 revision BLOB NOT NULL CHECK(length(revision)=8),
 phase TEXT NOT NULL CHECK(phase IN ('CONTROL_REQUIRED','MEMBERSHIP_PENDING','EPOCH_PENDING','ACTIVE','CONTROL_FORK','CONTROL_INVALID')),
 active_material BLOB CHECK(active_material IS NULL OR length(active_material)=32),
 row_digest BLOB NOT NULL CHECK(length(row_digest)=32)
) STRICT;
CREATE TABLE auth_epoch_keys (
 space_id BLOB NOT NULL REFERENCES auth_spaces(space_id),
 epoch BLOB NOT NULL CHECK(length(epoch)=8),
 anchor BLOB NOT NULL CHECK(length(anchor)=32),
 key_check BLOB NOT NULL CHECK(length(key_check)=32),
 PRIMARY KEY(space_id,epoch), UNIQUE(space_id,key_check)
) STRICT;
CREATE TABLE auth_materials (
 space_id BLOB NOT NULL REFERENCES auth_spaces(space_id),
 material_id BLOB NOT NULL CHECK(length(material_id)=32),
 epoch BLOB NOT NULL CHECK(length(epoch)=8),
 anchor BLOB NOT NULL CHECK(length(anchor)=32),
 key_check BLOB NOT NULL CHECK(length(key_check)=32),
 encrypted_material BLOB NOT NULL CHECK(length(encrypted_material) BETWEEN 1 AND 900000),
 PRIMARY KEY(space_id,material_id),
 FOREIGN KEY(space_id,epoch) REFERENCES auth_epoch_keys(space_id,epoch)
) STRICT;
CREATE TABLE auth_commits (
 operation_id BLOB PRIMARY KEY REFERENCES commit_ledger(operation_id),
 space_id BLOB NOT NULL REFERENCES auth_spaces(space_id),
 head BLOB NOT NULL CHECK(length(head)=32),
 sequence BLOB NOT NULL CHECK(length(sequence)=8),
 epoch BLOB NOT NULL CHECK(length(epoch)=8),
 revision BLOB NOT NULL CHECK(length(revision)=8),
 device_id BLOB NOT NULL CHECK(length(device_id)=32),
 certificate BLOB NOT NULL,
 key_check BLOB NOT NULL CHECK(length(key_check)=32),
 material_id BLOB NOT NULL CHECK(length(material_id)=32),
 prepared_digest BLOB NOT NULL CHECK(length(prepared_digest)=32),
 proof_digest BLOB NOT NULL CHECK(length(proof_digest)=32),
 FOREIGN KEY(space_id,material_id) REFERENCES auth_materials(space_id,material_id)
) STRICT;
