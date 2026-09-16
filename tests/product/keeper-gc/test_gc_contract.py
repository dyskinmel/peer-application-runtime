import os,sqlite3
from dataclasses import replace
from gc_support import GCTest,h
from par_wire.codec import encode,decode

class GCContract(GCTest):
    def test_active_never_collected(self):
        lid,_=self.ready();self.err('NOT_RELEASED',lambda:self.gc_request(lid))
    def test_expired_never_collected(self):
        lid,_=self.ready();self.clock.ns+=100*10**9
        self.assertEqual(self.status(lid)['state'],'EXPIRED_RETAINED');self.err('NOT_RELEASED',lambda:self.gc_request(lid))
    def test_unknown_never_collected(self):
        lid,_=self.ready();self.clock.boot=h('other-boot');self.reopen()
        self.assertEqual(self.status(lid)['state'],'UNKNOWN_RETAINED');self.err('NOT_RELEASED',lambda:self.gc_request(lid))
    def test_release_does_not_delete(self):
        lid,req=self.released();self.assertTrue(all(self.keeper.object_path(lid,x).exists() for x in self.bundle.objects))
        self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total)
    def test_current_authority_required(self):
        lid,req=self.released();self.keeper.update_authority(replace(self.authority,head=h('new-head'),sequence=2))
        self.err('CAPABILITY_SCOPE',lambda:self.gc(lid,req))
    def test_stale_generation_rejected(self):
        lid,_=self.released();req=self.gc_request(lid,generation=88);self.err('GC_SCOPE',lambda:self.gc(lid,req))
    def test_wrong_release_rejected(self):
        lid,_=self.released();req=self.gc_request(lid,release_id=h('wrong'));self.err('GC_SCOPE',lambda:self.gc(lid,req))
    def test_signature_mutation_rejected(self):
        lid,req=self.released();v=decode(req);v[1]=bytes([v[1][0]^1])+v[1][1:]
        self.err('GC_SIGNATURE',lambda:self.gc(lid,encode(v)))
    def test_read_only_capability_cannot_collect(self):
        lid,_=self.released();cap=self.k.issue_capability(self.p,self.s.owner,self.authority,self.kp,self.cp,self.rpin.index_id,('get','status'),60,h('read-cap'))
        req=self.gc_request(lid,cap=cap);self.err('METHOD_DENIED',lambda:self.gc(lid,req,cap))
    def test_nonowner_denied(self):
        lid,_=self.released();seed=h('outsider');cap=self.k.issue_capability(self.p,self.s.owner,self.authority,self.kp,self.p.sign_public(seed),self.rpin.index_id,('release',),60,h('other-cap'))
        req=self.gc_request(lid,cap=cap,seed=seed);self.err('LEASE_OWNER',lambda:self.gc(lid,req,cap))
    def test_unknown_field_denied(self):
        lid,req=self.released();v=decode(req);v[7]=True;self.err('CONTRACT_SCHEMA',lambda:self.gc(lid,encode(v)))
    def test_wrong_lease_does_not_touch_files(self):
        lid,req=self.released();self.err(None,lambda:self.gc(h('nonexistent'),req));self.assertTrue(self.keeper.object_path(lid,next(iter(self.bundle.objects))).exists())
    def test_nonce_length_checked(self):
        lid,_=self.released();self.err('CONTRACT_SCHEMA',lambda:self.gc_request(lid,nonce=b'x'))
    def test_boolean_generation_rejected(self):
        lid,_=self.released();self.err('CONTRACT_SCHEMA',lambda:self.gc_request(lid,generation=True))

    def test_malformed_capability_in_request_builder(self):
        lid,_=self.released()
        malformed=encode({0:encode({}),1:b'S'*64})
        self.err('CONTRACT_SCHEMA',lambda:self.gc_request(lid,cap=malformed))
