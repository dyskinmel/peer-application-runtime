from file_support import *
from par_blob_store import Attachment

class FilePipelineTests(FileTest):
    def test_stage_does_not_publish_reference(self):
        self.start();s=self.stage();self.assertEqual(s.state,'STAGED');self.assertEqual(self.count('blob_objects'),0);self.assertEqual(list((self.root/'blocks').iterdir()),[])
    def test_whole_file_write_and_export(self):
        self.start();r=self.write();info=self.export(r.envelope_id);self.assertEqual(self.output.read_bytes(),self.data);self.assertEqual(info.size,len(self.data));self.assertEqual(info.name,'資料.txt');self.assertTrue(info.complete);self.assertTrue(self.db.audit()['valid'])
    def test_empty_file(self):
        self.source.write_bytes(b'');self.start();r=self.write();i=self.export(r.envelope_id);self.assertEqual(self.output.read_bytes(),b'');self.assertEqual(i.chunks,0)
    def test_one_byte(self):
        self.source.write_bytes(b'a');self.start();r=self.write();self.export(r.envelope_id);self.assertEqual(self.output.read_bytes(),b'a')
    def test_exact_chunk(self):
        self.source.write_bytes(b'b'*262144);self.start();r=self.write();i=self.export(r.envelope_id);self.assertEqual(i.chunks,1)
    def test_maximum_profile_size(self):
        self.source.write_bytes(b'm'*(7*1024*1024));self.start();r=self.write();i=self.export(r.envelope_id);self.assertEqual(i.chunks,28);self.assertEqual(i.size,7*1024*1024)
    def test_too_large_before_nonce(self):
        self.source.write_bytes(b'');self.source.open('r+b').truncate(7*1024*1024+1);self.start();self.reject_file('FILE_LIMIT',lambda:self.stage());self.assertEqual(self.count('issued_nonces'),0)
    def test_manifest_and_chunks_have_distinct_domains(self):
        self.start();w=self.fw();s=self.stage(w);parts=w.artifacts(s);self.assertNotEqual(decode(parts[0].header_bytes)[3],decode(parts[1].header_bytes)[3])
    def test_acknowledged_stage_retry_no_new_nonce(self):
        self.start();w=self.fw();s=self.stage(w);n=self.count('issued_nonces');self.assertEqual(self.stage(w),s);self.assertEqual(self.count('issued_nonces'),n)
    def test_acknowledged_write_retry_no_new_nonce(self):
        self.start();w=self.fw();s=self.stage(w);r=w.commit(s,*self.request()[1:]);n=self.count('issued_nonces');self.assertEqual(w.commit(s,*self.request()[1:]),r);self.assertEqual(self.count('issued_nonces'),n)
    def test_whole_write_convenience(self):
        self.start();r=self.fw().write(*self.request(),self.source,name='a.bin',media_type='application/octet-stream');self.assertEqual(self.file.inspect_file(self.db,r.envelope_id,self.s.secret).name,'a.bin')
    def test_query_stage_after_restart(self):
        self.start();w=self.fw();s=self.stage(w);self.reopen();w=self.fw();self.assertEqual(w.load_staged(self.request()[0]),s)
    def test_resume_stage_and_commit_after_reactivation(self):
        self.start();s=self.stage();self.reopen();self.activate();w=self.fw();r=w.commit(w.load_staged(s.operation_id),*self.request()[1:]);self.export(r.envelope_id);self.assertEqual(self.output.read_bytes(),self.data)
    def test_wrong_local_key_cannot_open_stage(self):
        self.start();s=self.stage();d=self.s.devices[0];w=self.file.FileWriter(self.db,d['cert'],self.s.secret,d['seed'],h('wrong-local'));self.reject_file(None,lambda:w.load_staged(s.operation_id))
    def test_wrong_epoch_key_cannot_export(self):
        self.start();r=self.write();self.reject_file(None,lambda:self.file.export_file(self.db,r.envelope_id,h('bad-key'),self.output));self.assertFalse(self.output.exists())
    def test_same_operation_changed_content(self):
        self.start();s=self.stage();self.source.write_bytes(b'changed');self.reject_file('FILE_OPERATION_CONFLICT',lambda:self.stage())
    def test_same_operation_changed_name(self):
        self.start();self.stage();self.reject_file('FILE_OPERATION_CONFLICT',lambda:self.stage(name='other.txt'))
    def test_same_operation_changed_mime(self):
        self.start();self.stage();self.reject_file('FILE_OPERATION_CONFLICT',lambda:self.stage(media_type='text/html'))
    def test_same_operation_changed_cache(self):
        self.start();self.stage();op,hd,p,c=self.request();self.reject_file('FILE_OPERATION_CONFLICT',lambda:self.stage(request=(op,hd,p,b'different')))
    def test_commit_changed_payload(self):
        self.start();w=self.fw();s=self.stage(w);op,hd,p,c=self.request();p=b'x'*len(p);self.reject_file('FILE_OPERATION_CONFLICT',lambda:w.commit(s,hd,p,c));self.assertEqual(self.count('blob_objects'),0)
    def test_commit_mutated_handle(self):
        self.start();w=self.fw();s=self.stage(w);self.reject_file('FILE_HANDLE_INVALID',lambda:w.commit(replace(s,manifest_id=b'x'*32),*self.request()[1:]))
    def test_partial_staging_resume_reuses_complete_chunks(self):
        self.start();seen=[]
        def hook(s):
            seen.append(s)
            if s=='file.chunk.0.durable':raise RuntimeError()
        w=self.fw(observer=hook);self.reject_file(None,lambda:self.stage(w));n=self.count('issued_nonces');w=self.fw();s=self.stage(w);self.assertGreater(self.count('issued_nonces'),n);self.assertEqual(s.chunks,2)
    def test_metadata_is_encrypted_at_rest(self):
        self.start();self.stage(name='private-name.txt');self.db._storage.connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        forbidden=[b'private-name.txt',b'text/plain',hashlib.sha256(self.data).digest(),self.data[:100]]
        for p in self.root.rglob('*'):
            if p.is_file():
                raw=p.read_bytes()
                for f in forbidden:self.assertNotIn(f,raw,str(p))
    def test_source_symlink(self):
        self.start();link=Path(self.tmp.name)/'link';link.symlink_to(self.source);self.reject_file('UNSAFE_PATH',lambda:self.fw().stage(*self.request(),link,name='a',media_type='text/plain'))
    def test_source_directory(self):
        self.start();self.reject_file('FILE_SOURCE_INVALID',lambda:self.fw().stage(*self.request(),Path(self.tmp.name),name='a',media_type='text/plain'))
    def test_source_fifo_does_not_block(self):
        self.start();p=Path(self.tmp.name)/'fifo';os.mkfifo(p);self.reject_file('FILE_SOURCE_INVALID',lambda:self.fw().stage(*self.request(),p,name='a',media_type='text/plain'))
    def test_input_inside_store_rejected(self):
        self.start();self.reject_file('UNSAFE_PATH',lambda:self.fw().stage(*self.request(),self.root/'store.sqlite',name='a',media_type='text/plain'))
    def test_output_inside_store_rejected(self):
        self.start();r=self.write();self.reject_file('UNSAFE_PATH',lambda:self.file.export_file(self.db,r.envelope_id,self.s.secret,self.root/'new-output'))
    def test_existing_output_not_overwritten(self):
        self.start();r=self.write();self.output.write_bytes(b'preserve');self.reject_file('DESTINATION_EXISTS',lambda:self.export(r.envelope_id));self.assertEqual(self.output.read_bytes(),b'preserve')
    def test_output_symlink_rejected(self):
        self.start();r=self.write();self.output.symlink_to(self.source);self.reject_file('UNSAFE_PATH',lambda:self.export(r.envelope_id));self.assertEqual(self.source.read_bytes(),self.data)
    def test_output_permissions_private(self):
        self.start();r=self.write();self.export(r.envelope_id);self.assertEqual(self.output.stat().st_mode & 0o777,0o600)
    def test_stage_job_budget(self):
        self.start();w=self.fw(max_jobs=1);self.stage(w);self.reject_file('FILE_STAGE_BUDGET',lambda:self.stage(w,request=self.request(op=2)))
    def test_staged_file_does_not_count_as_committed(self):
        self.start();s=self.stage();self.assertEqual(self.count('commit_ledger'),0);self.assertEqual(self.count('outbox'),0)
    def test_nonce_ledger_separate_operation_domain(self):
        self.start();s=self.stage();ops=[r[0] for r in self.db._storage.connection.execute('SELECT operation_id FROM local_operation_intents')];self.assertEqual(len(ops),1);self.assertNotEqual(ops[0],s.operation_id)
    def test_no_nonce_reuse_on_encryption_failure(self):
        self.start()
        def hook(s):
            if s=='file.chunk.0.reserved':raise RuntimeError()
        self.reject_file(None,lambda:self.stage(self.fw(observer=hook)));n=self.count('issued_nonces');self.stage();self.assertGreater(self.count('issued_nonces'),n)
    def test_source_changed_after_scan_not_committed(self):
        self.start()
        def hook(s):
            if s=='file.source.scanned':self.source.write_bytes(b'x'*len(self.data))
        self.reject_file('FILE_SOURCE_CHANGED',lambda:self.stage(self.fw(observer=hook)));self.assertEqual(self.count('commit_ledger'),0)
    def test_source_grows_during_generation(self):
        self.start()
        def hook(s):
            if s=='file.chunk.0.durable':
                with self.source.open('ab') as f:f.write(b'extra')
        self.reject_file('FILE_SOURCE_CHANGED',lambda:self.stage(self.fw(observer=hook)))
    def test_reader_cannot_stage(self):
        self.start();self.reject_file('NOT_AUTHORIZED',lambda:self.stage(self.fw(index=1),self.request(index=1)));self.assertEqual(self.count('issued_nonces'),0)
    def test_revocation_between_stage_and_commit(self):
        self.start();w=self.fw();s=self.stage(w);self.next_epoch(entries=self.s.entries[1:]);self.reject_file(None,lambda:w.commit(s,*self.request()[1:]));self.assertEqual(self.count('blob_objects'),0)
    def test_same_epoch_change_between_stage_and_commit(self):
        self.start();w=self.fw();s=self.stage(w);self.same_epoch();self.reject_file('AUTH_CONTEXT_MISMATCH',lambda:w.commit(s,*self.request()[1:]))
    def test_committed_query_after_revocation(self):
        self.start();w=self.fw();s=self.stage(w);r=w.commit(s,*self.request()[1:]);self.next_epoch(entries=self.s.entries[1:]);self.assertEqual(w.commit(s,*self.request()[1:]),r)
    def test_restore_without_staging_can_export(self):
        self.start();r=self.write();backup=Path(self.tmp.name)/'backup';self.db.export_snapshot(backup);dest=Path(self.tmp.name)/'restored';self.blob.BlobStore.restore_snapshot(backup,dest,provider=self.p,allow_unpatched_sqlite=True);self.close();self.db=self.blob.BlobStore.open(dest,provider=self.p,allow_unpatched_sqlite=True);self.export(r.envelope_id);self.assertEqual(self.output.read_bytes(),self.data)
    def test_restored_writer_remains_disabled(self):
        self.start();r=self.write();backup=Path(self.tmp.name)/'backup';self.db.export_snapshot(backup);dest=Path(self.tmp.name)/'restored';self.blob.BlobStore.restore_snapshot(backup,dest,provider=self.p,allow_unpatched_sqlite=True);self.close();self.db=self.blob.BlobStore.open(dest,provider=self.p,allow_unpatched_sqlite=True);self.reject_file('RESTORE_READ_ONLY',lambda:self.stage())
    def test_automerge_still_pending(self):
        self.start();r=self.write();self.assertEqual(self.db._storage.connection.execute('SELECT state FROM envelopes').fetchone()[0],'pending')
    def test_missing_committed_chunk_does_not_publish(self):
        self.start();r=self.write();b=self.db.attachments(r.envelope_id)[1];(self.root/'blocks'/b.locator.hex()).unlink();self.reject_file(None,lambda:self.export(r.envelope_id));self.assertFalse(self.output.exists())
    def test_tampered_committed_chunk_does_not_publish(self):
        self.start();r=self.write();b=self.db.attachments(r.envelope_id)[1];(self.root/'blocks'/b.locator.hex()).write_bytes(b'bad');self.reject_file(None,lambda:self.export(r.envelope_id));self.assertFalse(self.output.exists())
    def test_plaintext_never_published_until_hash_checked(self):
        self.start();r=self.write();seen=[]
        def hook(s):
            if s=='file.export.verified':seen.append(not self.output.exists())
        self.export(r.envelope_id,observer=hook);self.assertEqual(seen,[True])

