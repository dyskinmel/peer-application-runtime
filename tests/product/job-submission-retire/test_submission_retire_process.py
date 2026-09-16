from pathlib import Path
from host_process_support import ProcessTest,ROOT
from par_job_submit.client import Client
from par_job_control.client import Client as ControlClient
from par_job_submit import protocol as c
from submission_retire_support import h
class RetirementHostProcess(ProcessTest):
    def setUp(self):
        super().setUp();self.jroot=Path(self.tmp.name)/'retire-jobs';self.cr=Path(self.tmp.name)/'retire-control';self.sroot=Path(self.tmp.name)/'retire-submission'
        self.cpath=self.socket_dir/'ctl.sock';self.spath=self.socket_dir/'sub.sock';self.os=h('retire-process-operator');self.op=self.p.sign_public(self.os);self.jid=h('retire-process-job')
    def host_args(self):
        a=super().host_args();a[a.index(str(ROOT/'tools/keeper_window_host.py'))]=str(ROOT/'tools/keeper_retiring_submit_host.py')
        return a+['--jobs',str(self.jroot),'--control-state',str(self.cr),'--control-socket',str(self.cpath),'--control-public',self.op.hex(),'--control-revision','1','--submit-socket',str(self.spath),'--submissions',str(self.sroot)]
    def test_separate_process_register_select_and_schema2(self):
        archive,command=self.proposed();payload=c.pack_job('close',command,archive);self.start_host()
        client=Client(self.spath,self.p,self.kp,self.store_id,self.os,1);context=client.call('context')
        desc=client.descriptor(payload,self.jid,bytes.fromhex(context['target_digest']));client.stage(payload,desc)
        self.assertEqual(client.call('submit',desc)['state'],'REGISTERED')
        control=ControlClient(self.cpath,self.p,self.kp,self.store_id,self.os,1)
        self.assertIsNone(control.call('status',self.jid)['host']['selected_job']);control.call('select',self.jid,h('select'))
        for _ in range(50):
            v=control.call('status',self.jid)
            if v['job']['state']=='SUCCEEDED':break
        self.assertEqual(v['job']['state'],'SUCCEEDED');self.assertEqual(c.load((self.sroot/'CONFIG.cbor').read_bytes(),4096)[0],2)
    def test_separate_process_upload_read_source_removed_recovery(self):
        self.start_host();lid,_=self.send_bundle();oid=sorted(self.bundle.objects)[0]
        self.assertEqual(self.client.fetch(lid,oid),self.bundle.objects[oid])
        job=self.job();expected=self.remove_donor();result=self.run_receiver(job)
        self.assertEqual(result['sha256'],expected);self.assertFalse(result['status']['writable'])
