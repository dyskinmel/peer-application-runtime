from store_helpers import *
import os

class BlockTests(StoreCase):
    def test_blocks_published_before_references(self):
        data=b'sealed-block-example';p=self.prepare(blocks=(data,));self.commit(p)
        bid=hashlib.sha256(data).digest()
        self.assertEqual(self.s.read_block(bid),data)
        self.assertEqual(self.scalar('SELECT count(*) FROM envelope_blocks'),1)
        self.assertTrue(self.s.audit()['valid'])
    def test_identical_block_bytes_deduplicated(self):
        data=b'sealed-shared';p=self.prepare(blocks=(data,));self.commit(p)
        q=self.prepare(2,sequence=2,previous=p.envelope_id,blocks=(data,));self.commit(q)
        self.assertEqual(self.scalar('SELECT count(*) FROM blocks'),1)
        self.assertEqual(self.scalar('SELECT count(*) FROM envelope_blocks'),2)
    def test_missing_referenced_block_fails_audit(self):
        p=self.prepare(blocks=(b'sealed',));self.commit(p)
        (self.root/'blocks'/hashlib.sha256(b'sealed').hexdigest()).unlink()
        self.assertFalse(self.s.audit()['valid'])
    def test_corrupted_block_rejected_on_read(self):
        data=b'sealed';p=self.prepare(blocks=(data,));self.commit(p);bid=hashlib.sha256(data).digest()
        (self.root/'blocks'/bid.hex()).write_bytes(b'broken')
        self.err('BLOCK_CORRUPT',self.s.read_block,bid);self.assertFalse(self.s.audit()['valid'])
    def test_preexisting_corrupt_hash_path_not_overwritten(self):
        data=b'sealed';bid=hashlib.sha256(data).digest();path=self.root/'blocks'/bid.hex();path.write_bytes(b'wrong')
        self.err('BLOCK_CORRUPT',self.commit,self.prepare(blocks=(data,)))
        self.assertEqual(path.read_bytes(),b'wrong');self.assertEqual(self.scalar('SELECT count(*) FROM commit_ledger'),0)
    def test_uncommitted_published_block_is_orphan(self):
        p=self.prepare(blocks=(b'sealed-orphan',))
        self.s.observer=lambda stage: (_ for _ in ()).throw(RuntimeError('cut')) if stage=='commit.before_commit' else None
        self.err('LOCAL_ABORTED',self.commit,p);self.s.observer=None
        self.assertTrue(self.s.audit()['valid'])
        self.assertEqual(self.scalar('SELECT count(*) FROM blocks'),0)
        self.assertTrue(list((self.root/'blocks').iterdir()))
        result=self.s.collect_orphans();self.assertEqual(len(result['blocks_removed']),1)
    def test_gc_preserves_pending_and_retained_references(self):
        p=self.prepare(blocks=(b'sealed-retained',));self.commit(p)
        self.s.connection.execute("UPDATE outbox SET state='retained'")
        self.assertEqual(self.s.collect_orphans()['blocks_removed'],[])
        self.assertEqual(self.s.read_block(hashlib.sha256(b'sealed-retained').digest()),b'sealed-retained')
    def test_gc_refuses_structurally_corrupt_database(self):
        self.commit(self.prepare(blocks=(b'sealed',)))
        self.s.connection.execute('DELETE FROM outbox')
        self.err('CORRUPT_STORE',self.s.collect_orphans)
    def test_stage_bytes_not_counted_as_published(self):
        (self.root/'staging'/'a.part').write_bytes(b'incomplete')
        self.assertTrue(self.s.audit()['valid']);self.assertEqual(self.scalar('SELECT count(*) FROM blocks'),0)
        self.assertIn('a.part',self.s.collect_orphans()['staging_removed'])
    def test_block_paths_only_accept_fixed_ids(self):
        self.err('INVALID_INPUT',self.s.read_block,b'../outside')
    def test_symlink_block_rejected(self):
        data=b'sealed';bid=hashlib.sha256(data).digest();other=Path(self.tmp.name)/'outside';other.write_bytes(data)
        (self.root/'blocks'/bid.hex()).symlink_to(other)
        self.err('UNSAFE_PATH',self.commit,self.prepare(blocks=(data,)))
        self.assertEqual(other.read_bytes(),data)
    def test_symlink_database_rejected(self):
        self.s.close();db=self.root/'store.sqlite';target=Path(self.tmp.name)/'external.sqlite';db.rename(target);db.symlink_to(target)
        self.err('UNSAFE_PATH',self.api.Store.open,self.root,allow_unpatched_sqlite=True)
    def test_symlink_root_rejected(self):
        alias=Path(self.tmp.name)/'alias';alias.symlink_to(self.root,target_is_directory=True)
        self.err('UNSAFE_PATH',self.api.Store.open,alias,allow_unpatched_sqlite=True)
    def test_block_file_size_cap(self):
        self.err('INVALID_INPUT',self.commit,self.prepare(blocks=(b'x'*(262144+4097),)))
    def test_duplicate_block_ids_within_commit_rejected(self):
        self.err('INVALID_INPUT',self.commit,self.prepare(blocks=(b'x',b'x')))
    def test_gc_does_not_delete_unrecognized_files(self):
        path=self.root/'blocks'/'operator-note';path.write_bytes(b'keep')
        result=self.s.collect_orphans();self.assertTrue(path.exists());self.assertIn('operator-note',result['unrecognized'])

class PublishReviewTests(StoreCase):
    def test_existing_orphan_is_synced_before_reference_commit(self):
        data=b'previously-renamed';bid=hashlib.sha256(data).digest()
        (self.root/'blocks'/bid.hex()).write_bytes(data)
        synced=[];original=self.s.block_port.sync_file
        def tracked(fd):synced.append(fd);original(fd)
        self.s.block_port.sync_file=tracked
        self.commit(self.prepare(blocks=(data,)))
        self.assertTrue(synced,'existing file path must still be flushed before DB publication')
    def test_existing_unflushed_file_sync_failure_not_success(self):
        import errno
        data=b'previously-renamed';bid=hashlib.sha256(data).digest();(self.root/'blocks'/bid.hex()).write_bytes(data)
        def fail(fd):raise OSError(errno.EIO,'io error')
        self.s.block_port.sync_file=fail
        self.err('STORAGE_IO',self.commit,self.prepare(blocks=(data,)))
        self.assertEqual(self.scalar('SELECT count(*) FROM commit_ledger'),0)
