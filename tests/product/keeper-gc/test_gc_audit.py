import os,sqlite3
from dataclasses import replace
from gc_support import GCTest,h
from par_wire.codec import encode,decode

class GCAudit(GCTest):
    def test_marked_credit_forgery_rejected(self):
        lid,req=self.released();self.keeper.mark(lid,self.cap,req)
        self.keeper.connection.execute('PRAGMA ignore_check_constraints=ON');self.keeper.connection.execute('UPDATE gc_jobs SET credit=1')
        self.keeper.close();self.err('CORRUPT_STORE',self.open_keeper)
    def test_intent_signature_changed_rejected(self):
        lid,req=self.released();self.keeper.mark(lid,self.cap,req);c=self.keeper.connection
        raw=c.execute('SELECT intent FROM gc_jobs').fetchone()[0];v=decode(raw);v[1]=b'Z'*64;c.execute('UPDATE gc_jobs SET intent=?',(encode(v),))
        self.err('CORRUPT_GC',lambda:self.gc(lid,req))
    def test_intent_request_mismatch_rejected(self):
        lid,req=self.released();self.keeper.mark(lid,self.cap,req)
        self.keeper.connection.execute('UPDATE gc_jobs SET request=?',(self.gc_request(lid),))
        self.keeper.close();self.err('CORRUPT_GC',self.open_keeper)
    def test_done_credit_tamper_rejected(self):
        lid,req=self.released();self.gc(lid,req);self.keeper.connection.execute('UPDATE gc_jobs SET credit=credit-1')
        self.keeper.close();self.err('CORRUPT_GC',self.open_keeper)
    def test_done_file_reappearance_rejected_on_restart(self):
        lid,req=self.released();self.gc(lid,req);(self.path/'objects'/lid.hex()).mkdir();self.keeper.close()
        self.err('CORRUPT_GC',self.open_keeper)
    def test_missing_recorded_before_mark_not_claimed_deleted(self):
        lid,req=self.released();self.keeper.object_path(lid,next(iter(self.bundle.objects))).unlink()
        self.err('GC_OBJECT_MISSING',lambda:self.gc(lid,req))
    def test_unrecorded_valid_publication_is_collected(self):
        lid,req=self.released();self.keeper.connection.execute('DELETE FROM stored_objects')
        self.gc(lid,req);self.assertEqual(self.status(lid)['state'],'RECLAIMED')
    def test_corruption_after_mark_stops_sweep(self):
        lid,req=self.released();self.keeper.mark(lid,self.cap,req);oid=next(iter(self.bundle.objects));self.keeper.object_path(lid,oid).write_bytes(b'bad')
        self.err('OBJECT_HASH',lambda:self.gc(lid,req));self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total)
    def test_unknown_file_after_mark_stops_sweep(self):
        lid,req=self.released();self.keeper.mark(lid,self.cap,req);(self.path/'objects'/lid.hex()/'x').write_bytes(b'x')
        self.err('GC_UNKNOWN_FILE',lambda:self.gc(lid,req))
    def test_authority_change_between_mark_and_collect_stops(self):
        lid,req=self.released();self.keeper.mark(lid,self.cap,req);self.keeper.update_authority(replace(self.authority,head=h('later'),sequence=2))
        self.err('CAPABILITY_SCOPE',lambda:self.gc(lid,req));self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total)
    def test_empty_reservation_can_be_cancelled(self):
        self.open_keeper();lid=self.reserve();self.release(lid);req=self.gc_request(lid)
        v=self.g.verify_result(self.p,self.gc(lid,req),self.kp,req);self.assertEqual(v['unlinked_payload_bytes'],0)
    def test_schema_extra_table_rejected(self):
        lid,req=self.released();self.keeper.connection.execute('CREATE TABLE unknown(x)');self.keeper.close();self.err('SCHEMA_MISMATCH',self.open_keeper)
    def test_gc_limit_keeps_payload_and_credit(self):
        lid,req=self.released()
        from unittest.mock import patch
        with patch('par_keeper_gc.store.MAX_JOBS',0):self.err('GC_LIMIT',lambda:self.gc(lid,req))
        self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total)
    def test_completed_lease_slot_reusable(self):
        lid,req=self.released(max_leases=1);self.gc(lid,req);other=self.reserve();self.assertNotEqual(lid,other)
        self.keeper.close();self.open_keeper(max_leases=1);self.assertEqual(self.keeper.diagnostics()['active_lease_slots'],1)
    def test_pending_no_get_pin(self):
        lid,req=self.released();self.keeper.mark(lid,self.cap,req);oid=next(iter(self.bundle.objects))
        def run():
            with self.keeper.reader(lid,oid,self.cap,self.call('get',lid,oid)):pass
        self.err('LEASE_RELEASED',run)
    def test_legacy_release_request_cannot_delete(self):
        lid,_=self.released();self.err('CONTRACT_SCHEMA',lambda:self.gc(lid,self.releasecall))
    def test_gc_receipt_wrong_request_rejected(self):
        lid,req=self.released();result=self.gc(lid,req);self.err('GC_SCOPE',lambda:self.g.verify_result(self.p,result,self.kp,self.gc_request(lid)))
    def test_gc_receipt_bitflip_rejected(self):
        lid,req=self.released();result=self.gc(lid,req);v=decode(result);v[1]=b'R'*64
        self.err('GC_SIGNATURE',lambda:self.g.verify_result(self.p,encode(v),self.kp,req))

    def test_done_payload_reappears_before_retry_rejected(self):
        lid,req=self.released();self.gc(lid,req);path=self.path/'objects'/lid.hex();path.mkdir()
        self.err('CORRUPT_GC',lambda:self.gc(lid,req))
    def test_done_payload_reappears_before_reserve_rejected(self):
        lid,req=self.released();self.gc(lid,req);(self.path/'objects'/lid.hex()).mkdir()
        self.err('CORRUPT_GC',self.reserve)
    def test_done_payload_reappears_before_diagnostics_rejected(self):
        lid,req=self.released();self.gc(lid,req);(self.path/'objects'/lid.hex()).mkdir()
        self.err('CORRUPT_GC',self.keeper.diagnostics)
