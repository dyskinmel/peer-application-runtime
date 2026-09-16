CREATE TABLE gc_jobs (
 lease BLOB PRIMARY KEY REFERENCES leases(id) CHECK(length(lease)=32),
 id BLOB NOT NULL UNIQUE CHECK(length(id)=32),
 request BLOB NOT NULL,
 capability BLOB NOT NULL,
 intent BLOB NOT NULL,
 phase TEXT NOT NULL CHECK(phase IN ('marked','done')),
 result BLOB,
 credit INTEGER NOT NULL CHECK(credit>=0),
 CHECK((phase='marked' AND result IS NULL AND credit=0) OR (phase='done' AND result IS NOT NULL))
) STRICT;
