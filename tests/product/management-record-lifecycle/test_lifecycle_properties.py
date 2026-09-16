"""Deterministic generated traces; no third-party property framework required."""
import copy,itertools,json,random,subprocess,sys,tempfile
from pathlib import Path
from lifecycle_support import ModelTest,fixture,record,hx

class PropertyTests(ModelTest):
    def test_generated_closed_generation_replays(self):
        for seed in range(32):
            rng=random.Random(seed);m=self.compacted();m.open_next(controller_revision=1)
            for i in range(12):
                r=record('job',f'{seed}-{i}','CANCELLED');old=m.checkpoint()
                gen=rng.choice([1,2,3])
                if gen==2:m.admit(r,generation=gen,controller_revision=1)
                else:
                    self.err('GENERATION_CLOSED' if gen==1 else 'GENERATION',lambda:m.admit(r,generation=gen,controller_revision=1))
                    self.assertEqual(m.checkpoint(),old)
            m.close(m.plan(),controller_revision=1);m.archive();m.compact()
            restored=self.api.LifecycleModel.restore(m.checkpoint(),expected_pin=m.pin());self.assertEqual(restored.view(),m.view())
    def test_generated_bad_orders_are_atomic(self):
        for seed in range(24):
            rng=random.Random(seed);m=self.model()
            for i in range(16):
                before=m.checkpoint();action=rng.choice(['archive','compact','open_next'])
                try:getattr(m,action)(controller_revision=1) if action=='open_next' else getattr(m,action)()
                except self.api.LifecycleError:self.assertEqual(m.checkpoint(),before)
            self.assertEqual(m.view()['phase'],'OPEN')
    def test_generated_proof_mutations_change_digest(self):
        v=fixture();original=self.api.plan(v)['inventory_digest']
        for r in v['records']:
            for field in ('proof_digest','input_digest'):
                w=copy.deepcopy(v);next(x for x in w['records'] if x['key']==r['key'])[field]=hx(r['key']+field)
                self.assertNotEqual(self.api.plan(w)['inventory_digest'],original)
    def test_input_permutations_normalize_only_explicitly(self):
        v=fixture();base=self.api.encode_inventory(v)
        for perm in itertools.permutations(v['records']):
            w=copy.deepcopy(v);w['records']=list(perm)
            if w['records']!=v['records']:self.err('SCHEMA',lambda:self.api.encode_inventory(w))
            w['records'].sort(key=lambda r:r['key']);self.assertEqual(self.api.encode_inventory(w),base)
    def test_checkpoint_prefixes_resolve_same_records(self):
        m=self.model();pins=[m.pin()]
        for fn in (lambda:m.close(m.plan(),controller_revision=1),m.archive,m.compact,lambda:m.open_next(controller_revision=1)):
            fn();pins.append(m.pin())
        for p in pins:
            r=self.api.LifecycleModel.restore(m.checkpoint(),expected_pin=p)
            for row in fixture()['records']:self.assertEqual(r.resolve(row['key']),row)
    def test_unknown_record_enum_fails_closed(self):
        for kind in ('job','control','submission'):
            for state in ('ARCHIVED','DONE','PASS','',True,None,1):
                v=fixture();next(r for r in v['records'] if r['kind']==kind)['state']=state
                self.err('SCHEMA',lambda:self.api.encode_inventory(v))
    def test_model_checkpoint_new_process(self):
        m=self.archived();root=Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(prefix='par-lifecycle-') as tmp:
            ck=Path(tmp)/'model.json';pin=Path(tmp)/'pin.json';ck.write_bytes(m.checkpoint());pin.write_text(json.dumps(m.pin()))
            code="import sys,json;sys.path.insert(0,sys.argv[1]);from par_record_lifecycle import LifecycleModel;from pathlib import Path;m=LifecycleModel.restore(Path(sys.argv[2]).read_bytes(),expected_pin=json.loads(Path(sys.argv[3]).read_text()));print(json.dumps(m.view()))"
            p=subprocess.run([sys.executable,'-I','-S','-c',code,str(root/'experiments/management-record-lifecycle'),str(ck),str(pin)],capture_output=True,text=True,timeout=15)
            self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(json.loads(p.stdout),m.view())
    def test_succeeded_without_proof_reference_rejected(self):
        v=fixture();next(r for r in v['records'] if r['kind']=='job')['refs']=[]
        self.err('SCHEMA',lambda:self.api.encode_inventory(v))
    def test_registered_submission_wrong_job_digest_rejected(self):
        v=fixture();s=next(r for r in v['records'] if r['kind']=='submission');s['evidence_digest']=hx('wrong')
        self.err('REFERENCE_MISMATCH',lambda:self.api.encode_inventory(v))
    def test_allocation_estimates_are_not_deletion_authority(self):
        p=self.api.plan(fixture());self.assertTrue(p['model_ready']);self.assertFalse(p['real_deletion_allowed'])
    def test_same_generation_check_is_not_signature_verification(self):
        m=self.compacted();self.assertEqual(m.view()['scope'],'PURE_NON_DESTRUCTIVE_MODEL')
