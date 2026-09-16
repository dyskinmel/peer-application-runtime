CREATE TABLE repair_jobs (
 id BLOB PRIMARY KEY CHECK(length(id)=32),
 lease BLOB NOT NULL REFERENCES leases(id),
 request BLOB NOT NULL,
 capability BLOB NOT NULL,
 intent BLOB NOT NULL,
 phase TEXT NOT NULL CHECK(phase IN ('prepared','done','aborting','aborted')),
 result BLOB,
 cancel_request BLOB,
 cancel_capability BLOB,
 CHECK((phase='prepared' AND result IS NULL AND cancel_request IS NULL AND cancel_capability IS NULL)
 OR (phase='done' AND result IS NOT NULL AND cancel_request IS NULL AND cancel_capability IS NULL)
 OR (phase='aborting' AND result IS NULL AND cancel_request IS NOT NULL AND cancel_capability IS NOT NULL)
 OR (phase='aborted' AND result IS NOT NULL AND cancel_request IS NOT NULL AND cancel_capability IS NOT NULL))
) STRICT;
