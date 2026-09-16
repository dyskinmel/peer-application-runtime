import json,os,signal,subprocess,sys
from pathlib import Path
from host_process_support import ProcessTest,ROOT
from par_job_submit.client import Client as SubmitClient
from par_job_control.client import Client as JobClient
from par_job_submit import protocol as s
from par_submit_retire import contract as r
from par_keeper_service.transport import socket_identity,recover_stale
from retire_control_support import h
class ControlProcess(ProcessTest):
    def setUp(self):
        super().setUp()
        from par_submit_retire_control.client import Client
        self.ControlClient=Client;self.fault=None
        self.jroot=Path(self.tmp.name)/'jobs';self.cr=Path(self.tmp.name)/'controller';self.sroot=Path(self.tmp.name)/'submissions'
        self.cpath=self.socket_dir/'ctl.sock';self.spath=self.socket_dir/'sub.sock';self.os=h('rc-process-op');self.op=self.p.sign_public(self.os);self.jid=h('rc-process-job')
    def host_args(self):
        a=super().host_args();i=a.index(str(ROOT/'tools/keeper_window_host.py'))
        a[i]=str(ROOT/'tools/keeper_retire_control_host.py')
        if self.fault is not None:a[i:i+1]=[str(Path(__file__).with_name('retire_control_fault_host.py')),self.fault]
        return a+['--jobs',str(self.jroot),'--control-state',str(self.cr),'--control-socket',str(self.cpath),'--control-public',self.op.hex(),'--control-revision','1','--submit-socket',str(self.spath),'--submissions',str(self.sroot)]
    def setup_stage(self,registered=False):
        archive,command=self.proposed();payload=s.pack_job('close',command,archive);self.start_host()
        old=SubmitClient(self.spath,self.p,self.kp,self.store_id,self.os,1)
        d=old.descriptor(payload,self.jid,bytes.fromhex(old.call('context')['target_digest']))
        if registered:old.stage(payload,d);old.call('submit',d)
        else:old.call('begin',d);old.call('chunk',d,0,payload[:17])
        cli=self.ControlClient(self.spath,self.p,self.kp,self.store_id,self.os,1)
        prop=cli.call('proposal',d)['proposal'];q=r.make_request(self.p,self.os,self.os,revision=1,nonce=h('retire-control'),**prop)
        return old,cli,d,q
    def test_separate_process_retires_then_accepts_other_registration(self):
        old,cli,d,q=self.setup_stage();v=cli.call('retire',d,q)
        self.assertEqual(v['retirement']['state'],'TOMBSTONED');self.assertEqual(cli.call('retire',d,q),v)
        self.err(None,lambda:old.call('begin',d))
        payload=s.pack_job('open',self.grant);nd=old.descriptor(payload,h('next-job'),bytes.fromhex(old.call('context')['target_digest']))
        self.assertEqual(old.call('begin',nd)['state'],'RECEIVING')
    def test_registered_job_survives_and_runs_from_other_client(self):
        _,cli,d,q=self.setup_stage(True);cli.call('retire',d,q)
        ctl=JobClient(self.cpath,self.p,self.kp,self.store_id,self.os,1)
        self.assertIsNone(ctl.call('status',self.jid)['host']['selected_job'])
        ctl.call('select',self.jid,h('run-once'))
        for _ in range(50):
            result=ctl.call('status',self.jid)
            if result['job']['state']=='SUCCEEDED':break
        self.assertEqual(result['job']['state'],'SUCCEEDED');self.assertEqual(cli.call('status',d)['retirement']['state'],'TOMBSTONED')
    def test_real_recovery_still_works(self):
        self.start_host();lid,_=self.send_bundle();oid=sorted(self.bundle.objects)[0]
        self.assertEqual(self.client.fetch(lid,oid),self.bundle.objects[oid])
        job=self.job();expect=self.remove_donor();v=self.run_receiver(job)
        self.assertEqual(v['sha256'],expect);self.assertFalse(v['status']['writable'])
    def test_client_does_not_fallback_to_old_profile(self):
        old_args=self.host_args
        def legacy():
            a=old_args();a[a.index(str(ROOT/'tools/keeper_retire_control_host.py'))]=str(ROOT/'tools/keeper_retiring_submit_host.py');return a
        self.host_args=legacy
        archive,cmd=self.proposed();payload=s.pack_job('close',cmd,archive);self.start_host()
        old=SubmitClient(self.spath,self.p,self.kp,self.store_id,self.os,1);d=old.descriptor(payload,self.jid,bytes.fromhex(old.call('context')['target_digest']));old.call('begin',d)
        cli=self.ControlClient(self.spath,self.p,self.kp,self.store_id,self.os,1)
        self.err(None,lambda:cli.call('status',d));self.assertEqual(old.call('progress',d)['received'],0)
    def test_cli_proposal_sign_and_retire(self):
        _,cli,d,_=self.setup_stage();df=Path(self.tmp.name)/'descriptor';df.write_bytes(d);df.chmod(0o600)
        pf=Path(self.tmp.name)/'proposal';af=Path(self.tmp.name)/'approval'
        base=[sys.executable,'-I','-S',str(ROOT/'tools/keeper_retire_control_client.py'),'--socket',str(self.spath),'--keeper',self.kp.hex(),'--store',self.store_id.hex(),'--revision','1','--key-fd','0','--descriptor',str(df),'--allow-legacy-sodium']
        def call(action,extra=(),seeds=None):
            cp=subprocess.run(base+['--action',action]+list(extra),input=seeds or self.os,capture_output=True,timeout=10)
            self.assertEqual(cp.returncode,0,cp.stderr.decode());return json.loads(cp.stdout)
        call('proposal',['--output',str(pf)])
        # Distinct file descriptors are required, even if role keys coincide.
        seedfile=Path(self.tmp.name)/'synthetic-seed';seedfile.write_bytes(self.os);seedfile.chmod(0o600)
        with seedfile.open('rb') as f:
            cp=subprocess.run(base+['--action','approve','--proposal',str(pf),'--origin-key-fd',str(f.fileno()),'--output',str(af)],input=self.os,capture_output=True,pass_fds=(f.fileno(),),timeout=10)
        self.assertEqual(cp.returncode,0,cp.stderr.decode());self.assertTrue(af.exists())
        self.assertEqual(call('retire',['--authorization',str(af)])['retirement']['state'],'TOMBSTONED')
    def crash(self,point):
        self.fault=point;_,cli,d,q=self.setup_stage();ids={p:socket_identity(p) for p in (self.socket_path,self.upload_path,self.cpath,self.spath)}
        self.err('OUTCOME_UNKNOWN',lambda:cli.call('retire',d,q));self.process.wait(timeout=10)
        self.assertEqual(self.process.returncode,-signal.SIGKILL)
        marker=json.loads(self.process.stdout.readline());self.assertEqual(marker,{'hit':point,'pgid':os.getpgrp()})
        self.stop_process()
        for path,identity in ids.items():recover_stale(path,identity)
        self.fault=None;self.start_host()
        v=cli.call('status',d);self.assertIn(v['retirement']['state'],r.PHASES)
        self.assertEqual(cli.call('retire',d,q)['retirement']['state'],'TOMBSTONED')
        self.assertEqual(len(list(self.socket_dir.glob('*.sock'))),4)
for point in ('submit.retire_intent.after_sync','submit.retire.before_unlink','submit.retire.after_unlink',
              'submit.retire.after_payload_sync','submit.retire_removed.after_sync','submit.retire.before_release','submit.retire_tombstone.after_sync'):
    def case(self,p=point):self.crash(p)
    setattr(ControlProcess,'test_sigkill_'+point.replace('.','_'),case)
