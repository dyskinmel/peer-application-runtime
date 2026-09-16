import os
from pathlib import Path
from dataclasses import replace
from retire_support import RetireTest,h
from par_wire.codec import encode,decode
from par_keeper_upload.spool import Spool

class RetireAudit(RetireTest):
    def prepared(self):
        t=self.begin_index();self.spool.execute(self.cmd('chunk',[t,0,self.bundle.index[:16]]));return t,self.retirement_request()
    def pending(self):
        t,q=self.prepared()
        def stop(e):
            if e=='retirement.intent.after_meta':raise OSError('injected interruption')
        self.spool.observer=stop;self.err('OUTCOME_UNKNOWN',lambda:self.spool.retire(q));self.reopen();return t,q
    def test_old_reader_refuses_new_schema(self):
        self.spool.close();self.err(None,lambda:Spool(self.keeper,self.stage_root))
    def test_old_schema_requires_explicit_migration(self):
        self.spool.close();self.stage_root=self.path/'old'
        old=Spool(self.keeper,self.stage_root);old.close()
        self.err('STAGING_MIGRATION_REQUIRED',lambda:self.spooltype(self.keeper,self.stage_root))
        self.spool=self.spooltype(self.keeper,self.stage_root,allow_migrate=True)
    def test_migration_preserves_active_bytes(self):
        self.spool.close();self.stage_root=self.path/'old2';self.spool=Spool(self.keeper,self.stage_root)
        t=self.begin_index();self.spool.execute(self.cmd('chunk',[t,0,self.bundle.index[:16]]));self.spool.close()
        self.spool=self.spooltype(self.keeper,self.stage_root,allow_migrate=True)
        self.assertEqual(self.spool.execute(self.cmd('progress',t))[1],16)
    def test_intent_reopen_does_not_delete_or_refund(self):
        t,q=self.pending();self.assertTrue(self.part(t).exists());self.assertEqual(self.spool.diagnostics()['reserved_bytes'],len(self.bundle.index))
    def test_pending_blocks_original_begin(self):
        t,q=self.pending();self.err('RETIREMENT_PENDING',lambda:self.spool.execute(self.beginraw))
    def test_pending_blocks_handoff(self):
        t,q=self.pending();self.err('RETIREMENT_PENDING',lambda:self.spool.stamp(self.cmd('progress',t)))
    def test_tombstone_reappeared_payload_rejected(self):
        t,q=self.prepared();self.spool.retire(q);self.part(t).write_bytes(self.bundle.index[:16]);self.part(t).chmod(0o600)
        self.err(None,self.reopen)
    def test_live_tombstone_reappearance_blocks_capacity(self):
        t,q=self.prepared();self.spool.retire(q);self.part(t).write_bytes(b'x');self.part(t).chmod(0o600)
        self.err(None,self.spool.diagnostics);self.err(None,self.begin_index)
    def test_sidecar_signature_corruption_rejected(self):
        t,q=self.prepared();self.spool.retire(q);p=self.stage_root/(t.hex()+'.retirement');b=bytearray(p.read_bytes());b[-1]^=1;p.write_bytes(b)
        self.err(None,self.reopen)
    def test_original_metadata_changed_after_intent_rejected(self):
        t,q=self.pending();p=self.stage_root/(t.hex()+'.cbor');m=decode(p.read_bytes());m[3]=0;p.write_bytes(encode(m))
        self.err(None,self.reopen)
    def test_inode_replacement_not_deleted(self):
        t,q=self.pending();p=self.part(t);p.rename(p.with_suffix('.kept'));p.write_bytes(self.bundle.index[:16]);p.chmod(0o600)
        self.err(None,lambda:self.spool.retire(q));self.assertTrue(p.exists())
    def test_corrupt_confirmed_prefix_not_silently_deleted(self):
        t,q=self.prepared();self.part(t).write_bytes(b'x'*16)
        self.err(None,lambda:self.spool.retire(q));self.assertTrue(self.part(t).exists())
    def test_hardlink_refused(self):
        t,q=self.prepared();os.link(self.part(t),self.path/'linked')
        self.err(None,lambda:self.spool.retire(q));self.assertTrue(self.part(t).exists())
    def test_symlink_refused(self):
        t,q=self.prepared();self.part(t).unlink();target=self.path/'target';target.write_bytes(b'preserve');self.part(t).symlink_to(target)
        self.err(None,lambda:self.spool.retire(q));self.assertEqual(target.read_bytes(),b'preserve')
    def test_metadata_permissions_refused(self):
        t,q=self.pending();p=self.stage_root/(t.hex()+'.retirement');p.chmod(0o644)
        try:self.err(None,self.reopen)
        finally:p.chmod(0o600)
    def test_unknown_file_refused_not_removed(self):
        p=self.stage_root/'unknown';p.write_bytes(b'keep');p.chmod(0o600);self.err(None,self.reopen);self.assertTrue(p.exists())
    def test_rebind_after_authority_change(self):
        t,q=self.pending();self.change_authority();fresh=self.retirement_request()
        self.err(None,lambda:self.spool.retire(q));self.err('RETIREMENT_REBIND_REQUIRED',lambda:self.spool.retire(fresh))
        self.spool.rebind(fresh);self.assertTrue(self.part(t).exists());self.spool.retire(fresh);self.assertFalse(self.part(t).exists())
    def test_rebind_same_request_idempotent(self):
        t,q=self.pending();self.change_authority();fresh=self.retirement_request();one=self.spool.rebind(fresh)
        self.assertEqual(one,self.spool.rebind(fresh))
    def test_rebind_same_authority_with_new_request_refused(self):
        t,q=self.pending();self.err('RETIREMENT_REBIND_ORDER',lambda:self.spool.rebind(self.retirement_request()))
    def test_rebind_limit_bounded(self):
        t,q=self.pending()
        for _ in range(7):self.change_authority();q=self.retirement_request();self.spool.rebind(q)
        self.change_authority();self.err('RETIREMENT_REBIND_LIMIT',lambda:self.spool.rebind(self.retirement_request()))
    def test_completed_cannot_rebind(self):
        t,q=self.prepared();self.spool.retire(q);self.change_authority();self.err('STAGE_RETIRED',lambda:self.spool.rebind(self.retirement_request()))
    def test_operation_id_cannot_bind_two_stages(self):
        t,q=self.prepared();op=h('duplicate-op');q=self.retirement_request(operation=op);self.spool.retire(q)
        self.begin_index();other=self.retirement_request(operation=op);self.err('OPERATION_CONFLICT',lambda:self.spool.retire(other))

    def test_replay_and_audit_do_not_create_new_signatures(self):
        from unittest.mock import patch
        t,q=self.prepared();result=self.spool.retire(q)
        with patch.object(self.p,'sign',side_effect=AssertionError('read verification attempted signing')):
            self.reopen();self.spool.diagnostics();self.spool.retirement_status(t)
            self.assertEqual(self.spool.retire(q),result)
