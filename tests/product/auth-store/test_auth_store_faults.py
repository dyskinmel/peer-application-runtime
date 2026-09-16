from auth_store_support import *
import os,signal,subprocess,sys
from par_store.store import Store
AUTH_STAGES=['auth.before_begin','auth.after_begin','auth.after_row','auth.after_material','auth.after_outbox','auth.before_commit','auth.after_commit']
WRITE_STAGES=['commit.before_begin','commit.after_begin','commit.after_envelope','commit.after_ledger','commit.after_actor','commit.after_catalog','commit.after_dependencies','commit.after_blocks','commit.after_outbox','commit.after_meta','commit.after_nonce','commit.after_authority_proof','commit.before_commit','commit.after_commit']
CRYPTO_STAGES=['crypto.after_content_reservation','crypto.after_content_seal','crypto.before_store_commit']
MIGRATION_STAGES=['migration.after_begin','migration.after_schema','migration.before_commit','migration.after_commit']

class CrashTests(AuthStoreTest):
    def run_crash(self,action,stage):
        if action=='migration':Store.create(self.root,allow_unpatched_sqlite=True).close()
        else:
            self.start('control' if action=='membership' else 'membership' if action=='activate' else 'active');self.close()
        result=subprocess.run([sys.executable,'-I','-S',str(ROOT/'tests/product/auth-store/crash_worker.py'),str(self.root),action,stage],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,-signal.SIGKILL,result.stdout+result.stderr);self.assertIn('REACHED:'+stage,result.stdout)
        committed=stage.endswith('after_commit')
        if action=='migration':
            cls=self.m.AuthorityStore if committed else Store
            kw={'provider':self.p} if committed else {}
            with cls.open(self.root,allow_unpatched_sqlite=True,**kw) as db:
                c=db._storage.connection if committed else db.connection;self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],2 if committed else 1)
            return
        self.reopen();state=self.db.status(self.s.space)
        if action in ('write','crypto'):
            n=1 if committed else 0
            self.assertEqual(self.count('commit_ledger'),n);self.assertEqual(self.count('auth_commits'),n)
            issued=3 if action=='write' or stage=='crypto.before_store_commit' else 1
            self.assertEqual(self.count('issued_nonces'),issued)
            self.activate();r=self.writer().write(*self.request());self.assertIsNotNone(r)
            self.assertEqual(self.count('issued_nonces'),issued if committed else issued+3)
        elif action=='control':
            self.assertEqual(state['known_epoch'],2 if committed else 1)
            self.assertEqual(state['state'],'MEMBERSHIP_PENDING' if committed else 'EPOCH_PENDING')
            if committed:self.reject('MEMBERSHIP_REQUIRED',lambda:self.writer().prepare(*self.request()))
        elif action=='membership':self.assertEqual(state['state'],'EPOCH_PENDING' if committed else 'MEMBERSHIP_PENDING')
        elif action=='activate':
            self.assertEqual(self.count('auth_epoch_keys'),1 if committed else 0);self.assertEqual(self.count('auth_materials'),1 if committed else 0);self.assertEqual(state['state'],'EPOCH_PENDING')
        elif action=='fork':self.assertEqual(state['state'],'CONTROL_FORK' if committed else 'EPOCH_PENDING')
        self.assertTrue(self.db.audit()['valid'],self.db.audit())

for action,stages in [('control',AUTH_STAGES),('membership',AUTH_STAGES),('activate',AUTH_STAGES),('fork',AUTH_STAGES),('write',WRITE_STAGES),('crypto',CRYPTO_STAGES),('migration',MIGRATION_STAGES)]:
    for stage in stages:
        def case(self,a=action,s=stage):self.run_crash(a,s)
        setattr(CrashTests,'test_sigkill_'+action+'_'+stage.replace('.','_'),case)

class TransactionFaultTests(AuthStoreTest):
    def test_second_connection_cannot_write_inside_payload_transaction(self):
        self.start();c2=sqlite3.connect(self.root/'store.sqlite',isolation_level=None,timeout=.01);self.addCleanup(c2.close);seen=[]
        def probe(stage):
            if stage=='commit.after_begin':
                try:c2.execute('BEGIN IMMEDIATE')
                except sqlite3.OperationalError as e:seen.append(e.sqlite_errorcode)
        self.db.observer=probe;self.writer().write(*self.request());self.assertEqual(seen,[sqlite3.SQLITE_BUSY]);c2.execute('BEGIN IMMEDIATE');c2.execute('ROLLBACK')
    def test_sqlite_full_rolls_back_authority_and_payload(self):
        self.start();candidate=self.writer().prepare(*self.request());c=self.db._storage.connection
        limit=c.execute('PRAGMA page_count').fetchone()[0];c.execute('PRAGMA max_page_count='+str(limit))
        def full(stage):
            if stage=='commit.after_ledger':c.execute('INSERT INTO quarantined_inputs VALUES(?,?,?,?,?)',(h('input'),self.s.space,'test',b'x'*1048576,1048576))
        self.db.observer=full;self.reject('SQLITE_FULL',lambda:self.db.commit(candidate));self.assertEqual(self.count('commit_ledger'),0);self.assertEqual(self.count('auth_commits'),0);self.assertEqual(self.count('issued_nonces'),3);self.assertFalse(c.in_transaction)
    def test_sqlite_full_authority_update_is_not_acknowledged(self):
        self.start();c=self.db._storage.connection;limit=c.execute('PRAGMA page_count').fetchone()[0];c.execute('PRAGMA max_page_count='+str(limit))
        def full(stage):
            if stage=='auth.after_row':c.execute('INSERT INTO quarantined_inputs VALUES(?,?,?,?,?)',(h('input'),self.s.space,'test',b'x'*1048576,1048576))
        self.db.observer=full;self.reject('SQLITE_FULL',lambda:self.db.observe(self.s.space,self.s.raw(self.s.next(self.b['raw']))));self.db.observer=None;self.assertEqual(self.db.status(self.s.space)['state'],'AUTH_PERSISTENCE_UNCERTAIN');self.assertEqual(self.db.pin(self.s.space)['sequence'],1)
    def test_second_guard_rejects_change_after_first_guard(self):
        from par_auth_store.model import row_hash,ROW_FIELDS
        self.start();candidate=self.writer().prepare(*self.request());c=self.db._storage.connection
        def flip(stage):
            if stage=='commit.after_authority_proof':
                row=dict(c.execute('SELECT * FROM auth_spaces').fetchone());row['revision']=(100).to_bytes(8,'big');row['row_digest']=row_hash(row);c.execute('UPDATE auth_spaces SET revision=?,row_digest=?',(row['revision'],row['row_digest']))
        self.db.observer=flip;self.reject('STALE_DECISION',lambda:self.db.commit(candidate));self.assertEqual(self.count('commit_ledger'),0);self.assertEqual(self.count('auth_commits'),0)
    def test_process_writer_lock_is_still_exclusive(self):
        self.start();self.reject('WRITER_BUSY',lambda:self.m.AuthorityStore.open(self.root,provider=self.p,allow_unpatched_sqlite=True))
