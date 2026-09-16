import dataclasses,hashlib,json,os,unittest
from fetch_support import LocalFixture,h

class PlanTests(LocalFixture,unittest.TestCase):
    def test_owned_copy(self):
        scope=list(self.local.source.scope);ds=[list(d)for d in self.descriptors]
        p=self.make_plan(scope=scope,descriptors=ds);before=p.to_bytes();scope[0]='other';ds[0][2]=1
        self.assertEqual(before,p.to_bytes());self.assertEqual(p.digest,hashlib.sha256(before).hexdigest())
    def test_roundtrip(self):
        p=self.make_plan();self.assertEqual(p,self.m.FetchPlan.from_bytes(p.to_bytes()))
    def test_frozen(self):
        p=self.make_plan()
        with self.assertRaises(dataclasses.FrozenInstanceError):p.snapshot=h('bad')
    def test_reordered_plan_has_different_identity(self):
        self.assertNotEqual(self.make_plan().digest,self.make_plan(descriptors=list(reversed(self.descriptors))).digest)
    def test_empty_explicit_plan(self):
        p=self.make_plan(descriptors=[]);self.assertEqual(p.descriptors,());self.assertEqual(self.client(p).reconcile()['state'],'COMPLETE_PENDING')
    def test_plan_contains_no_plaintext_or_private_key(self):
        raw=self.make_plan().to_bytes();self.assertNotIn(b'PUBLIC OPAQUE INPUT',raw);self.assertNotIn(self.local.s.secret,raw)
    def test_reject_trailing_bytes(self):
        with self.assertRaises(self.m.FetchError):self.m.FetchPlan.from_bytes(self.make_plan().to_bytes()+b'\x00')
    def test_reject_oversized_encoding(self):
        with self.assertRaises(self.m.FetchError):self.m.FetchPlan.from_bytes(b'x'*65537)
    def test_wrong_binding_scope(self):
        scope=self.local.source.scope;scope[2]=h('wrong')
        with self.assertRaises(self.m.FetchError):self.make_plan(scope=scope)
    def test_reject_duplicate_inner(self):
        a=list(self.descriptors[0]);b=[a[0],h('other'),a[2]]
        with self.assertRaises(self.m.FetchError):self.make_plan(descriptors=[a,b])
    def test_reject_duplicate_envelope(self):
        a=list(self.descriptors[0]);b=[h('other'),a[1],a[2]]
        with self.assertRaises(self.m.FetchError):self.make_plan(descriptors=[a,b])
    def test_byte_budget_counts_all_records(self):
        with self.assertRaises(self.m.FetchError):self.make_plan(max_bytes=sum(d[2]for d in self.descriptors)-1)
    def test_record_budget(self):
        with self.assertRaises(self.m.FetchError):self.make_plan(max_records=1)

def reject(name,key,value):
    def test(self):
        with self.assertRaises(self.m.FetchError):self.make_plan(**{key:value})
    test.__name__='test_reject_'+name;setattr(PlanTests,test.__name__,test)
for name,key,value in [('snapshot_short','snapshot',b'x'),('snapshot_mutable','snapshot',bytearray(32)),('scope_bool','scope',['a',b'a'*32,b'b'*32,True,b'c'*32,b'd'*32]),('no_descriptors','descriptors',None),('descriptor_bool_length','descriptors',[[b'a'*32,b'b'*32,True]]),('descriptor_zero','descriptors',[[b'a'*32,b'b'*32,0]]),('descriptor_oversized','descriptors',[[b'a'*32,b'b'*32,819201]]),('record_bool','max_records',True),('record_zero','max_records',0),('record_over','max_records',65),('bytes_bool','max_bytes',True),('bytes_over','max_bytes',8388609),('generation','inbox_generation','f'*31),('generation_upper','inbox_generation','F'*32),('no_binding','binding',None)]:reject(name,key,value)
