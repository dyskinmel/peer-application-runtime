import os,signal,subprocess,sys
from pathlib import Path
from test_events import EventTest
R=Path(__file__).resolve().parents[3]
STAGES=('nonce.after_begin','nonce.before_commit','nonce.after_commit','event.after_encrypt','event.after_begin','event.after_insert','event.after_frontier','event.before_commit','event.after_commit')
ACK_STAGES=('ack.after_begin','ack.after_update','ack.before_commit','ack.after_commit')
class CrashTests(EventTest):
 def _kill(self,action,stage):
  self.create();self.emit()
  if action=='ack':self.journal.subscribe(b'c'*16).cancel()
  self.close_journal();self.close()
  p=subprocess.run([sys.executable,'-I','-S','-B',str(R/'tests/product/wp10/crash_worker.py'),self.tmp.name,action,stage],capture_output=True,text=True,timeout=20)
  self.assertEqual(p.returncode,-signal.SIGKILL,p.stdout+p.stderr)
  self.reopen_owner();self.kw['owner']=self.db;self.reopen()
  if action=='publish':
   found=self.journal.inspect_operation((2).to_bytes(16,'big'))
   self.assertEqual(found is not None,stage=='event.after_commit')
   self.emit(2);self.assertEqual(self.journal.inspect()['events'],2)
  else:
   s=self.journal.subscribe(b'c'*16);b=s.poll()
   self.assertEqual(len(b.events),0 if stage=='ack.after_commit' else 1)
 def reopen_owner(self):
  self.db=self.m.AuthorityStore.open(self.root,provider=self.p,allow_unpatched_sqlite=True);self.activate()
 def test_fork_handle_refused(self):
  self.create();pid=os.fork()
  if pid==0:
   try:self.journal.inspect()
   except self.events.EventError as e:os._exit(0 if e.code=='WRONG_OWNER' else 2)
   os._exit(3)
  _,status=os.waitpid(pid,0);self.assertEqual(os.waitstatus_to_exitcode(status),0)
for phase in STAGES:
 def test(self,stage=phase):self._kill('publish',stage)
 setattr(CrashTests,'test_kill_publish_'+phase.replace('.','_'),test)
for phase in ACK_STAGES:
 def test(self,stage=phase):self._kill('ack',stage)
 setattr(CrashTests,'test_kill_ack_'+phase.replace('.','_'),test)
