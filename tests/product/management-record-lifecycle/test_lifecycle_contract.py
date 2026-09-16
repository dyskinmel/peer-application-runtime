import copy,json
from lifecycle_support import ModelTest,fixture,record,hx

class ContractTests(ModelTest):
    def test_inventory_roundtrip(self):
        v=fixture();self.assertEqual(self.api.decode_inventory(self.api.encode_inventory(v)),v)
    def test_canonical_order(self):
        v=fixture();self.assertEqual(self.api.encode_inventory(v),self.api.encode_inventory(dict(reversed(list(v.items())))))
    def test_unknown_field(self):
        v=fixture();v['dangerous']=True;self.err('SCHEMA',lambda:self.api.encode_inventory(v))
    def test_bool_revision_rejected(self):
        v=fixture();v['controller_revision']=True;self.err('SCHEMA',lambda:self.api.encode_inventory(v))
    def test_bad_hex(self):
        v=fixture();v['keeper']='../secrets';self.err('SCHEMA',lambda:self.api.encode_inventory(v))
    def test_record_key_binding(self):
        v=fixture();v['records'][0]['local_id']=hx('other');self.err('SCHEMA',lambda:self.api.encode_inventory(v))
    def test_unknown_state(self):
        v=fixture();v['records'][0]['state']='ARCHIVED';self.err('SCHEMA',lambda:self.api.encode_inventory(v))
    def test_negative_budget(self):
        v=fixture();v['records'][0]['storage_bytes']=-1;self.err('SCHEMA',lambda:self.api.encode_inventory(v))
    def test_duplicate_records(self):
        v=fixture();v['records'].append(copy.deepcopy(v['records'][0]));self.err('SCHEMA',lambda:self.api.encode_inventory(v))
    def test_missing_reference(self):
        v=fixture();v['records']=[r for r in v['records'] if r['kind']!='job'];self.err('DANGLING_REFERENCE',lambda:self.api.encode_inventory(v))
    def test_missing_anchor(self):
        v=fixture();v['anchors']=[];self.err('DANGLING_REFERENCE',lambda:self.api.encode_inventory(v))
    def test_duplicate_refs(self):
        v=fixture();v['records'][0]['refs']*=2;self.err('SCHEMA',lambda:self.api.encode_inventory(v))
    def test_evidence_is_not_job_success(self):
        v=fixture();j=next(r for r in v['records'] if r['kind']=='job');j['evidence_digest']=None
        self.err('SCHEMA',lambda:self.api.encode_inventory(v))
    def test_control_acceptance_is_not_job_success(self):
        v=fixture();j=next(r for r in v['records'] if r['kind']=='job');j.update(state='QUEUED',evidence_digest=None)
        p=self.api.plan(v);self.assertIn('NONTERMINAL:'+j['key'],p['blockers']);self.assertFalse(p['model_ready'])
    def test_live_gates_cannot_be_claimed(self):
        v=fixture();v['source']='LIVE_READONLY';self.err('SCHEMA',lambda:self.api.encode_inventory(v))
    def test_live_snapshot_blocks_compaction(self):
        v=fixture();v['source']='LIVE_READONLY';v['gates']={k:False for k in v['gates']}
        p=self.api.plan(v);self.assertFalse(p['model_ready']);self.assertFalse(p['real_deletion_allowed']);self.assertEqual(len([x for x in p['blockers'] if x.startswith('UNMIGRATED:')]),4)
    def test_property_read_only_plan(self):
        v=fixture();old=copy.deepcopy(v);p=self.api.plan(v);self.assertEqual(v,old);self.assertFalse(p['real_deletion_allowed']);self.assertEqual(p['record_count'],3)
    def test_archive_size_budget(self):
        p=self.api.plan(fixture(),archive_limit=2999);self.assertIn('ARCHIVE_BUDGET',p['blockers'])
    def test_unknown_outcome_blocks(self):
        v=fixture();c=next(r for r in v['records'] if r['kind']=='control');c['state']='OUTCOME_UNKNOWN'
        self.assertIn('NONTERMINAL:'+c['key'],self.api.plan(v)['blockers'])
    def test_payload_retirement_required(self):
        v=fixture();s=next(r for r in v['records'] if r['kind']=='submission');s.update(state='REGISTERED',reserved_bytes=100)
        self.assertIn('NONTERMINAL:'+s['key'],self.api.plan(v)['blockers'])
    def test_alias_rejected(self):
        v=fixture();j=copy.deepcopy(next(r for r in v['records'] if r['kind']=='job'));j['key']='job:'+hx('alias');j['local_id']=hx('alias');v['records']=sorted(v['records']+[j],key=lambda r:r['key'])
        self.err('INTENT_ALIAS',lambda:self.api.encode_inventory(v))
    def test_json_duplicate_key_rejected(self):
        self.err('SCHEMA',lambda:self.api.decode_inventory(b'{"schema":1,"schema":1}'))
    def test_size_limit_before_decode(self):
        self.err('CAPACITY',lambda:self.api.decode_inventory(b' '*(2*1024*1024+1)))
    def test_no_unknown_result_flag(self):
        p=self.api.plan(fixture());self.assertFalse(p['product_qualified']);self.assertEqual(p['scope'],'LOCAL_MODEL_AND_INVENTORY_ONLY')
    def test_generationless_legacy_always_blocked(self):
        v=fixture();v['gates']['control']=False;self.assertIn('UNMIGRATED:control',self.api.plan(v)['blockers'])
