import json,os,signal,subprocess,sys
from pathlib import Path
from unittest.mock import patch
from inbox_support import InboxTest
from par_wire.codec import encode

STAGES=['inbox.before_write','inbox.after_write','inbox.after_file_sync','inbox.before_publish','inbox.after_publish','inbox.after_dirsync','inbox.before_receipt']
WORKER=Path(__file__).with_name('inbox_worker.py')
class CrashTests(InboxTest):
    def killed(self,stage):
        self.create();a=self.change();base=self.root.parent;(base/'receive-input.cbor').write_bytes(encode(list(a)));self.close_box();self.close()
        cp=subprocess.run([sys.executable,'-I','-S',str(WORKER),str(base),stage],capture_output=True,text=True,timeout=15)
        self.assertEqual(cp.returncode,-signal.SIGKILL,cp.stderr);self.assertEqual(json.loads(cp.stdout)['stage'],stage);self.assertEqual(json.loads(cp.stdout)['pgid'],os.getpgrp())
        self.reopen();self.db.reactivate(self.s.space,self.s.devices[0]['secret']);self.reopen_box()
        count=1 if STAGES.index(stage)>=4 else 0;self.assertEqual(self.box.usage()['records'],count)
        r=self.receive(a);self.assertTrue(r['inboxStored']);self.assertFalse(r['applied']);self.assertEqual(self.box.usage()['records'],1);self.assertEqual(self.count('envelopes'),0)
    def test_fresh_process_reads_without_automatic_core_execution(self):
        self.create();a=self.change();self.receive(a);base=self.root.parent;(base/'receive-input.cbor').write_bytes(encode(list(a)));self.close_box();self.close()
        cp=subprocess.run([sys.executable,'-I','-S',str(WORKER),str(base),'inspect'],capture_output=True,text=True,timeout=15)
        self.assertEqual(cp.returncode,0,cp.stderr);s=json.loads(cp.stdout);self.assertEqual(s['state'],'READY_FOR_CORE');self.assertFalse(s['applied']);self.assertFalse(s['innerValidated'])
    def test_after_publish_failure_requires_reopen_and_preserves_id(self):
        self.create();a=self.change()
        def fail(stage):
            if stage=='inbox.after_publish':raise OSError('response lost')
        self.box.observer=fail;self.bad('INBOX_OUTCOME_UNKNOWN',lambda:self.receive(a));self.bad('INBOX_OUTCOME_UNKNOWN',self.box.usage)
        self.reopen_box();r=self.receive(a);self.assertEqual(r['envelopeId'],self.eid(a[0]).hex());self.assertEqual(self.box.usage()['records'],1)
    def test_write_failure_never_acknowledged(self):
        self.create();a=self.change()
        def fail(stage):
            if stage=='inbox.after_write':raise OSError('full')
        self.box.observer=fail;self.bad('INBOX_WRITE_FAILED',lambda:self.receive(a));self.assertEqual(self.box.usage()['records'],0)
    def test_rename_failure_never_publishes(self):
        self.create();a=self.change()
        with patch('product.wp04.inbox.os.rename',side_effect=OSError('rename failed')):self.bad('INBOX_WRITE_FAILED',lambda:self.receive(a))
        self.assertEqual(self.box.usage()['records'],0)
    def test_real_fork_refuses_parent_inbox_and_does_not_unlock(self):
        self.create();pid=os.fork()
        if pid==0:
            try:self.box.usage()
            except Exception as e:os._exit(0 if getattr(e,'code',None)=='WRONG_OWNER' else 2)
            os._exit(3)
        _,status=os.waitpid(pid,0);self.assertEqual(os.waitstatus_to_exitcode(status),0)
        self.bad('INBOX_BUSY',lambda:self.cls.open(self.path,self.db,**self.scope));self.assertEqual(self.box.usage()['records'],0)
for index,stage in enumerate(STAGES):
    def case(self,stage=stage):self.killed(stage)
    setattr(CrashTests,'test_sigkill_%02d_%s'%(index,stage.replace('.','_')),case)
