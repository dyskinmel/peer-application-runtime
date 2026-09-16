import json,os,signal,subprocess,sys,threading
from pathlib import Path
from unittest.mock import patch
from submit_support import SubmitTest,h
from par_keeper.contract import authority_body
from par_wire.codec import encode
from par_keeper_service.transport import socket_identity,recover_stale
from par_job_control.controller import Controller
class SubmitRestart(SubmitTest):
    def close_all(self):
        self.st.close();self.st=None;self.ctl.close();self.ctl=None;self.host.close();self.host=None;self.window.close();self.window=None;self.keeper.close();self.keeper=None
    def open_all(self):
        self.open_keeper();self.window=self.w.ReplaySpool(self.keeper,self.wroot,self.store_id);self.start_host();self.ctl=Controller(self.host,Path(self.tmp.name)/'controller',self.op,1);self.st=self.sm.Submissions(self.ctl,self.sroot)
    def crash(self,event,operation):
        r=self.payload();d=self.descriptor(r)
        if operation!='begin':self.st.begin(d)
        if operation=='submit':self.st.chunk(d,0,r)
        cp=self.socket_dir/'crash-control.sock'
        q={'keeper':str(self.path),'spool':str(self.wroot),'store':self.store_id.hex(),'seed':self.ks.hex(),'authority':encode(authority_body(self.keeper.authority)).hex(),'quota':self.total*3,'jobs':str(self.jroot),'journal':str(Path(self.tmp.name)/'controller'),'stage':str(self.sroot),'operator':self.op.hex(),'descriptor':d.hex(),'payload':r.hex(),'event':event,'operation':operation,'read':str(self.socket_path),'upload':str(self.upload_path),'control':str(cp)}
        f=Path(self.tmp.name)/'crash-input.json';f.write_text(json.dumps(q));f.chmod(0o600);self.close_all()
        res=subprocess.run([sys.executable,'-I','-S',str(Path(__file__).with_name('submit_crash_worker.py')),str(f)],capture_output=True,timeout=20,env={'PATH':os.environ.get('PATH','')})
        self.assertEqual(res.returncode,-signal.SIGKILL,res.stderr.decode());self.assertEqual(json.loads(res.stdout),{'hit':event,'pgid':os.getpgid(0)})
        for path in (self.socket_path,self.upload_path,cp):recover_stale(path,socket_identity(path))
        self.open_all();self.assertIsNone(self.host.selected);self.assertEqual(self.window.phase,'OPEN')
        self.st.begin(d);v=self.st.progress(d)
        if v['state']=='RECEIVING':self.st.chunk(d,v['received'],r[v['received']:]);v=self.st.progress(d)
        if v['state']=='INFLIGHT':v=self.st.reconcile(d)
        if v['state']=='RETRY_READY':v=self.st.retry(d)
        if v['state']=='READY':v=self.st.submit(d)
        self.assertEqual(v['state'],'REGISTERED');self.assertEqual(len(self.host.jobs.list()),1);self.assertEqual(self.host.jobs.poll(self.jid())['state'],'QUEUED');self.assertIsNone(self.host.selected)
    def test_fsync_failure_does_not_register(self):
        d,r=self.ready()
        with patch('par_job_submit.staging.os.fsync',side_effect=OSError('synthetic fault')):self.err(None,lambda:self.st.submit(d))
        self.assertEqual(self.host.jobs.list(),[]);self.assertIsNone(self.host.selected);self.assertTrue(self.st.poison)
    def test_wrong_thread_refused(self):
        out=[]
        def wrong():
            try:self.st.context()
            except Exception as e:out.append(e.code)
        t=threading.Thread(target=wrong);t.start();t.join();self.assertEqual(out,['SUBMIT_OWNER'])
    def test_signed_metadata_corruption(self):
        d,r=self.ready();p=self.st._path(self.jid());data=bytearray(p.read_bytes());data[-1]^=1;p.write_bytes(data);self.err(None,lambda:self.reopen())
    def test_settings_type_not_coerced(self):
        path=self.sroot/'CONFIG.cbor';v=self.sc.load(path.read_bytes(),4096);v[0]=True;path.write_bytes(self.sc.dump(v,4096));self.err('SUBMIT_SETTINGS',lambda:self.st.context())
    def test_extra_file_refused(self):
        p=self.sroot/'foreign';p.write_bytes(b'x');p.chmod(0o600);self.err('SUBMIT_LAYOUT',lambda:self.st.context())
    def test_known_record_disappearance(self):
        d=self.descriptor();self.st.begin(d);self.st._path(self.jid()).unlink();self.err('SUBMIT_CHANGED',lambda:self.st.context())
    def test_foreign_payload_without_record(self):
        p=self.st.payload_path(h('orphan'));p.write_bytes(b'');p.chmod(0o600);self.err('SUBMIT_CHANGED',lambda:self.st.context())
    def test_inflight_reopen_does_not_submit(self):
        d,_=self.ready()
        def fail(e):
            if e=='submit.before_dispatch':raise RuntimeError('lost')
        self.st.observer=fail;self.err('SUBMIT_OUTCOME_UNKNOWN',lambda:self.st.submit(d));self.reopen()
        with patch.object(self.host.jobs,'submit',side_effect=AssertionError('automatic replay')):
            self.assertEqual(self.st.progress(d)['state'],'INFLIGHT');self.assertEqual(self.st.reconcile(d)['state'],'RETRY_READY')
    def test_registered_reopen_does_not_sign(self):
        d,_=self.ready();self.st.submit(d)
        with patch.object(self.p,'sign',side_effect=AssertionError('unexpected signing')):
            self.reopen();self.assertEqual(self.st.progress(d)['state'],'REGISTERED')

