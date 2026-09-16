import unittest
from dataclasses import replace
from keeper_support import ContractTest,h
from par_keeper.contract import split,signed,capability_id
from par_keeper_repair import contract as r

class RepairContract(ContractTest):
    def req(self,**kw):
        cap=kw.pop('cap',self.cap());return r.make_request(self.p,kw.pop('seed',self.subject),cap,kw.pop('lease',h('lease')),kw.pop('generation',1),kw.pop('index',self.index),kw.pop('oids',[h('object')]),kw.pop('nonce',h('nonce')))
    def verify(self,raw,cap=None,a=None,keeper=None):return r.verify_request(self.p,a or self.a,keeper or self.pk,cap or self.cap(),raw)
    def test_signed_roundtrip(self):
        req,cap=self.verify(self.req());self.assertEqual(req[4],self.sp);self.assertEqual(req[7],self.index)
    def test_domain_separation_from_put(self):
        raw=self.req();v,_=split(raw);wrong=signed(self.p,self.subject,'request-sign',v);self.err('REPAIR_SIGNATURE',lambda:self.verify(wrong))
    def test_signature_mutation(self):
        raw=self.req();self.err('REPAIR_SIGNATURE',lambda:self.verify(raw[:-1]+bytes([raw[-1]^1])))
    def test_other_keeper_rejected(self):self.err('CAPABILITY_SCOPE',lambda:self.verify(self.req(),keeper=h('other')))
    def test_stale_authority_rejected(self):self.err('CAPABILITY_SCOPE',lambda:self.verify(self.req(),a=replace(self.a,sequence=4,head=h('new'))))
    def test_get_only_cannot_repair(self):
        cap=self.cap(methods=('get',));self.err('METHOD_DENIED',lambda:self.verify(self.req(cap=cap),cap=cap))
    def test_release_only_cannot_repair(self):
        cap=self.cap(methods=('release',));self.err('METHOD_DENIED',lambda:self.verify(self.req(cap=cap),cap=cap))
    def test_put_only_can_request_repair(self):
        cap=self.cap(methods=('put',));self.verify(self.req(cap=cap),cap=cap)
    def test_different_subject_cannot_sign(self):self.err('REPAIR_SIGNATURE',lambda:self.req(seed=h('other')))
    def test_wrong_index_rejected(self):self.err('REPAIR_SCOPE',lambda:self.verify(self.req(index=h('other-index'))))
    def test_empty_targets_rejected(self):self.err('REPAIR_TARGETS',lambda:self.req(oids=[]))
    def test_duplicate_targets_rejected(self):self.err('REPAIR_TARGETS',lambda:self.req(oids=[h('a'),h('a')]))
    def test_unsorted_targets_rejected(self):self.err('REPAIR_TARGETS',lambda:self.req(oids=sorted([h('a'),h('b')],reverse=True)))
    def test_target_count_limit(self):self.err('REPAIR_TARGETS',lambda:self.req(oids=sorted(h(str(i)) for i in range(129))))
    def test_maximum_target_count(self):self.verify(self.req(oids=sorted(h(str(i)) for i in range(128))))
    def test_generation_zero_rejected(self):self.err('CONTRACT_SCHEMA',lambda:self.req(generation=0))
    def test_generation_bool_rejected(self):self.err('CONTRACT_SCHEMA',lambda:self.req(generation=True))
    def test_nonce_type_rejected(self):self.err('CONTRACT_SCHEMA',lambda:self.req(nonce='bad'))
    def test_unknown_field_rejected(self):
        v,_=split(self.req());v[10]=0;self.err('CONTRACT_SCHEMA',lambda:self.verify(signed(self.p,self.subject,'repair-request-sign',v)))
    def test_mutated_grant_id_rejected(self):
        v,_=split(self.req());v[3]=h('bad');self.err('REPAIR_SCOPE',lambda:self.verify(signed(self.p,self.subject,'repair-request-sign',v)))
    def test_cancel_requires_release_permission(self):
        cap=self.cap(methods=('put',));raw=r.make_cancel(self.p,self.subject,cap,h('lease'),h('job'),h('nonce'))
        self.err('METHOD_DENIED',lambda:r.verify_cancel(self.p,self.a,self.pk,cap,raw))
    def test_cancel_roundtrip(self):
        cap=self.cap();raw=r.make_cancel(self.p,self.subject,cap,h('lease'),h('job'),h('nonce'));v,_=r.verify_cancel(self.p,self.a,self.pk,cap,raw);self.assertEqual(v[6],h('job'))
    def test_cancel_wrong_signer(self):self.err('REPAIR_SIGNATURE',lambda:r.make_cancel(self.p,h('wrong'),self.cap(),h('lease'),h('job'),h('nonce')))
    def test_cancel_cannot_be_used_as_repair(self):
        cap=self.cap();raw=r.make_cancel(self.p,self.subject,cap,h('lease'),h('job'),h('nonce'));self.err('CONTRACT_SCHEMA',lambda:self.verify(raw))
    def test_job_identity_is_nonce_bound(self):
        a,_=split(self.req());b,_=split(self.req(nonce=h('two')));self.assertNotEqual(r.job_id(a),r.job_id(b))
