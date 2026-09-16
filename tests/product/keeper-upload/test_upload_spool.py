import hashlib,os
from dataclasses import replace
from upload_support import UploadTest,h,pr,pin_values,reserve_payload
from par_wire.codec import decode,encode

class UploadSpool(UploadTest):
    def test_index_reservation_and_retry(self):
        lid=self.upload_index();before=self.keeper.diagnostics()['reserved_bytes']
        self.assertEqual(self.spool.execute(self.rescmd),lid);self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],before)
    def test_complete_seal_retry_same_receipt(self):
        lid=self.upload_all();self.assertEqual(self.spool.execute(self.sealcmd),self.rc)
        self.assertEqual(self.status(lid)['generation'],1)
    def test_begin_idempotent_no_double_charge(self):
        token=self.begin_index();charge=self.spool.diagnostics()['reserved_bytes']
        self.assertEqual(self.spool.execute(self.beginraw)[0],token)
        self.assertEqual(self.spool.diagnostics()['reserved_bytes'],charge)
    def test_begin_same_operation_changed_input(self):
        self.begin_index(h('same'));self.err(None,lambda:self.spool.execute(self.cmd('begin',['index',self.rpin.index_id,1,h('s')],nonce=h('same'))))
    def test_chunk_replay_exact(self):
        token=self.begin_index();q=self.cmd('chunk',[token,0,self.bundle.index[:16]])
        self.assertEqual(self.spool.execute(q),self.spool.execute(q))
    def test_chunk_different_same_offset(self):
        token=self.begin_index();self.spool.execute(self.cmd('chunk',[token,0,self.bundle.index[:16]]))
        self.err(None,lambda:self.spool.execute(self.cmd('chunk',[token,0,b'x'*16])))
    def test_gap_rejected(self):
        t=self.begin_index();self.err(None,lambda:self.spool.execute(self.cmd('chunk',[t,1,b'x'])))
    def test_overlap_rejected(self):
        t=self.begin_index();self.spool.execute(self.cmd('chunk',[t,0,self.bundle.index[:16]]))
        self.err(None,lambda:self.spool.execute(self.cmd('chunk',[t,15,self.bundle.index[15:20]])))
    def test_partial_progress_reopen(self):
        t=self.begin_index();self.spool.execute(self.cmd('chunk',[t,0,self.bundle.index[:16]]));self.reopen()
        self.assertEqual(self.spool.execute(self.cmd('progress',t))[1],16)
    def test_unacknowledged_tail_truncated(self):
        t=self.begin_index();self.spool.execute(self.cmd('chunk',[t,0,self.bundle.index[:16]]))
        with (self.stage_root/(t.hex()+'.part')).open('ab') as f:f.write(b'junk')
        self.reopen();self.assertEqual((self.stage_root/(t.hex()+'.part')).stat().st_size,16)
    def test_acknowledged_prefix_corrupt_rejected(self):
        t=self.begin_index();self.chunks(t,self.bundle.index);(self.stage_root/(t.hex()+'.part')).write_bytes(b'x')
        self.err(None,self.reopen)
    def test_incomplete_index_no_reservation(self):
        t=self.begin_index();c=self.call('reserve',payload=reserve_payload(self.bundle.index,self.rpin,30))
        self.err(None,lambda:self.spool.execute(self.cmd('reserve',[t,pin_values(self.rpin),30],call=c)))
        self.assertEqual(self.keeper.diagnostics()['leases'],0)
    def test_wrong_index_digest_no_reservation(self):
        t=self.begin_index();raw=bytearray(self.bundle.index);raw[-1]^=1;self.chunks(t,bytes(raw))
        c=self.call('reserve',payload=reserve_payload(self.bundle.index,self.rpin,30))
        self.err(None,lambda:self.spool.execute(self.cmd('reserve',[t,pin_values(self.rpin),30],call=c)))
    def test_missing_objects_no_seal(self):
        lid=self.upload_index();self.err(None,lambda:self.spool.execute(self.cmd('seal',None,lid,self.call('seal',lid))))
    def test_object_stage_is_inventory_scoped(self):
        lid=self.upload_index();oid=h('unknown');c=self.call('put',lid,[oid,1,hashlib.sha256(b'x').digest()])
        self.err(None,lambda:self.spool.execute(self.cmd('begin',['object',oid,1,hashlib.sha256(b'x').digest()],lid,c)))
    def test_committed_stage_releases_payload_quota_not_history(self):
        lid=self.upload_index();self.assertEqual(self.spool.diagnostics()['reserved_bytes'],0)
        self.assertEqual(self.spool.diagnostics()['records'],1)
        self.assertEqual(list(self.stage_root.glob('*.part')),[])
    def test_committed_object_replay_after_restart(self):
        lid=self.upload_index();t=self.upload_object(lid,sorted(self.bundle.objects)[0]);q=self.putcmd
        self.reopen();self.assertEqual(self.spool.execute(q),sorted(self.bundle.objects)[0])
        self.assertTrue(self.spool.execute(self.cmd('progress',t,lid))[4])
    def test_committed_put_corruption_not_success(self):
        lid=self.upload_index();oid=sorted(self.bundle.objects)[0];self.upload_object(lid,oid)
        self.keeper.object_path(lid,oid).write_bytes(b'broken');self.err(None,lambda:self.spool.execute(self.putcmd))
    def test_stale_capability_no_new_stage(self):
        self.keeper.update_authority(replace(self.authority,head=h('new'),sequence=2))
        self.err(None,self.begin_index);self.assertEqual(self.spool.diagnostics()['records'],0)
    def test_authority_change_blocks_existing_stage(self):
        t=self.begin_index();self.keeper.update_authority(replace(self.authority,head=h('new'),sequence=2))
        self.err(None,lambda:self.chunks(t,self.bundle.index))
    def test_read_only_grant_cannot_stage(self):
        cap=self.k.issue_capability(self.p,self.s.owner,self.authority,self.kp,self.cp,self.rpin.index_id,['get'],60,h('read'))
        q=self.cmd('begin',['index',self.rpin.index_id,len(self.bundle.index),hashlib.sha256(self.bundle.index).digest()],cap=cap)
        self.err(None,lambda:self.spool.execute(q));self.assertEqual(self.spool.diagnostics()['records'],0)
    def test_staging_quota_before_allocation(self):
        self.spool.close();import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.spool=self.spooltype(self.keeper,d,max_bytes=1)
            self.err(None,self.begin_index);self.assertEqual(self.spool.diagnostics()['records'],0)
    def test_symlink_stage_root_rejected(self):
        p=self.path/'linked';p.symlink_to(self.stage_root);self.err(None,lambda:self.spooltype(self.keeper,p))
    def test_stage_payload_hardlink_rejected(self):
        t=self.begin_index();os.link(self.stage_root/(t.hex()+'.part'),self.path/'duplicate')
        self.err(None,lambda:self.spool.execute(self.cmd('progress',t)))
    def test_second_spool_writer_rejected(self):self.err(None,lambda:self.spooltype(self.keeper,self.stage_root))
    def test_no_arbitrary_files_on_reopen(self):
        (self.stage_root/'unknown').write_bytes(b'x');self.err(None,self.reopen)
    def test_current_read_pin_does_not_make_appendable_object_mutable(self):
        lid=self.upload_all();oid=sorted(self.bundle.objects)[0]
        with self.keeper.reader(lid,oid,self.cap,self.call('get',lid,oid)):
            self.err(None,lambda:self.begin_object(lid,oid))
    def test_existing_stage_directory_must_be_private(self):
        self.spool.close();os.chmod(self.stage_root,0o755)
        try:self.err(None,lambda:self.spooltype(self.keeper,self.stage_root))
        finally:os.chmod(self.stage_root,0o700)
    def test_stage_directory_permissions_rechecked_live(self):
        token=self.begin_index();os.chmod(self.stage_root,0o755)
        try:self.err(None,lambda:self.spool.execute(self.cmd('progress',token)))
        finally:os.chmod(self.stage_root,0o700)
    def test_metadata_permissions_rechecked_on_resume(self):
        token=self.begin_index();f=self.stage_root/(token.hex()+'.cbor');os.chmod(f,0o644)
        try:self.err(None,self.reopen)
        finally:os.chmod(f,0o600)
    def test_payload_permissions_rechecked_before_progress(self):
        token=self.begin_index();f=self.stage_root/(token.hex()+'.part');os.chmod(f,0o644)
        try:self.err(None,lambda:self.spool.execute(self.cmd('progress',token)))
        finally:os.chmod(f,0o600)
