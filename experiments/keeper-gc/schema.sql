CREATE TABLE metadata (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 profile BLOB NOT NULL CHECK(length(profile)=32),
 keeper BLOB NOT NULL CHECK(length(keeper)=32),
 authority BLOB NOT NULL,
 quota INTEGER NOT NULL CHECK(quota>0),
 max_leases INTEGER NOT NULL CHECK(max_leases>0),
 max_ops INTEGER NOT NULL CHECK(max_ops>0),
 clock_boot BLOB NOT NULL CHECK(length(clock_boot)=32),
 clock_ns INTEGER NOT NULL CHECK(clock_ns>=0)
) STRICT;
CREATE TABLE leases (
 id BLOB PRIMARY KEY CHECK(length(id)=32),
 index_raw BLOB NOT NULL,
 pin BLOB NOT NULL,
 owner BLOB NOT NULL CHECK(length(owner)=32),
 origin_nonce BLOB NOT NULL CHECK(length(origin_nonce)=32),
 seconds INTEGER NOT NULL CHECK(seconds BETWEEN 1 AND 86400),
 charge INTEGER NOT NULL CHECK(charge>0),
 state TEXT NOT NULL CHECK(state IN ('reserved','sealed','released')),
 generation INTEGER NOT NULL CHECK(generation>=0),
 receipt BLOB,
 CHECK((generation=0 AND receipt IS NULL) OR (generation>0 AND receipt IS NOT NULL))
) STRICT;
CREATE TABLE stored_objects (
 lease BLOB NOT NULL REFERENCES leases(id),
 oid BLOB NOT NULL CHECK(length(oid)=32),
 PRIMARY KEY(lease,oid)
) STRICT;
CREATE TABLE operations (
 id BLOB PRIMARY KEY CHECK(length(id)=32),
 lease BLOB NOT NULL REFERENCES leases(id),
 action TEXT NOT NULL CHECK(action IN ('reserve','seal','renew','release')),
 request BLOB NOT NULL,
 capability BLOB NOT NULL,
 response BLOB NOT NULL
) STRICT;
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
