import errno,json,os,signal,subprocess,sys
from pathlib import Path
from unittest.mock import patch
from jobs_support import JobTest,h
from par_keeper.contract import authority_body
from par_upload_window import contract as w
from par_wire.codec import encode
class JobFaults(JobTest):
    def setup_action(self,action):
        if action=='close':args=self.close_args()
        elif action=='retire':args=dict(action='retire',command=self.retired_command())
        elif action=='compact':
            self.terminal();a,q=self.proposed();self.window.close_window(q,a);args=dict(action='compact')
        elif action=='open':
            r=self.finish();args=dict(action='open',command=self.grant_for(2,w.digest(r)))
        self.jobs.submit(self.jid(),**args);self.prepare(self.jid())
    def crash(self,action,event,mode='step'):
        self.setup_action(action)
        j={'keeper_root':str(self.path),'root':str(self.wroot),'store_id':self.store_id.hex(),
           'seed':self.ks.hex(),'authority':encode(authority_body(self.keeper.authority)).hex(),
           'quota':self.total*3,'jobs':str(self.jroot),'jid':self.jid().hex(),'event':event,'mode':mode}
        f=Path(self.tmp.name)/'job-worker.json';f.write_text(json.dumps(j));f.chmod(0o600)
        self.jobs.close();self.jobs=None;self.window.close();self.window=None;self.keeper.close();self.keeper=None
        cp=subprocess.run([sys.executable,'-I','-S',str(Path(__file__).with_name('jobs_crash_worker.py')),str(f)],capture_output=True,timeout=15,env={'PATH':os.environ.get('PATH','')})
        self.assertEqual(cp.returncode,-signal.SIGKILL,cp.stderr.decode());event_read=json.loads(cp.stdout);self.assertEqual(event_read,{'hit':event,'pgid':os.getpgid(0)})
        self.open_keeper();self.window=self.w.ReplaySpool(self.keeper,self.wroot,self.store_id);self.reopen_jobs_new()
        status=self.jobs.poll(self.jid())
        if mode=='cancel':
            self.assertEqual(self.window.phase,'OPEN');self.assertEqual(self.jobs.cancel(self.jid())['state'],'CANCELLED');return
        if status['state']=='PREPARED':status=self.jobs.step(self.jid())
        elif status['state']=='OUTCOME_UNKNOWN':
            self.err('CANCEL_TOO_LATE',lambda:self.jobs.cancel(self.jid()));status=self.jobs.reconcile(self.jid())
            if status['state']=='RETRY_READY':status=self.jobs.retry(self.jid())
        self.assertEqual(status['state'],'SUCCEEDED');result=self.jobs.result(self.jid());self.assertEqual(result,self.jobs.result(self.jid()))
    def test_sync_failure_before_execution_does_not_mutate_target(self):
        self.setup_action('close')
        with patch('par_management_jobs.journal.os.fsync',side_effect=OSError(errno.ENOSPC,'synthetic full')):self.err(None,lambda:self.jobs.step(self.jid()))
        self.assertEqual(self.window.phase,'OPEN');self.reopen_jobs();self.assertEqual(self.jobs.poll(self.jid())['state'],'PREPARED')
    def test_cancel_ack_loss_reopens_cancelled(self):
        self.setup_action('close')
        def lose(e):
            if e=='job.cancelled.after_sync':raise OSError('ack lost')
        self.jobs.journal.observer=lose;self.err(None,lambda:self.jobs.cancel(self.jid()));self.reopen_jobs();self.assertEqual(self.jobs.poll(self.jid())['state'],'CANCELLED');self.assertEqual(self.window.phase,'OPEN')
    def test_success_journal_failure_is_unknown_until_reconcile(self):
        self.setup_action('close')
        def lose(e):
            if e=='job.succeeded.before_replace':raise OSError('result write failed')
        self.jobs.journal.observer=lose;self.err('JOB_JOURNAL_UNCERTAIN',lambda:self.jobs.step(self.jid()));self.reopen_jobs();self.assertEqual(self.jobs.poll(self.jid())['state'],'OUTCOME_UNKNOWN');self.assertEqual(self.jobs.reconcile(self.jid())['state'],'SUCCEEDED')
    def test_authority_changes_after_dispatch_does_not_erase_result(self):
        self.setup_action('close')
        def change(e):
            if e=='job.effect.after_dispatch':self.change_authority();raise OSError('lost')
        self.jobs.journal.observer=change;self.assertEqual(self.jobs.step(self.jid())['state'],'OUTCOME_UNKNOWN');self.jobs.journal.observer=None;self.assertTrue(self.jobs.reconcile(self.jid())['result_verified'])
    def test_dispatch_marked_before_side_effect(self):
        self.setup_action('close');seen=[]
        def observe(e):
            if e=='job.effect.before_dispatch':
                from par_management_jobs import contract as c
                b,_,_=self.jobs.journal.read(self.jid());seen.append((b[13][-1][1],self.window.phase))
        self.jobs.journal.observer=observe;self.jobs.step(self.jid());self.assertEqual(seen,[('EXECUTING','OPEN')])
    def test_activity_changes_after_marker_stops_dispatch(self):
        self.setup_action('close');self.jobs.journal.observer=lambda e:setattr(self,'activity_count',1) if e=='job.effect.before_dispatch' else None
        self.assertEqual(self.jobs.step(self.jid())['state'],'OUTCOME_UNKNOWN');self.assertEqual(self.window.phase,'OPEN')
    def test_fork_rejects_inherited_manager(self):
        self.setup_action('close');r,wfd=os.pipe();pid=os.fork()
        if pid==0:
            os.close(r)
            try:self.jobs.step(self.jid());v=b'BAD'
            except Exception as e:v=getattr(e,'code','ERROR').encode()
            os.write(wfd,v);os._exit(0)
        os.close(wfd);v=os.read(r,100);os.close(r);_,status=os.waitpid(pid,0);self.assertEqual(status,0);self.assertEqual(v,b'OWNER_REQUIRED');self.assertEqual(self.window.phase,'OPEN')
BOUNDARIES={
 'close':['job.executing.before_replace','job.executing.after_replace','job.executing.after_sync','job.effect.before_dispatch','window.archive.after_sync','window.close.after_replace','window.close.after_sync','job.effect.after_dispatch','job.succeeded.before_replace','job.succeeded.after_replace','job.succeeded.after_sync'],
 'retire':['retirement.intent.after_meta','retirement.after_unlink','retirement.after_sync','retirement.tombstone.after_meta'],
 'compact':['window.compact.after_unlink','window.compact.after_unlink_sync','window.compact.before_credit','window.compact.after_sync'],
 'open':['window.open.before_replace','window.open.after_replace','window.open.after_sync']}
for action,events in BOUNDARIES.items():
    for event in events:
        def test(self,a=action,e=event):self.crash(a,e)
        name='test_sigkill_'+action+'_'+event.replace('.','_')
        if hasattr(JobFaults,name):raise RuntimeError('duplicate test name')
        setattr(JobFaults,name,test)
for event in ('job.cancelled.before_replace','job.cancelled.after_replace','job.cancelled.after_sync'):
    def test(self,e=event):self.crash('close',e,'cancel')
    setattr(JobFaults,'test_sigkill_cancel_'+event.replace('.','_'),test)
