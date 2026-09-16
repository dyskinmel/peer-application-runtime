import os,sqlite3
from dataclasses import replace
from gc_support import GCTest,h

class GCLifecycle(GCTest):
    def test_collect_then_exact_retry(self):
        lid,req=self.released();before=self.keeper.diagnostics()['reserved_bytes']
        a=self.gc(lid,req);self.assertEqual(a,self.gc(lid,req))
        d=self.keeper.diagnostics();self.assertEqual(d['reserved_bytes'],len(self.bundle.index));self.assertLess(d['reserved_bytes'],before)
        self.assertEqual(self.status(lid)['state'],'RECLAIMED')
        self.assertFalse(any(self.keeper.object_path(lid,x).exists() for x in self.bundle.objects))
    def test_mark_does_not_refund_or_unlink(self):
        lid,req=self.released();self.keeper.mark(lid,self.cap,req)
        self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total)
        self.assertEqual(self.status(lid)['state'],'GC_PENDING')
        self.assertTrue(all(self.keeper.object_path(lid,x).exists() for x in self.bundle.objects))
    def test_second_request_conflicts(self):
        lid,req=self.released();self.keeper.mark(lid,self.cap,req)
        self.err('GC_CONFLICT',lambda:self.gc(lid,self.gc_request(lid)))
    def test_restart_mark_then_resume(self):
        lid,req=self.released();self.keeper.mark(lid,self.cap,req);self.reopen()
        self.assertEqual(self.status(lid)['state'],'GC_PENDING');a=self.gc(lid,req);self.reopen();self.assertEqual(a,self.gc(lid,req))
    def test_restart_done_no_refund_twice(self):
        lid,req=self.released();a=self.gc(lid,req);self.reopen();before=self.keeper.diagnostics()['reserved_bytes']
        self.assertEqual(a,self.gc(lid,req));self.assertEqual(before,self.keeper.diagnostics()['reserved_bytes'])
    def test_reader_pin_blocks_mark(self):
        lid,_=self.ready();oid=next(iter(self.bundle.objects))
        with self.keeper.reader(lid,oid,self.cap,self.call('get',lid,oid)) as reader:
            self.assertEqual(reader.read(),self.bundle.objects[oid]);self.release(lid);req=self.gc_request(lid)
            self.err('PINNED',lambda:self.gc(lid,req));self.err('LEASE_RELEASED',reader.read)
        self.gc(lid,req)
    def test_reader_invalid_after_close(self):
        lid,_=self.ready();oid=next(iter(self.bundle.objects))
        with self.keeper.reader(lid,oid,self.cap,self.call('get',lid,oid)) as reader:
            self.keeper.close();self.err('CLOSED',reader.read)
    def test_reader_invalid_after_context(self):
        lid,_=self.ready();oid=next(iter(self.bundle.objects))
        with self.keeper.reader(lid,oid,self.cap,self.call('get',lid,oid)) as reader:pass
        self.err('PIN_CLOSED',reader.read)
    def test_nested_pins(self):
        lid,_=self.ready();oid=next(iter(self.bundle.objects))
        with self.keeper.reader(lid,oid,self.cap,self.call('get',lid,oid)):
            with self.keeper.reader(lid,oid,self.cap,self.call('get',lid,oid)):
                self.release(lid);req=self.gc_request(lid);self.err('PINNED',lambda:self.gc(lid,req))
            self.err('PINNED',lambda:self.gc(lid,req))
        self.gc(lid,req)
    def test_unknown_path_blocks_without_refund(self):
        lid,req=self.released();p=self.path/'objects'/lid.hex()/'unexpected';p.write_bytes(b'x')
        self.err('GC_UNKNOWN_FILE',lambda:self.gc(lid,req));self.assertTrue(p.exists());self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total)
    def test_symlink_rejected(self):
        lid,req=self.released();oid=next(iter(self.bundle.objects));p=self.keeper.object_path(lid,oid);raw=p.read_bytes();p.unlink()
        outside=self.path.parent/'not-managed';outside.write_bytes(raw);p.symlink_to(outside)
        self.err(None,lambda:self.gc(lid,req));self.assertTrue(outside.exists())
    def test_hardlink_rejected(self):
        lid,req=self.released();p=self.keeper.object_path(lid,next(iter(self.bundle.objects)));outside=self.path.parent/'hardlink';os.link(p,outside)
        self.err('GC_UNSAFE_FILE',lambda:self.gc(lid,req));self.assertTrue(outside.exists())
    def test_content_mismatch_rejected_before_mark(self):
        lid,req=self.released();p=self.keeper.object_path(lid,next(iter(self.bundle.objects)));p.write_bytes(b'bad')
        self.err('OBJECT_HASH',lambda:self.gc(lid,req));self.assertEqual(self.keeper.connection.execute('SELECT count(*) FROM gc_jobs').fetchone()[0],0)
    def test_other_lease_remains_readable(self):
        lid,req=self.released();other=self.reserve();self.fill(other);self.seal(other);self.gc(lid,req)
        oid=next(iter(self.bundle.objects));self.assertEqual(self.get(other,oid),self.bundle.objects[oid])
    def test_partial_reservation_refund_not_physical_free_claim(self):
        self.open_keeper();lid=self.reserve();oid=next(iter(self.bundle.objects));self.put(lid,oid);self.release(lid);req=self.gc_request(lid)
        raw=self.gc(lid,req);r=self.g.verify_result(self.p,raw,self.kp,req)
        self.assertEqual(r['unlinked_payload_bytes'],len(self.bundle.objects[oid]));self.assertEqual(r['reservation_released_bytes'],self.total-len(self.bundle.index))
    def test_get_after_gc_denied(self):
        lid,req=self.released();self.gc(lid,req);self.err('LEASE_RELEASED',lambda:self.get(lid,next(iter(self.bundle.objects))))
    def test_renew_after_gc_denied(self):
        lid,req=self.released();self.gc(lid,req);self.err('LEASE_RELEASED',lambda:self.renew(lid))
    def test_reserved_payload_capacity_reusable(self):
        lid,req=self.released(quota_bytes=self.total+len(self.bundle.index));self.gc(lid,req)
        lid2=self.reserve();self.assertNotEqual(lid,lid2)
    def test_result_tamper_detected_on_open(self):
        lid,req=self.released();self.gc(lid,req);self.keeper.close()
        c=sqlite3.connect(self.path/'keeper.sqlite');c.execute("UPDATE gc_jobs SET result=X'00'");c.commit();c.close()
        self.err('CORRUPT_GC',self.open_keeper)
    def test_migration_explicit_and_old_open_rejects(self):
        self.keeper=self.k.Keeper(self.path,self.p,self.ks,self.authority,quota_bytes=self.total*3,clock=self.clock,allow_unpatched_sqlite=True)
        lid=self.reserve();self.fill(lid);self.seal(lid);self.release(lid);self.keeper.close()
        self.err('SCHEMA_MISMATCH',self.open_keeper)
        self.open_keeper(migrate_v1=True);req=self.gc_request(lid);self.gc(lid,req);self.keeper.close()
        self.err('SCHEMA_MISMATCH',lambda:self.k.Keeper(self.path,self.p,self.ks,self.authority,quota_bytes=self.total*3,clock=self.clock,allow_unpatched_sqlite=True))
