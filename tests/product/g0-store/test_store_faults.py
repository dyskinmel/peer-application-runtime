from store_helpers import *
import errno, os, subprocess, selectors, time

STAGES=('commit.before_begin','commit.after_begin','commit.after_envelope','commit.after_ledger',
        'commit.after_actor','commit.after_catalog','commit.after_dependencies','commit.after_blocks',
        'commit.after_outbox','commit.after_meta','commit.after_nonce','commit.before_commit','commit.after_commit')
BLOCK_STAGES=('block.after_write','block.after_fsync','block.after_rename','block.after_dirsync')

class FaultTests(StoreCase):
    def test_sqlite_full_is_real_error_with_no_partial_commit(self):
        p=self.prepare(envelope=b'x'*700000)
        pages=self.scalar('PRAGMA page_count');self.s.connection.execute(f'PRAGMA max_page_count={pages}')
        e=self.err('SQLITE_FULL',self.commit,p)
        self.assertEqual(e.sqlite_code,sqlite3.SQLITE_FULL)
        self.assertEqual(self.scalar('SELECT count(*) FROM commit_ledger'),0)
        self.assertEqual(self.scalar('SELECT count(*) FROM issued_nonces'),1)
        self.assertTrue(self.s.audit()['valid'])
    def test_real_sqlite_write_lock_busy(self):
        p=self.prepare();other=sqlite3.connect(self.root/'store.sqlite',isolation_level=None)
        try:
            other.execute('BEGIN IMMEDIATE')
            e=self.err('SQLITE_BUSY',self.commit,p);self.assertEqual(e.sqlite_code,sqlite3.SQLITE_BUSY)
            self.assertFalse(self.s.connection.in_transaction)
        finally:other.execute('ROLLBACK');other.close()
        self.commit(p);self.assertTrue(self.s.audit()['valid'])
    def test_constraint_failure_rolls_back_prior_inserts(self):
        p=self.prepare()
        self.s.connection.execute("CREATE TRIGGER force_abort BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT,'reject'); END")
        self.err('SQLITE_CONSTRAINT',self.commit,p)
        self.assertEqual(self.scalar('SELECT count(*) FROM envelopes'),0)
        self.s.connection.execute('DROP TRIGGER force_abort');self.commit(p)
    def test_interrupt_rolls_back(self):
        p=self.prepare()
        self.s.connection.set_progress_handler(lambda:1,1)
        self.err('SQLITE_INTERRUPT',self.commit,p)
        self.s.connection.set_progress_handler(None,0)
        self.assertIsNone(self.s.lookup_operation(p.operation_id,p.input_digest))
    def test_fsync_enospc_is_not_success(self):
        p=self.prepare(blocks=(b'sealed',))
        original=self.s.block_port.sync_file
        def fail(fd):raise OSError(errno.ENOSPC,'full')
        self.s.block_port.sync_file=fail
        self.err('STORAGE_FULL',self.commit,p)
        self.s.block_port.sync_file=original
        self.assertIsNone(self.s.lookup_operation(p.operation_id,p.input_digest));self.assertTrue(self.s.audit()['valid'])
    def test_commit_response_exception_is_outcome_unknown(self):
        p=self.prepare()
        self.s.observer=lambda stage: (_ for _ in ()).throw(RuntimeError('response gone')) if stage=='commit.after_commit' else None
        e=self.err('LOCAL_OUTCOME_UNKNOWN',self.commit,p)
        self.assertEqual(e.operation_id,p.operation_id)
        self.s.observer=None;self.assertIsNotNone(self.s.lookup_operation(p.operation_id,p.input_digest))
        self.assertEqual(self.commit(p),self.s.lookup_operation(p.operation_id,p.input_digest))
    def test_db_read_corruption_does_not_trigger_destructive_repair(self):
        self.s.close();p=self.root/'store.sqlite';p.write_bytes(b'bad header'+p.read_bytes()[10:]);before=p.read_bytes()
        self.err('CORRUPT_STORE',self.api.Store.open,self.root,allow_unpatched_sqlite=True)
        self.assertEqual(p.read_bytes(),before)

def exception_case(stage):
    def test(self):
        p=self.prepare(blocks=(b'cutpoint-block',),dependencies=(h('dep'),))
        self.s.observer=lambda s: (_ for _ in ()).throw(RuntimeError('injected cut')) if s==stage else None
        code='LOCAL_OUTCOME_UNKNOWN' if stage=='commit.after_commit' else 'LOCAL_ABORTED'
        self.err(code,self.commit,p);self.s.observer=None
        expected=1 if stage=='commit.after_commit' else 0
        for table in ('commit_ledger','envelopes','actor_states','outbox','catalog','local_commit_meta'):
            self.assertEqual(self.scalar('SELECT count(*) FROM '+table),expected,(stage,table))
        self.assertEqual(self.scalar('SELECT count(*) FROM issued_nonces'),1)
        self.assertTrue(self.s.audit()['valid'])
    return test
for stage in STAGES:setattr(FaultTests,'test_rollback_'+stage.replace('.','_'),exception_case(stage))

# Parent kills the child only after receiving the exact boundary label. stdout is not a PASS oracle.
def killed_case(stage):
    def test(self):
        self.s.close()
        worker=ROOT/'tests/product/g0-store/store_worker.py'
        proc=subprocess.Popen([sys.executable,'-I','-S','-B',str(worker),'--root',str(self.root),'--cut',stage],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.addCleanup(lambda:proc.kill() if proc.poll() is None else None)
        sel=selectors.DefaultSelector();sel.register(proc.stdout,selectors.EVENT_READ)
        try:
            self.assertTrue(sel.select(10), 'child never reached requested barrier')
            line=proc.stdout.readline().decode().strip();self.assertEqual(line,'BARRIER '+stage)
            proc.kill();out,err=proc.communicate(timeout=10)
            self.assertNotEqual(proc.returncode,0);self.assertNotIn(b'COMMIT_RETURNED',out)
        finally:
            sel.close()
            if proc.poll() is None:proc.kill();proc.communicate(timeout=5)
        self.s=self.api.Store.open(self.root,allow_unpatched_sqlite=True)
        expected=1 if stage=='commit.after_commit' else 0
        for table in ('commit_ledger','envelopes','actor_states','outbox','catalog','local_commit_meta'):
            self.assertEqual(self.scalar('SELECT count(*) FROM '+table),expected,(stage,table))
        self.assertEqual(self.scalar('SELECT count(*) FROM issued_nonces'),1)
        self.assertTrue(self.s.audit()['valid'])
        if expected:
            r=self.s.lookup_operation((100).to_bytes(16,'big'),h('input-100'))
            self.assertIsNotNone(r)
        self.s.collect_orphans();self.assertTrue(self.s.audit()['valid'])
    return test
for stage in STAGES+BLOCK_STAGES:setattr(FaultTests,'test_sigkill_'+stage.replace('.','_'),killed_case(stage))
