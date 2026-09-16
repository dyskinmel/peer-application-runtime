-- Separate document application contract; base envelope 'pending' is ingestion only.
CREATE TABLE document_inputs (
 scope BLOB NOT NULL CHECK(length(scope)=32),
 envelope_id BLOB NOT NULL CHECK(length(envelope_id)=32),
 inner_id BLOB NOT NULL CHECK(length(inner_id)=32),
 record BLOB NOT NULL CHECK(length(record)>0 AND length(record)<=800000),
 record_digest BLOB NOT NULL CHECK(length(record_digest)=32),
 first_event BLOB NOT NULL CHECK(length(first_event)=16),
 evidence_class TEXT NOT NULL CHECK(evidence_class IN ('candidate','core-validated')),
 PRIMARY KEY(scope,envelope_id), UNIQUE(scope,inner_id)
) STRICT;
CREATE TABLE document_apply_events (
 operation_id BLOB PRIMARY KEY CHECK(length(operation_id)=16),
 scope BLOB NOT NULL CHECK(length(scope)=32),
 revision INTEGER NOT NULL CHECK(revision>0 AND revision<=64),
 request_digest BLOB NOT NULL CHECK(length(request_digest)=32),
 previous_digest BLOB NOT NULL CHECK(length(previous_digest)=32),
 record BLOB NOT NULL CHECK(length(record)>0 AND length(record)<=1000000),
 record_digest BLOB NOT NULL CHECK(length(record_digest)=32),
 UNIQUE(scope,revision)
) STRICT;
CREATE TABLE document_frontiers (
 scope BLOB PRIMARY KEY CHECK(length(scope)=32),
 revision INTEGER NOT NULL CHECK(revision>0 AND revision<=64),
 operation_id BLOB NOT NULL CHECK(length(operation_id)=16),
 record_digest BLOB NOT NULL CHECK(length(record_digest)=32),
 heads BLOB NOT NULL,
 evidence_class TEXT NOT NULL CHECK(evidence_class IN ('candidate','core-validated'))
) STRICT;
CREATE TABLE document_apply_nonces (
 reservation_id BLOB PRIMARY KEY CHECK(length(reservation_id)=16),
 scope BLOB NOT NULL CHECK(length(scope)=32),
 key_context BLOB NOT NULL CHECK(length(key_context)=32),
 nonce BLOB NOT NULL CHECK(length(nonce)=24),
 request_digest BLOB NOT NULL CHECK(length(request_digest)=32),
 used_by BLOB UNIQUE CHECK(used_by IS NULL OR length(used_by)=16),
 UNIQUE(key_context,nonce)
) STRICT;
