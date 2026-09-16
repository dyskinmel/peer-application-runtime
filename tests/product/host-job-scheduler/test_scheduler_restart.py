import json,os,signal,subprocess,sys
from pathlib import Path
from unittest.mock import patch
from scheduler_support import SchedulerTest,h
from par_wire.codec import encode
from par_keeper.contract import authority_body
from par_keeper_service.transport import socket_identity,recover_stale
class SchedulerRestart(SchedulerTest):
    def close_handles(self):
        self.host.close();self.host=None;self.window.close();self.window=None;self.keeper.close();self.keeper=None
    def reopen_all(self,**kw):
        self.open_keeper();self.window=self.w.ReplaySpool(self.keeper,self.wroot,self.store_id);self.start_host(**kw)
    def test_prepared_job_not_selected_after_restart(self):
        self.start_host();self.submit_close();self.host.schedule(self.jid());self.tick(2);self.close_handles();self.reopen_all();self.tick(4)
        self.assertEqual(self.host.jobs.poll(self.jid())['state'],'PREPARED');self.assertEqual(self.window.phase,'OPEN');self.assertIsNone(self.host.diagnostics()['selected_job'])
    def test_unknown_journal_pauses_listeners_at_startup(self):
        self.start_host();self.submit_close();self.host.schedule(self.jid());self.tick(2)
        self.host.jobs.journal.observer=lambda e:(_ for _ in ()).throw(OSError('stop')) if e=='job.effect.before_dispatch' else None
        self.tick();self.close_handles();self.reopen_all();self.tick(4)
        self.assertEqual(self.window.phase,'OPEN');self.assertFalse(self.host.read.accepting);self.assertFalse(self.host.upload.accepting);self.assertEqual(self.host.diagnostics()['fault'],'RECONCILE_REQUIRED')
    def test_success_journal_does_not_autodispatch_after_restart(self):
        self.start_host();self.submit_close();self.host.schedule(self.jid());self.complete();self.close_handles();self.reopen_all()
        with patch.object(self.host.jobs.backend,'apply',side_effect=AssertionError('replay')):self.tick(5)
        self.assertEqual(self.window.phase,'CLOSED');self.assertTrue(self.host.read.accepting)
    def test_external_job_pin_missing_job_rejected(self):
        self.start_host();self.submit_close();pin=self.host.jobs.pin();path=self.host.jobs.journal.path(self.jid());self.host.close();self.host=None;path.unlink()
        self.err('JOB_PIN',lambda:self.start_host(expected_jobs_pin=pin));self.assertFalse(self.socket_path.exists())
    def test_child_cannot_close_or_tick_parent_scheduler(self):
        self.start_host();r,fd=os.pipe();pid=os.fork()
        if pid==0:
            os.close(r);out=[]
            for method in (lambda:self.host.tick(0),self.host.close):
                try:method();out.append('BAD')
                except Exception as e:out.append(e.code)
            os.write(fd,json.dumps(out).encode());os._exit(0)
        os.close(fd);result=os.read(r,4096);os.close(r);_,status=os.waitpid(pid,0)
        self.assertEqual(status,0);self.assertEqual(json.loads(result),['SCHEDULER_OWNER']*2);self.assertTrue(self.socket_path.exists())
    def crash(self,event):
        self.start_host();self.submit_close();self.host.schedule(self.jid());self.tick(2)
        job={'keeper_root':str(self.path),'root':str(self.wroot),'store_id':self.store_id.hex(),
             'seed':self.ks.hex(),'authority':encode(authority_body(self.keeper.authority)).hex(),'quota':self.total*3,
             'jobs':str(self.jroot),'jid':self.jid().hex(),'event':event,'read_socket':str(self.socket_path),'upload_socket':str(self.upload_path)}
        f=Path(self.tmp.name)/'scheduler-child.json';f.write_text(json.dumps(job));f.chmod(0o600);self.close_handles()
        cp=subprocess.run([sys.executable,'-I','-S',str(Path(__file__).with_name('scheduler_crash_worker.py')),str(f)],capture_output=True,timeout=15,env={'PATH':os.environ.get('PATH','')})
        self.assertEqual(cp.returncode,-signal.SIGKILL,cp.stderr.decode());self.assertEqual(json.loads(cp.stdout),{'hit':event,'pgid':os.getpgid(0)})
        for path in (self.socket_path,self.upload_path):recover_stale(path,socket_identity(path))
        self.reopen_all();initial=self.host.jobs.poll(self.jid());phase=self.window.phase
        self.tick(3);self.assertEqual(self.window.phase,phase);self.assertIsNone(self.host.diagnostics()['selected_job'])
        if initial['state']=='PREPARED':self.host.schedule(self.jid());self.complete()
        elif initial['state']=='OUTCOME_UNKNOWN':
            self.assertFalse(self.host.read.accepting);result=self.host.reconcile(self.jid())
            if result['state']=='RETRY_READY':self.host.arm_retry(self.jid());self.tick()
        self.assertEqual(self.host.jobs.poll(self.jid())['state'],'SUCCEEDED');self.assertTrue(self.host.read.accepting)

for event in ('job.executing.before_replace','job.executing.after_sync','job.effect.before_dispatch','window.close.after_sync','job.effect.after_dispatch','job.succeeded.before_replace','job.succeeded.after_sync'):
    def case(self,event=event):self.crash(event)
    setattr(SchedulerRestart,'test_sigkill_'+event.replace('.','_'),case)
