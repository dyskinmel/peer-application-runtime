import errno
from pathlib import Path
from dataclasses import replace
from retire_support import RetireTest,h,pr
from par_keeper.contract import reserve_payload,pin_values

class RetireLifecycle(RetireTest):
    def prepared(self,n=16):
        t=self.begin_index()
        if n:self.spool.execute(self.cmd('chunk',[t,0,self.bundle.index[:n]]))
        return t,self.retirement_request()
    def test_empty_stage_returns_declared_reservation_only(self):
        t,q=self.prepared(0);r=self.spool.retire(q)
        self.assertEqual(r['state'],'TOMBSTONED');self.assertEqual(r['reservation_released_bytes'],len(self.bundle.index))
        self.assertEqual(r['unlinked_payload_bytes'],0);self.assertFalse(r['keeper_mutated'])
    def test_partial_stage_reclaims_after_unlink(self):
        t,q=self.prepared();r=self.spool.retire(q)
        self.assertFalse(self.part(t).exists());self.assertEqual(r['unlinked_payload_bytes'],16)
        self.assertEqual(self.spool.diagnostics()['reserved_bytes'],0)
    def test_full_stage_can_be_abandoned(self):
        t,q=self.prepared(len(self.bundle.index));r=self.spool.retire(q);self.assertEqual(r['unlinked_payload_bytes'],len(self.bundle.index))
    def test_same_request_idempotent(self):
        t,q=self.prepared();one=self.spool.retire(q);self.assertEqual(self.spool.retire(q),one)
        self.assertEqual(self.spool.diagnostics()['records'],1)
    def test_reopen_preserves_tombstone(self):
        t,q=self.prepared();r=self.spool.retire(q);self.reopen();self.assertEqual(self.spool.retire(q),r)
    def test_original_begin_does_not_resurrect(self):
        t,q=self.prepared();b=self.beginraw;self.spool.retire(q);self.err('STAGE_RETIRED',lambda:self.spool.execute(b))
    def test_changed_begin_same_operation_does_not_resurrect(self):
        t,q=self.prepared();b=pr.check_command(self.p,self.beginraw)
        self.spool.retire(q);raw=self.cmd('begin',['index',self.rpin.index_id,1,h('wrong')],nonce=b[3])
        self.err('STAGE_RETIRED',lambda:self.spool.execute(raw))
    def test_chunk_after_retirement_denied(self):
        t,q=self.prepared();self.spool.retire(q);self.err('STAGE_RETIRED',lambda:self.spool.execute(self.cmd('chunk',[t,0,b'x'])))
    def test_progress_is_not_false_upload_success(self):
        t,q=self.prepared();self.spool.retire(q);self.err('STAGE_RETIRED',lambda:self.spool.execute(self.cmd('progress',t)))
    def test_stamp_rejects_retired_request(self):
        t,q=self.prepared();self.spool.retire(q);self.err('STAGE_RETIRED',lambda:self.spool.stamp(self.beginraw))
    def test_second_distinct_retirement_request_conflicts(self):
        t,q=self.prepared();self.spool.retire(q);self.err('RETIREMENT_CONFLICT',lambda:self.spool.retire(self.retirement_request()))
    def test_other_stage_unchanged(self):
        t,q=self.prepared();other=self.begin_index();raw=self.beginraw;self.spool.retire(q)
        self.assertEqual(self.spool.execute(raw)[0],other);self.assertTrue(self.part(other).exists())
    def test_payload_quota_reusable_record_not_reclaimed(self):
        self.spool.close()
        self.stage_root=self.path/'small';self.spool=self.spooltype(self.keeper,self.stage_root,max_bytes=len(self.bundle.index),max_records=2)
        t,q=self.prepared();self.err('STAGING_CAPACITY',self.begin_index);self.spool.retire(q)
        self.begin_index();self.assertEqual(self.spool.diagnostics()['records'],2)
        q2=self.retirement_request();self.spool.retire(q2);self.err('STAGING_CAPACITY',self.begin_index)
    def test_completed_handoff_stage_is_not_cancelled(self):
        self.upload_index();q=self.retirement_request();self.err('STAGE_COMMITTED',lambda:self.spool.retire(q))
    def test_keeper_payload_and_receipt_unchanged(self):
        lid=self.upload_all();before=self.keeper.diagnostics().copy();receipt=self.rc
        snapshots={oid:self.keeper.object_path(lid,oid).read_bytes() for oid in self.bundle.objects}
        t,q=self.prepared();self.spool.retire(q)
        self.assertEqual(self.keeper.diagnostics(),before)
        self.assertEqual(self.keeper._lease(lid)['receipt'],receipt)
        for oid,raw in snapshots.items():self.assertEqual(self.keeper.object_path(lid,oid).read_bytes(),raw)
    def test_pending_object_only_removes_staging(self):
        lid=self.upload_index();t,oid,raw,call=self.begin_object(lid);self.spool.execute(self.cmd('chunk',[t,0,raw[:16]],lid))
        q=self.retirement_request(begin=self.object_begin);before=self.keeper.diagnostics()['reserved_bytes'];self.spool.retire(q)
        self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],before)
        self.assertEqual(self.keeper._lease(lid)['state'],'reserved')
    def test_destination_commit_before_stage_ack_is_preserved(self):
        lid=self.upload_index();t,oid,raw,call=self.begin_object(lid);self.chunks(t,raw,lid)
        q=self.cmd('put',t,lid,call);rq=self.retirement_request(begin=self.object_begin)
        def fail(e):
            if e=='finalize.after_keeper':raise OSError(errno.EIO,'synthetic ack loss')
        self.spool.observer=fail;self.err('OUTCOME_UNKNOWN',lambda:self.spool.execute(q));self.reopen()
        before=self.keeper.object_path(lid,oid).read_bytes();self.spool.retire(rq)
        self.assertEqual(self.keeper.object_path(lid,oid).read_bytes(),before)
    def test_reopen_does_not_expire_staging(self):
        t,q=self.prepared();self.change_authority();self.reopen();self.assertTrue(self.part(t).exists())
        self.assertGreater(self.spool.diagnostics()['reserved_bytes'],0)
    def test_current_grant_cleans_expired_upload_capability(self):
        t,q=self.prepared();self.change_authority();self.spool.retire(self.retirement_request());self.assertFalse(self.part(t).exists())
    def test_stale_retirement_grant_no_change(self):
        t,q=self.prepared();self.change_authority();self.err(None,lambda:self.spool.retire(q));self.assertEqual(self.part(t).stat().st_size,16)
    def test_unknown_stage_rejected_without_allocation(self):
        t,q=self.prepared();self.spool.close()
        self.stage_root=self.path/'empty';self.spool=self.spooltype(self.keeper,self.stage_root)
        self.err('STAGE_UNKNOWN',lambda:self.spool.retire(q));self.assertEqual(self.spool.diagnostics()['records'],0)
    def test_status_exposes_only_staging_scope(self):
        t,q=self.prepared();self.spool.retire(q);r=self.spool.retirement_status(t)
        self.assertEqual(r['state'],'TOMBSTONED');self.assertFalse(r['record_reclaimed']);self.assertFalse(r['product_qualified'])
    def test_read_wire_methods_unchanged(self):
        self.assertEqual(pr.METHODS,frozenset(('begin','chunk','progress','reserve','put','seal')))
    def test_second_owner_rejected(self):self.err(None,lambda:self.spooltype(self.keeper,self.stage_root))
    def test_wrong_thread_rejected(self):
        from concurrent.futures import ThreadPoolExecutor
        t,q=self.prepared()
        with ThreadPoolExecutor(1) as ex:self.err('OWNER_REQUIRED',lambda:ex.submit(self.spool.retire,q).result())
