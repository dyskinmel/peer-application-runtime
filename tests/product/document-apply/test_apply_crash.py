import json,subprocess,sys,signal,sqlite3
from pathlib import Path
from apply_support import ApplyTest,h
from harness.common import clean_env

STAGES=['apply.nonce_before_commit','apply.nonce_after_commit','apply.after_encrypt','apply.before_begin','apply.after_begin','apply.after_inputs','apply.after_event','apply.after_frontier','apply.after_nonce_link','apply.before_commit','apply.after_commit']
class CrashTests(ApplyTest):
 def crash(self,stage):
  e,_=self.saved();self.close()
  cp=subprocess.run([sys.executable,'-I','-S','-B',str(Path(__file__).with_name('apply_crash_worker.py')),str(self.root),stage,e.hex()],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15,env=clean_env())
  self.assertEqual(cp.returncode,-signal.SIGKILL,cp.stderr.decode());self.assertIn(('KILL_BOUNDARY:'+stage).encode(),cp.stdout)
  self.reopen();self.db.reactivate(self.s.space,self.s.devices[0]['secret']);self.a=self.make();n=self.nums()
  finished=stage=='apply.after_commit';self.assertEqual(n['document_frontiers'],int(finished));self.assertEqual(n['document_inputs'],int(finished));self.assertTrue(self.db.audit()['valid'])
  before=n['document_apply_nonces'];self.assertEqual(self.call([e])['revision'],1);self.assertEqual(self.nums()['document_apply_nonces'],before+(0 if finished else 1))
 def test_actual_sqlite_writer_contention(self):
  e,_=self.saved();p=self.a.prepare(b'c'*16,(e,),expected_revision=0)
  other=sqlite3.connect(self.root/'store.sqlite',isolation_level=None)
  try:
   other.execute('BEGIN IMMEDIATE');self.deny('SQLITE_BUSY',lambda:self.a.commit(p))
  finally:other.execute('ROLLBACK');other.close()
  self.assertEqual(self.nums()['document_apply_events'],0);self.assertEqual(self.a.commit(p)['revision'],1)
 def test_actual_sqlite_full(self):
  e,_=self.saved();p=self.a.prepare(b'f'*16,(e,),expected_revision=0);c=self.db._storage.connection
  # Force growth under SQLite's real page limit, not a mocked return code.
  n=c.execute('PRAGMA page_count').fetchone()[0];c.execute('PRAGMA max_page_count='+str(n))
  from unittest.mock import patch
  # Need a sufficiently large legitimate synthetic note to force new pages.
  self.port.mutate=lambda r:r['note'].update(body='z'*100000)
  c.execute('PRAGMA max_page_count=1073741823');p=self.a.prepare(b'g'*16,(e,),expected_revision=0)
  n=c.execute('PRAGMA page_count').fetchone()[0];c.execute('PRAGMA max_page_count='+str(n))
  self.deny('SQLITE_FULL',lambda:self.a.commit(p));self.assertEqual(self.nums()['document_apply_events'],0)
for stage in STAGES:
 def test(self,stage=stage):self.crash(stage)
 setattr(CrashTests,'test_sigkill_'+stage.replace('.','_'),test)