class FileHardeningTests(FileTest):
    def test_rejected_reader_does_not_allocate_stage_job(self):
        self.start();self.reject_file('NOT_AUTHORIZED',lambda:self.stage(self.fw(index=1),self.request(index=1)))
        self.assertEqual(list((self.root/'staging').rglob('intent.cbor')),[])
        parent=self.root/'staging'/'files'
        self.assertTrue(not parent.exists() or not list(parent.iterdir()),'unauthorized call allocated a stage slot')
    def test_rejected_stale_header_does_not_allocate_stage_job(self):
        self.start();self.same_epoch();self.reject_file('AUTH_CONTEXT_MISMATCH',lambda:self.stage())
        parent=self.root/'staging'/'files';self.assertTrue(not parent.exists() or not list(parent.iterdir()))
    def test_internal_metadata_never_controls_output_path(self):
        self.start();w=self.fw();s=self.stage(w,name='not-output.txt');r=w.commit(s,*self.request()[1:]);self.export(r.envelope_id)
        self.assertFalse((self.output.parent/'not-output.txt').exists());self.assertTrue(self.output.exists())
    def test_independent_operations_use_distinct_file_ids(self):
        self.start();a=self.stage();b=self.stage(request=self.request(op=2));self.assertNotEqual(a.file_id,b.file_id);self.assertNotEqual(a.manifest_id,b.manifest_id)
    def test_multiple_files_in_different_envelopes(self):
        self.start();w=self.fw();a=self.write(w);req=self.request(op=2,sequence=2,previous=a.envelope_id);b=self.write(w,req)
        self.assertEqual(self.file.inspect_file(self.db,a.envelope_id,self.s.secret).size,self.file.inspect_file(self.db,b.envelope_id,self.s.secret).size)
    def test_inspect_performs_whole_file_hash_verification(self):
        self.start();r=self.write();i=self.file.inspect_file(self.db,r.envelope_id,self.s.secret);self.assertEqual(i.sha256,hashlib.sha256(self.data).digest());self.assertFalse(self.output.exists())
    def test_failed_stage_keeps_issued_nonce_but_no_reference(self):
        self.start()
        def stop(s):
            if s=='file.manifest.reserved':raise RuntimeError()
        self.reject_file('FILE_INTERRUPTED',lambda:self.stage(self.fw(observer=stop)));n=self.count('issued_nonces');self.assertGreater(n,0);self.assertEqual(self.count('blob_references'),0);self.stage();self.assertGreater(self.count('issued_nonces'),n)
    def test_bytes_source_is_not_an_implicit_in_memory_buffer(self):
        self.start();self.reject_file('FILE_SOURCE_INVALID',lambda:self.fw().stage(*self.request(),self.data,name='a',media_type='text/plain'))
    def test_closed_store_rejected(self):
        self.start();w=self.fw();self.close();self.reject_file('STORE_CLOSED',lambda:self.stage(w))
    def test_declared_file_name_surrogate_is_rejected(self):
        self.start();self.reject_file('FILE_METADATA_INVALID',lambda:self.stage(name='bad\ud800'))
