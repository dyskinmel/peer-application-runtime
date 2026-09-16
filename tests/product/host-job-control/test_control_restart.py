import json,os,signal,subprocess,sys,time
from pathlib import Path
from unittest.mock import patch
from control_support import ControlTest,h
from host_process_support import ProcessTest,ROOT
from par_management_jobs import ManagementJobs
from par_keeper.contract import authority_body
from par_wire.codec import encode
from par_keeper_service.transport import socket_identity,recover_stale
class ControlRestart(ControlTest):
    def close_handles(self):
        self.ctl.close();self.ctl=None;self.host.close();self.host=None;self.window.close();self.window=None;self.keeper.close();self.keeper=None
    def reopen(self):
        self.open_keeper();self.window=self.w.ReplaySpool(self.keeper,self.wroot,self.store_id);self.start_host();self.ctl=self.cm.Controller(self.host,self.cr,self.op,1)
    def crash(self,event):
        intent=self.intent('cancel');control_path=self.socket_dir/'ctrl.sock'
        j={'keeper_root':str(self.path),'root':str(self.wroot),'store_id':self.store_id.hex(),'seed':self.ks.hex(),
           'authority':encode(authority_body(self.keeper.authority)).hex(),'quota':self.total*3,'jobs':str(self.jroot),'journal':str(self.cr),
           'owner':self.op.hex(),'intent':intent.hex(),'event':event,'read_socket':str(self.socket_path),'upload_socket':str(self.upload_path),'control_socket':str(control_path)}
        f=Path(self.tmp.name)/'control-child.json';f.write_text(json.dumps(j));f.chmod(0o600);self.close_handles()
        cp=subprocess.run([sys.executable,'-I','-S',str(Path(__file__).with_name('control_crash_worker.py')),str(f)],capture_output=True,timeout=15,env={'PATH':os.environ.get('PATH','')})
        self.assertEqual(cp.returncode,-signal.SIGKILL,cp.stderr.decode());self.assertEqual(json.loads(cp.stdout),{'hit':event,'pgid':os.getpgid(0)})
        for path in (self.socket_path,self.upload_path,control_path):recover_stale(path,socket_identity(path))
        self.reopen();self.tick(4);self.assertIsNone(self.host.selected);self.assertEqual(self.window.phase,'OPEN')
        with patch.object(self.host,'cancel',side_effect=AssertionError('automatic replay')):
            r=self.ctl.execute(intent);self.assertIn(r['outcome'],('ACCEPTED','OUTCOME_UNKNOWN'));self.assertTrue(r['duplicate'])
        current=self.host.jobs.poll(self.jid())['state']
        self.assertIn(current,('QUEUED','CANCELLED'))
        self.call('cancel',opid=h('new-explicit-cancel'));self.assertEqual(self.host.jobs.poll(self.jid())['state'],'CANCELLED')
    def test_journal_sync_failure_blocks_dispatch(self):
        with patch('par_job_control.journal.os.fsync',side_effect=OSError('synthetic disk fault')):
            self.err('CONTROL_JOURNAL_UNCERTAIN',lambda:self.call())
        self.assertIsNone(self.host.selected);self.assertEqual(self.window.phase,'OPEN')
    def test_journal_capacity_before_effect(self):
        self.ctl.close();self.ctl=None
        # Separate private journal so there is no silent config rewrite.
        self.cr=Path(self.tmp.name)/'one-op';self.ctl=self.cm.Controller(self.host,self.cr,self.op,1,max_operations=1)
        self.call('cancel');self.err('CONTROL_CAPACITY',lambda:self.call('cancel',opid=h('two')))
    def test_expected_pin_valid_after_pending_becomes_terminal(self):
        i=self.pr.check_intent(self.p,self.kp,self.store_id,self.op,1,self.intent('cancel'))
        self.ctl.journal.start(i);pin=self.ctl.journal.pin();self.ctl.journal.finish(i,'ACCEPTED');self.assertTrue(self.ctl.journal.verify_pin(pin))
    def test_signed_record_tamper_rejected(self):
        self.call('cancel');f=next(self.cr.glob('*.op'));raw=f.read_bytes();self.ctl.close();f.write_bytes(raw[:-1]+bytes([raw[-1]^1]))
        self.err(None,lambda:self.cm.Controller(self.host,self.cr,self.op,1))
    def test_unknown_extra_file_refused(self):
        p=self.cr/'foreign';p.write_text('x');p.chmod(0o600);self.err('CONTROL_LAYOUT',lambda:self.call('status'))
    def test_foreign_thread_refused(self):
        import threading
        out=[]
        def f():
            try:self.call()
            except Exception as exc:out.append(exc.code)
        t=threading.Thread(target=f);t.start();t.join();self.assertEqual(out,['SCHEDULER_OWNER']);self.assertIsNone(self.host.selected)

