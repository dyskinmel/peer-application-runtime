"""Death between two durability domains; never assert hardware or CRDT safety."""
import dataclasses,json,os,signal,subprocess,sys,unittest
from pathlib import Path
import test_intent_coordinator as fixtures
from anchored_process_support import open_anchored_runtime
from product.wp09.par_application_intent import LocalPinStore,AnchoredApplication
from harness.common import clean_env

class AnchorProcessTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.IntentCoordinatorTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        f=self.f;store=LocalPinStore.create(f.root.parent/'anchor',AnchoredApplication.binding(f.c),f.j.pin());store.close()
        self.config={'database':str(f.root),'plan':f.plan.to_bytes().hex(),'target':f.target.hex(),'pin':dataclasses.asdict(f.j.pin())}
        self.path=f.root.parent/'anchor-fixture.json';self.path.write_text(json.dumps(self.config));self.path.chmod(0o600)
        f.j.close();f.box.close();f.close()
    def child(self,stage):
        cp=subprocess.run([sys.executable,'-I','-S','-B',str(Path(__file__).with_name('anchor_crash_worker.py')),str(self.path),stage],capture_output=True,timeout=30,env=clean_env())
        self.assertEqual(cp.returncode,0 if stage=='complete' else -signal.SIGKILL,cp.stdout.decode()+cp.stderr.decode())
        v=json.loads(cp.stdout)
        if stage!='complete':self.assertEqual(v['killed_at'],stage);self.assertEqual(v['pgid'],os.getpgrp())
        return v
    def reopen(self):
        f=open_anchored_runtime(self.config);self.addCleanup(f.doCleanups);return f
    def test_prepared_pin_survives_kill(self):
        self.child('after-prepare-pin');f=self.reopen();self.assertEqual(f.j.status()['state'],'PREPARED');self.assertEqual(f.anchor.load(),f.j.pin());self.assertEqual(f.port.calls,0)
    def test_dispatch_ahead_of_pin_reopens_inquiry_only(self):
        self.child('before-dispatch-pin');f=self.reopen();self.assertEqual(f.j.status()['state'],'DISPATCHED');self.assertEqual(f.anchor.load(),f.j.pin())
        self.assertEqual(f.d.inquire(f.j.current.digest)['operationState'],'NOT_OBSERVED')
        with self.assertRaisesRegex(Exception,'INQUIRY_REQUIRED'):f.d.execute(f.j.current.digest,expected_observation=f.c.observe()['revision'])
        self.assertEqual(f.port.calls,0);self.assertEqual(f.nums()['document_apply_nonces'],0)
    def test_dispatch_pin_survives_before_effect(self):
        self.child('after-dispatch-pin');f=self.reopen();self.assertEqual(f.j.status()['state'],'DISPATCHED');self.assertEqual(f.port.calls,0);self.assertEqual(f.nums()['document_apply_events'],0)
    def test_partial_pin_blocks_open_not_empty(self):
        self.child('partial-dispatch-pin')
        with self.assertRaisesRegex(Exception,'PIN_STORE_UNCERTAIN'):self.reopen()
        self.assertTrue((self.f.root.parent/'anchor'/'pending.json').is_file())
    def test_commit_response_loss_is_one_event_no_replay(self):
        self.child('commit-response-loss');f=self.reopen();f.app._core=None
        r=f.d.inquire(f.j.current.digest);self.assertEqual(r['state'],'OBSERVED');self.assertEqual(f.port.calls,0)
        self.assertEqual(f.nums()['document_apply_events'],1);self.assertEqual(f.nums()['document_apply_nonces'],1);self.assertEqual(f.anchor.load(),f.j.pin())
    def test_retirement_pin_and_tombstone_survive_kill(self):
        self.child('after-retire-pin');f=self.reopen();self.assertEqual(f.j.status()['state'],'RETIRED');self.assertEqual(f.anchor.load(),f.j.pin())
        with self.assertRaisesRegex(Exception,'INQUIRY_REQUIRED'):f.d.execute(f.j.current.digest,expected_observation=f.c.observe()['revision'])
        self.assertEqual(f.port.calls,0)
    def test_normal_control_one_event_one_nonce(self):
        r=self.child('complete');self.assertEqual(r['state'],'RETIRED');self.assertTrue(r['anchor_matches']);self.assertFalse(r['real_core_executed'])
        f=self.reopen();self.assertEqual(f.nums()['document_apply_events'],1);self.assertEqual(f.nums()['document_apply_nonces'],1);self.assertTrue(f.db.audit()['valid'])
