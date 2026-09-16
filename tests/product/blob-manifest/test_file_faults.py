from file_support import *
import errno,signal,subprocess,sys,sqlite3
from unittest import mock
ROOT=Path(__file__).resolve().parents[3]
GEN_STAGES=['file.intent.sealed','file.intent.written','file.intent.synced','file.intent.published','file.intent.durable','file.source.scanned']+[f'file.chunk.{i}.{point}' for i in (0,1) for point in ('reserved','sealed','written','synced','published','durable')]+[f'file.manifest.{point}' for point in ('reserved','sealed','written','synced','published','durable')]+['file.stage.ack']
COMMIT_STAGES=['file.commit.before_prepare','file.commit.prepared','block.after_write','block.after_rename','commit.after_begin','blob.after_manifest','blob.after_reference','commit.before_commit','commit.after_commit','file.commit.ack']
EXPORT_STAGES=['file.export.chunk.0','file.export.chunk.1','file.export.verified','file.export.published','file.export.ack']
class FileFaultTests(FileTest):
    def child(self,action,stage):
        r=subprocess.run([sys.executable,'-I','-S',str(ROOT/'tests/product/blob-manifest/file_crash_worker.py'),str(self.root),action,stage,str(self.source),str(self.output)],capture_output=True,text=True,timeout=15)
        self.assertEqual(r.returncode,-signal.SIGKILL,r.stdout+r.stderr);self.assertIn('REACHED:'+stage,r.stdout)
    def check_stage(self,stage):
        self.start();self.close();self.child('stage',stage);self.reopen();self.assertEqual(self.count('commit_ledger'),0);self.assertTrue(self.db.audit()['valid']);self.activate()
        files={p.name:p.read_bytes() for p in (self.root/'staging').rglob('chunk-*.cbor')}
        w=self.fw();s=self.stage(w);r=w.commit(s,*self.request()[1:]);self.export(r.envelope_id);self.assertEqual(self.output.read_bytes(),self.data)
        for p in (self.root/'staging').rglob('chunk-*.cbor'):
            if p.name in files:self.assertEqual(p.read_bytes(),files[p.name])
        c=self.db._storage.connection;self.assertEqual(c.execute('SELECT count(*) FROM issued_nonces').fetchone()[0],len(set(tuple(x) for x in c.execute('SELECT key_context,nonce FROM issued_nonces'))))
    def check_commit(self,stage):
        self.start();self.stage();self.close();self.child('commit',stage);self.reopen();self.assertTrue(self.db.audit()['valid'])
        expected=1 if stage in ('commit.after_commit','file.commit.ack') else 0;self.assertEqual(self.count('commit_ledger'),expected);self.activate()
        w=self.fw();s=w.load_staged(self.request()[0]);n=self.count('issued_nonces');r=w.commit(s,*self.request()[1:])
        if expected:self.assertEqual(self.count('issued_nonces'),n)
        self.export(r.envelope_id);self.assertEqual(self.output.read_bytes(),self.data)
    def check_export(self,stage):
        self.start();r=self.write();self.close();self.child('export',stage);self.reopen();self.assertTrue(self.db.audit()['valid'])
        expected=stage in ('file.export.published','file.export.ack');self.assertEqual(self.output.exists(),expected)
        if not expected:self.export(r.envelope_id)
        self.assertEqual(self.output.read_bytes(),self.data)
    def test_no_reference_after_stage_fsync_failure(self):
        self.start()
        with mock.patch('par_file.journal.os.fsync',side_effect=OSError(errno.ENOSPC,'injected')):
            self.reject_file('FILE_IO_FAILED',lambda:self.stage())
        self.assertEqual(self.count('commit_ledger'),0)
    def test_export_fsync_failure_does_not_publish(self):
        self.start();r=self.write()
        with mock.patch('par_file.reader.os.fsync',side_effect=OSError(errno.EIO,'injected')):
            self.reject_file('FILE_EXPORT_IO_FAILED',lambda:self.export(r.envelope_id))
        self.assertFalse(self.output.exists())
    def test_export_response_loss_is_unknown_not_rollback(self):
        self.start();r=self.write()
        def hook(s):
            if s=='file.export.published':raise RuntimeError()
        self.reject_file('FILE_EXPORT_OUTCOME_UNKNOWN',lambda:self.export(r.envelope_id,observer=hook));self.assertEqual(self.output.read_bytes(),self.data)
    def test_commit_response_loss_reuses_exact_ciphertext(self):
        self.start();w=self.fw();s=self.stage(w)
        def hook(p):
            if p=='file.commit.ack':raise RuntimeError()
        w.observer=hook;self.reject_file('FILE_COMMIT_OUTCOME_UNKNOWN',lambda:w.commit(s,*self.request()[1:]));n=self.count('issued_nonces');w.observer=None;self.assertIsNotNone(w.commit(s,*self.request()[1:]));self.assertEqual(self.count('issued_nonces'),n)
    def test_stage_ack_loss_keeps_exact_artifacts(self):
        self.start()
        def hook(p):
            if p=='file.stage.ack':raise RuntimeError()
        self.reject_file('FILE_INTERRUPTED',lambda:self.stage(self.fw(observer=hook)));n=self.count('issued_nonces');self.stage();self.assertEqual(self.count('issued_nonces'),n)
    def test_auth_change_after_preparation_is_rejected(self):
        self.start();w=self.fw();s=self.stage(w)
        def hook(p):
            if p=='file.commit.prepared':self.same_epoch()
        w.observer=hook;self.reject_file('STALE_DECISION',lambda:w.commit(s,*self.request()[1:]));self.assertEqual(self.count('blob_references'),0)
    def test_sqlite_write_lock_blocks_nonce(self):
        self.start();c=sqlite3.connect(self.root/'store.sqlite',isolation_level=None);self.addCleanup(c.close);c.execute('BEGIN IMMEDIATE');self.reject_file('SQLITE_BUSY',lambda:self.stage());c.execute('ROLLBACK');self.assertEqual(self.count('issued_nonces'),0);self.assertIsNotNone(self.stage())
    def test_complete_missing_chunk_not_regenerated(self):
        self.start();w=self.fw();s=self.stage(w);paths=list((self.root/'staging').rglob('chunk-0000.cbor'));paths[0].unlink();n=self.count('issued_nonces');self.reject_file('FILE_ARTIFACT_MISSING',lambda:self.stage(w));self.assertEqual(self.count('issued_nonces'),n)
    def test_complete_corrupt_manifest_not_regenerated(self):
        self.start();w=self.fw();self.stage(w);list((self.root/'staging').rglob('manifest.cbor'))[0].write_bytes(b'bad');n=self.count('issued_nonces');self.reject_file(None,lambda:self.stage(w));self.assertEqual(self.count('issued_nonces'),n)
    def test_nonce_collision_is_rejected(self):
        self.start();self.reject_file('NONCE_REUSED',lambda:self.stage(self.fw(random_source=lambda n:b'Z'*n)));self.assertEqual(self.count('commit_ledger'),0)
    def test_nonce_record_mismatch_is_rejected(self):
        self.start();w=self.fw();s=self.stage(w);self.db._storage.connection.execute('UPDATE issued_nonces SET payload_digest=?',(h("corrupt-reservation"),));self.reject_file('FILE_NONCE_RECORD_MISSING',lambda:w.load_staged(s.operation_id))
    def test_reentrant_other_file_writer_is_rejected(self):
        self.start();errors=[]
        def hook(s):
            if s=='file.source.scanned':
                try:self.stage(self.fw(),self.request(op=2))
                except StoreError as e:errors.append(e.code)
        self.stage(self.fw(observer=hook));self.assertEqual(errors,['REENTRANT_OPERATION'])
    def test_validly_encrypted_wrong_whole_hash_rejected(self):
        self.start();w=self.fw();s=self.stage(w);parts=list(w.artifacts(s));raw=objects.open_block(self.p,self.s.secret,decode(parts[0].header_bytes),parts[0].sealed_bytes);v=self.file.manifest.loads(raw);v[9]=h('wrong-whole-hash');plain=self.file.manifest.dumps(v);head=self.file.manifest.root_header(v,len(plain));sealed=objects.seal_block(self.p,self.s.secret,head,plain,b'Y'*24);parts[0]=self.blob.Attachment(objects.block_id(sealed),encode(head),sealed);r=self.writer().write(*self.request(),attachments=tuple(parts));self.assertTrue(self.db.audit()['valid']);self.reject_file('FILE_HASH_MISMATCH',lambda:self.export(r.envelope_id));self.assertFalse(self.output.exists())
    def test_signed_attachment_subset_is_not_complete_file(self):
        self.start();w=self.fw();s=self.stage(w);parts=w.artifacts(s);r=self.writer().write(*self.request(),attachments=parts[:-1]);self.assertTrue(self.db.audit()['valid']);self.reject_file('FILE_CHUNK_SET',lambda:self.export(r.envelope_id));self.assertFalse(self.output.exists())
    def test_signed_reordered_chunk_set_is_not_complete_file(self):
        self.start();w=self.fw();s=self.stage(w);parts=w.artifacts(s);r=self.writer().write(*self.request(),attachments=parts[:1]+parts[:0:-1]);self.reject_file('FILE_CHUNK_SET',lambda:self.export(r.envelope_id))
    def test_duplicate_intent_or_unknown_file_is_rejected(self):
        self.start();w=self.fw();s=self.stage(w);list((self.root/'staging').rglob('intent.cbor'))[0].with_name('unknown.cbor').write_bytes(b'bad');self.reject_file('FILE_ARTIFACT_INVALID',lambda:w.load_staged(s.operation_id))
    def test_source_unlinked_after_stage_can_commit(self):
        self.start();w=self.fw();s=self.stage(w);self.source.unlink();r=w.commit(s,*self.request()[1:]);self.export(r.envelope_id);self.assertEqual(self.output.read_bytes(),self.data)
    def test_mutating_header_in_observer_does_not_change_write_intent(self):
        self.start();req=self.request();head=req[1]
        def hook(s):
            if s=='file.source.scanned':head[13]=h('changed-head')
        r=self.fw(observer=hook).write(*req,self.source,name='資料.txt',media_type='text/plain');self.export(r.envelope_id);self.assertEqual(self.output.read_bytes(),self.data)

for prefix,stages,method in [('stage',GEN_STAGES,'check_stage'),('commit',COMMIT_STAGES,'check_commit'),('export',EXPORT_STAGES,'check_export')]:
    for stage in stages:
        def test(self,stage=stage,method=method):getattr(self,method)(stage)
        setattr(FileFaultTests,'test_sigkill_'+prefix+'_'+stage.replace('.','_'),test)
