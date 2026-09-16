"""Real subprocess death and original-ID recovery; all positive core is synthetic."""
import dataclasses,json,signal,subprocess,sys,unittest
from pathlib import Path
import test_intent_coordinator as fixtures
from process_support import open_runtime
from harness.common import clean_env

class IntentProcessTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.IntentCoordinatorTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        f=self.f
        self.config={'database':str(f.root),'plan':f.plan.to_bytes().hex(),'target':f.target.hex(),
                     'pin':dataclasses.asdict(f.j.pin())}
        self.path=f.root.parent/'fixture.json';self.path.write_text(json.dumps(self.config));self.path.chmod(0o600)
        f.j.close();f.box.close();f.close()
    def run_child(self,stage):
        cp=subprocess.run([sys.executable,'-I','-S','-B',str(Path(__file__).with_name('intent_crash_worker.py')),
            str(self.path),stage],capture_output=True,timeout=30,env=clean_env())
        if stage=='complete':
            self.assertEqual(cp.returncode,0,cp.stderr.decode());return json.loads(cp.stdout)
        self.assertEqual(cp.returncode,-signal.SIGKILL,cp.stdout.decode()+cp.stderr.decode())
        self.assertIn('KILL_BOUNDARY:'+stage,cp.stdout.decode())
    def reopen(self):
        f=open_runtime(self.config);self.addCleanup(f.doCleanups);return f
    def test_prepare_fsync_restart_is_prepared_not_dispatched(self):
        self.run_child('prepare-synced');f=self.reopen()
        self.assertEqual(f.j.status()['state'],'PREPARED');self.assertEqual(f.nums()['document_apply_nonces'],0)
        self.assertEqual(f.d.inquire(f.j.current.digest)['operationState'],'NOT_OBSERVED')
        self.assertEqual(f.d.abandon(f.j.current.digest)['state'],'ABANDONED')
    def test_dispatch_fsync_restart_never_replays_absent_row(self):
        self.run_child('dispatch-synced');f=self.reopen()
        self.assertEqual(f.d.inquire(f.j.current.digest)['operationState'],'NOT_OBSERVED')
        self.assertEqual(f.j.status()['state'],'DISPATCHED');self.assertEqual(f.nums()['document_apply_nonces'],0)
        with self.assertRaisesRegex(Exception,'INQUIRY_REQUIRED'):
            f.d.execute(f.j.current.digest,expected_observation=f.c.observe()['revision'])
        self.assertEqual(f.port.calls,0)
    def test_nonce_fsync_restart_no_new_nonce_or_replay(self):
        self.run_child('apply.nonce_after_commit');f=self.reopen()
        self.assertEqual(f.nums()['document_apply_nonces'],1);self.assertEqual(f.nums()['document_apply_events'],0)
        self.assertEqual(f.d.inquire(f.j.current.digest)['operationState'],'NOT_OBSERVED')
        with self.assertRaisesRegex(Exception,'INQUIRY_REQUIRED'):
            f.d.execute(f.j.current.digest,expected_observation=f.c.observe()['revision'])
        self.assertEqual(f.nums()['document_apply_nonces'],1);self.assertEqual(f.port.calls,0)
    def test_commit_response_loss_restart_reads_original_row_without_core(self):
        self.run_child('apply.after_commit');f=self.reopen();f.app._core=None
        value=f.d.inquire(f.j.current.digest)
        self.assertEqual(value['state'],'OBSERVED');self.assertEqual(value['operationId'],(b'o'*16).hex())
        self.assertEqual(f.nums()['document_apply_events'],1);self.assertEqual(f.nums()['document_apply_nonces'],1)
        self.assertEqual(f.port.calls,0);self.assertFalse(value['applied']);self.assertFalse(value['acknowledged'])
        self.assertEqual(f.d.retire(f.j.current.digest)['state'],'RETIRED')
    def test_readable_observation_reopened_and_resynced(self):
        self.run_child('observe-written');f=self.reopen()
        self.assertEqual(f.j.status()['state'],'OBSERVED');pin=f.j.pin()
        self.assertEqual(f.d.inquire(f.j.current.digest)['state'],'OBSERVED')
        self.assertEqual(f.j.pin(),pin);self.assertEqual(f.port.calls,0)
    def test_observed_fsync_restart_keeps_original_receipt(self):
        self.run_child('observe-synced');f=self.reopen()
        self.assertEqual(f.j.status()['state'],'OBSERVED');self.assertEqual(f.nums()['document_apply_events'],1)
        self.assertEqual(f.d.inquire(f.j.current.digest)['state'],'OBSERVED');self.assertEqual(f.port.calls,0)
    def test_retire_fsync_restart_keeps_tombstone(self):
        self.run_child('retire-synced');f=self.reopen()
        self.assertEqual(f.j.status()['state'],'RETIRED');self.assertEqual(f.nums()['document_apply_events'],1)
        with self.assertRaisesRegex(Exception,'OPERATION_RETIRED'):f.j.prepare(f.j.current)
        self.assertEqual(f.d.inquire(f.j.current.digest)['state'],'RETIRED');self.assertEqual(f.port.calls,0)
    def test_partial_prepare_file_never_becomes_empty(self):
        self.run_child('prepare-created')
        # This scope intentionally does not trim an incomplete event. It blocks.
        with self.assertRaisesRegex(Exception,'CORRUPT'):self.reopen()
    def test_complete_child_restart_can_only_read_retired_history(self):
        result=self.run_child('complete');self.assertTrue(result['synthetic_core'])
        f=self.reopen();self.assertEqual(f.j.status()['state'],'RETIRED')
        self.assertEqual(f.d.inquire(f.j.current.digest)['operationState'],'OBSERVED_APPLICATION_RECORD')
        self.assertEqual(f.port.calls,0);self.assertTrue(f.db.audit()['valid'])