for event,operation in [
 ('submit.begin.after_replace','begin'),('submit.begin.after_sync','begin'),
 ('submit.chunk.after_payload_sync','chunk'),('submit.chunk.after_replace','chunk'),('submit.chunk.after_sync','chunk'),
 ('submit.inflight.after_sync','submit'),('submit.before_dispatch','submit'),('submit.after_dispatch','submit'),
 ('submit.registered.before_replace','submit'),('submit.registered.after_replace','submit'),('submit.registered.after_sync','submit')]:
    def case(self,e=event,o=operation):self.crash(e,o)
    setattr(SubmitRestart,'test_sigkill_'+event.replace('.','_'),case)

from host_process_support import ProcessTest,ROOT
from par_job_submit.client import Client
from par_job_control.client import Client as ControlClient
class SubmitHostProcess(ProcessTest):
    def setUp(self):
        super().setUp();self.jroot=Path(self.tmp.name)/'live-jobs';self.cr=Path(self.tmp.name)/'live-control';self.sroot=Path(self.tmp.name)/'live-submission'
        self.cpath=self.socket_dir/'control.sock';self.spath=self.socket_dir/'submit.sock';self.os=h('live-submit-operator');self.op=self.p.sign_public(self.os);self.jid=h('live-submit-job')
        self.assertTrue((ROOT/'tools/keeper_submit_host.py').exists(),'submission host CLI not implemented')
        from par_job_submit import protocol
        self.sc=protocol
    def host_args(self):
        a=super().host_args();a[a.index(str(ROOT/'tools/keeper_window_host.py'))]=str(ROOT/'tools/keeper_submit_host.py')
        return a+['--jobs',str(self.jroot),'--control-state',str(self.cr),'--control-socket',str(self.cpath),'--control-public',self.op.hex(),'--control-revision','1','--submit-socket',str(self.spath),'--submissions',str(self.sroot)]
    def submit_client(self):return Client(self.spath,self.p,self.kp,self.store_id,self.os,1)
    def control_client(self):return ControlClient(self.cpath,self.p,self.kp,self.store_id,self.os,1)
    def prep(self):
        a,q=self.proposed();return self.sc.pack_job('close',q,a)
    def transfer(self,r):
        cli=self.submit_client();v=cli.call('context');d=cli.descriptor(r,self.jid,bytes.fromhex(v['target_digest']));self.assertEqual(cli.stage(r,d)['state'],'READY');return cli,d
    def test_separate_process_registration_then_selection(self):
        r=self.prep();self.start_host();cli,d=self.transfer(r);v=cli.call('submit',d);self.assertEqual(v['state'],'REGISTERED')
        ctl=self.control_client();status=ctl.call('status',self.jid);self.assertEqual(status['job']['state'],'QUEUED');self.assertIsNone(status['host']['selected_job'])
        ctl.call('select',self.jid,h('explicit-select'))
        for _ in range(50):
            v=ctl.call('status',self.jid)
            if v['job']['state']=='SUCCEEDED':break
        self.assertEqual(v['job']['state'],'SUCCEEDED')
    def test_real_large_archive_multichunk(self):
        for _ in range(24):
            self.terminal();r=self.prep()
            if len(r)>70000:break
        self.assertGreater(len(r),65536);self.start_host();cli,d=self.transfer(r);self.assertEqual(cli.call('submit',d)['state'],'REGISTERED')
    def test_existing_upload_read_and_source_removed_recovery(self):
        self.start_host();lid,receipt=self.send_bundle();oid=sorted(self.bundle.objects)[0];self.assertEqual(self.client.fetch(lid,oid),self.bundle.objects[oid])
        job=self.job();expected=self.remove_donor();result=self.run_receiver(job);self.assertEqual(result['sha256'],expected);self.assertFalse(result['status']['writable'])
    def test_cli_prepare_stage_submit_separate_processes(self):
        r=self.prep();payload=Path(self.tmp.name)/'job.payload';payload.write_bytes(r);payload.chmod(0o600);desc=Path(self.tmp.name)/'job.desc';self.start_host()
        base=[sys.executable,'-I','-S',str(ROOT/'tools/keeper_submit_client.py'),'--socket',str(self.spath),'--keeper',self.kp.hex(),'--store',self.store_id.hex(),'--revision','1','--key-fd','0','--allow-legacy-sodium']
        def call(action,extra=()):
            p=subprocess.run(base+['--action',action]+list(extra),input=self.os,capture_output=True,timeout=15,env={'PATH':os.environ.get('PATH','')});self.assertEqual(p.returncode,0,p.stderr.decode());return json.loads(p.stdout)
        ctx=call('context');call('prepare',['--payload',str(payload),'--job-id',self.jid.hex(),'--target',ctx['target_digest'],'--output',str(desc)])
        self.assertEqual(call('stage',['--payload',str(payload),'--descriptor',str(desc)])['state'],'READY')
        self.assertEqual(call('submit',['--descriptor',str(desc)])['state'],'REGISTERED');self.assertIsNone(self.control_client().call('status',self.jid)['host']['selected_job'])
    def test_partial_upload_host_restart(self):
        r=self.prep();self.start_host();cli=self.submit_client();d=cli.descriptor(r,self.jid,bytes.fromhex(cli.call('context')['target_digest']));cli.call('begin',d);cli.call('chunk',d,0,r[:10]);self.stop_process();self.start_host()
        self.assertEqual(cli.call('progress',d)['received'],10);cli.stage(r,d);self.assertEqual(cli.call('submit',d)['state'],'REGISTERED')