for event in ('control.inflight.after_sync','control.before_dispatch','control.after_dispatch','control.result.before_replace','control.result.after_sync'):
    def case(self,event=event):self.crash(event)
    setattr(ControlRestart,'test_sigkill_'+event.replace('.','_'),case)

class ControlHostProcess(ProcessTest):
    def setUp(self):
        super().setUp();self.jroot=Path(self.tmp.name)/'control-jobs';self.cr=Path(self.tmp.name)/'control-state';self.cpath=self.socket_dir/'control.sock'
        self.os=h('process-owner-seed');self.op=self.p.sign_public(self.os);self.jid=h('process-job')
        self.assertTrue((ROOT/'tools/keeper_control_host.py').exists(),'controlled host CLI not implemented')
        a,q=self.proposed()
        with ManagementJobs(self.window,self.jroot) as jobs:jobs.submit(self.jid,action='close',command=q,archive=a)
    def host_args(self):
        a=super().host_args();a[a.index(str(ROOT/'tools/keeper_window_host.py'))]=str(ROOT/'tools/keeper_control_host.py')
        if hasattr(self,'clock_path'):
            a[a.index(str(ROOT/'tools/keeper_control_host.py')):a.index(str(ROOT/'tools/keeper_control_host.py'))+1]=[str(Path(__file__).with_name('controlled_clock_host.py')),str(self.clock_path)]
        return a+['--jobs',str(self.jroot),'--control-state',str(self.cr),'--control-socket',str(self.cpath),'--control-public',self.op.hex(),'--control-revision','1','--drain-timeout','3']
    def control(self,action='status',oid=None,seed=None):
        a=[sys.executable,'-I','-S',str(ROOT/'tools/keeper_control_client.py'),'--socket',str(self.cpath),'--keeper',self.kp.hex(),'--store',self.store_id.hex(),
           '--allow-legacy-sodium','--key-fd','0','--revision','1','--action',action,'--job',self.jid.hex()]
        if action!='status':a+=['--operation-id',(oid or h('process-'+action)).hex()]
        cp=subprocess.run(a,input=seed or self.os,capture_output=True,timeout=10,env={'PATH':os.environ.get('PATH','')})
        self.assertEqual(cp.returncode,0,cp.stderr.decode());return json.loads(cp.stdout)
    def test_live_status_and_select(self):
        self.start_host();r=self.control();self.assertEqual(r['job']['state'],'QUEUED');self.control('select')
        for _ in range(25):
            r=self.control()
            if r['job']['state']=='SUCCEEDED':break
        self.assertEqual(r['job']['state'],'SUCCEEDED')
    def test_live_control_with_incomplete_data_client(self):
        import socket
        self.clock_path=Path(self.tmp.name)/'test-clock';self.clock_path.write_text('0')
        self.start_host();s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.connect(str(self.socket_path))
        try:
            r=self.control('select');r=self.control();self.assertEqual(r['host']['mode'],'DRAINING');self.assertGreater(r['host']['connections'],0)
            # Clock is held while actual CLI processes perform select/status/cancel.
            # No production limit changes; the following case advances past 1500ms.
            r=self.control('cancel');self.assertEqual(r['job']['state'],'CANCELLED')
        finally:s.close()
    def test_data_deadline_without_cancel_completes(self):
        import socket
        self.clock_path=Path(self.tmp.name)/'test-clock';self.clock_path.write_text('0')
        self.start_host();s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.connect(str(self.socket_path))
        try:
            self.control('select');r=self.control();self.assertEqual(r['host']['mode'],'DRAINING')
            self.assertGreater(r['host']['connections'],0)
            new=self.clock_path.with_suffix('.next');new.write_text('1.6');new.replace(self.clock_path)
            for _ in range(25):
                r=self.control()
                if r['job']['state']=='SUCCEEDED':break
            self.assertEqual(r['job']['state'],'SUCCEEDED');self.assertEqual(r['host']['connections'],0)
            with self.assertRaisesRegex(AssertionError,'REMOTE_REJECTED'):self.control('cancel')
        finally:s.close()
    def test_existing_upload_read_paths(self):
        self.start_host();lid,receipt=self.send_bundle();oid=sorted(self.bundle.objects)[0]
        self.assertEqual(self.client.fetch(lid,oid),self.bundle.objects[oid]);self.assertEqual(self.control()['job']['state'],'QUEUED')
    def test_provider_removed_receiver_restores(self):
        self.start_host();lid,receipt=self.send_bundle();job=self.job();expected=self.remove_donor();result=self.run_receiver(job)
        self.assertEqual(result['sha256'],expected);self.assertFalse(result['status']['writable'])
    def test_mutation_retry_in_new_client_is_duplicate(self):
        self.start_host();r=self.control('cancel');r2=self.control('cancel');self.assertTrue(r2['duplicate']);self.assertEqual(r2['job']['state'],'CANCELLED')
