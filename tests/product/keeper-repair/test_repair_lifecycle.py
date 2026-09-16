from repair_support import RepairTest,h,replace
from par_keeper.contract import split

class RepairLifecycle(RepairTest):
    def test_missing_object_restored_without_lease_change(self):
        lid,rc=self.ready();oid=self.damage(lid);row=dict(self.keeper._lease(lid));quota=self.keeper.diagnostics()['reserved_bytes']
        result=self.repair(lid,self.repair_request(lid,[oid]));self.assertEqual(self.get(lid,oid),self.bundle.objects[oid])
        self.assertEqual(dict(self.keeper._lease(lid)),row);self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],quota)
        v=self.r.verify_result(self.p,result,self.kp);self.assertEqual(v['state'],'TARGET_BYTES_VERIFIED');self.assertFalse(v['recipient_validated'])
    def test_corrupt_object_replaced(self):
        lid,_=self.ready();oid=self.damage(lid,'corrupt');self.repair(lid,self.repair_request(lid,[oid]));self.assertEqual(self.get(lid,oid),self.bundle.objects[oid])
    def test_empty_object_replaced(self):
        lid,_=self.ready();oid=self.damage(lid,'empty');self.repair(lid,self.repair_request(lid,[oid]));self.assertEqual(self.get(lid,oid),self.bundle.objects[oid])
    def test_same_request_same_result_after_reopen(self):
        lid,_=self.ready();oid=self.damage(lid);req=self.repair_request(lid,[oid]);a=self.repair(lid,req);self.reopen();self.assertEqual(self.repair(lid,req),a)
    def test_bad_replacement_rejected_before_intent(self):
        lid,_=self.ready();oid=self.damage(lid);req=self.repair_request(lid,[oid]);self.err('OBJECT_HASH',lambda:self.repair(lid,req,{oid:b'wrong'}));self.assertEqual(self.keeper.diagnostics()['repair_jobs'],0)
    def test_wrong_object_set_rejected(self):
        lid,_=self.ready();oid=self.damage(lid);req=self.repair_request(lid,[oid]);self.err('REPAIR_OBJECT_SET',lambda:self.repair(lid,req,{}))
    def test_subset_repair_does_not_claim_all_bytes(self):
        lid,_=self.ready();a,b=sorted(self.bundle.objects)[:2];self.damage(lid,oid=a);self.damage(lid,oid=b)
        r=self.repair(lid,self.repair_request(lid,[a]));self.assertFalse(self.r.verify_result(self.p,r,self.kp)['all_bytes_observed']);self.assertEqual(self.status(lid)['state'],'DEGRADED')
    def test_multi_object_repair(self):
        lid,_=self.ready();oids=sorted(self.bundle.objects)[:3]
        for oid in oids:self.damage(lid,oid=oid)
        self.repair(lid,self.repair_request(lid,oids));self.assertEqual(self.status(lid)['state'],'RETAINED_ACTIVE')
    def test_released_not_repaired(self):
        lid,_=self.ready();self.release(lid);self.err('LEASE_RELEASED',lambda:self.repair(lid,self.repair_request(lid)))
    def test_reserved_not_repaired(self):
        self.open_keeper();lid=self.reserve();req=self.r.make_request(self.p,self.cs,self.cap,lid,1,self.rpin.index_id,[sorted(self.bundle.objects)[0]],h('reserved-attempt'));self.err('NOT_SEALED',lambda:self.repair(lid,req))
    def test_expired_stays_expired(self):
        lid,_=self.ready();self.clock.ns+=40*10**9;oid=self.damage(lid);self.repair(lid,self.repair_request(lid,[oid]));self.assertEqual(self.status(lid)['state'],'EXPIRED_RETAINED')
    def test_unknown_stays_unknown(self):
        lid,_=self.ready();self.clock.boot=h('new-boot');oid=self.damage(lid);self.repair(lid,self.repair_request(lid,[oid]));self.assertEqual(self.status(lid)['state'],'UNKNOWN_RETAINED')
    def test_reader_pin_blocks_repair(self):
        lid,_=self.ready();oid=sorted(self.bundle.objects)[0];req=self.repair_request(lid,[oid])
        with self.keeper.reader(lid,oid,self.cap,self.call('get',lid,oid)):
            self.err('PINNED',lambda:self.repair(lid,req))
        self.repair(lid,req)
    def test_pending_repair_blocks_gc_until_cancel(self):
        lid,_=self.ready();oid=self.damage(lid);req=self.repair_request(lid,[oid]);job=self.keeper.mark_repair(lid,self.cap,req)['job_id'];self.release(lid)
        self.err('REPAIR_PENDING',lambda:self.gc(lid,self.gc_request(lid)))
        c=self.cancel_request(lid,job);r=self.keeper.cancel_repair(lid,self.cap,c);self.assertEqual(r,self.keeper.cancel_repair(lid,self.cap,c))
        self.assertEqual(self.keeper.diagnostics()['repair_staging_reserved_bytes'],0)
    def test_authority_update_blocks_pending(self):
        lid,_=self.ready();oid=self.damage(lid);req=self.repair_request(lid,[oid]);self.keeper.mark_repair(lid,self.cap,req)
        self.authority=replace(self.authority,head=h('next-head'),sequence=2);self.keeper.update_authority(self.authority)
        self.err('CAPABILITY_SCOPE',lambda:self.repair(lid,req))
    def test_same_nonce_different_targets_rejected(self):
        lid,_=self.ready();a,b=sorted(self.bundle.objects)[:2];n=h('same-nonce');one=self.repair_request(lid,[a],n);two=self.repair_request(lid,[b],n)
        self.keeper.mark_repair(lid,self.cap,one);self.err('REPAIR_CONFLICT',lambda:self.repair(lid,two))
    def test_receipt_unchanged_after_repair(self):
        lid,rc=self.ready();oid=self.damage(lid);self.repair(lid,self.repair_request(lid,[oid]));self.assertEqual(self.keeper.receipt(lid,self.cap,self.call('receipt',lid)),rc)
    def test_done_receipt_is_historical_not_current_health(self):
        lid,_=self.ready();req=self.repair_request(lid);r=self.repair(lid,req);self.damage(lid);self.assertEqual(self.repair(lid,req),r);self.assertEqual(self.status(lid)['state'],'DEGRADED')
    def test_reclaimed_not_resurrected(self):
        lid,_=self.ready();self.release(lid);self.gc(lid,self.gc_request(lid));self.err('LEASE_RELEASED',lambda:self.repair(lid,self.repair_request(lid)))
    def test_new_request_needed_for_new_corruption(self):
        lid,_=self.ready();req=self.repair_request(lid);r=self.repair(lid,req);self.damage(lid);r2=self.repair(lid,self.repair_request(lid));self.assertNotEqual(r,r2);self.assertEqual(self.status(lid)['state'],'RETAINED_ACTIVE')

    def test_pin_acquired_after_mark_still_blocks_execution(self):
        lid,_=self.ready();oid=sorted(self.bundle.objects)[0];req=self.repair_request(lid,[oid]);self.keeper.mark_repair(lid,self.cap,req)
        with self.keeper.reader(lid,oid,self.cap,self.call('get',lid,oid)):
            self.err('PINNED',lambda:self.repair(lid,req))
        self.repair(lid,req)
    def test_one_pending_job_per_lease(self):
        lid,_=self.ready();self.keeper.mark_repair(lid,self.cap,self.repair_request(lid));self.err('REPAIR_PENDING',lambda:self.repair(lid,self.repair_request(lid)))
    def test_cancel_healthy_job_then_gc(self):
        lid,_=self.ready();req=self.repair_request(lid);job=self.keeper.mark_repair(lid,self.cap,req)['job_id'];self.release(lid)
        self.keeper.cancel_repair(lid,self.cap,self.cancel_request(lid,job));self.gc(lid,self.gc_request(lid));self.assertEqual(self.status(lid)['state'],'RECLAIMED')
    def test_new_cap_can_restart_after_old_job_cancelled(self):
        lid,_=self.ready();oid=self.damage(lid);req=self.repair_request(lid,[oid]);job=self.keeper.mark_repair(lid,self.cap,req)['job_id']
        self.authority=replace(self.authority,head=h('next-authority'),sequence=2);self.keeper.update_authority(self.authority)
        self.cap=self.k.issue_capability(self.p,self.s.owner,self.authority,self.kp,self.cp,self.rpin.index_id,tuple(self.k.METHODS),60,h('new-capability'))
        self.keeper.cancel_repair(lid,self.cap,self.cancel_request(lid,job));self.repair(lid,self.repair_request(lid,[oid]));self.assertEqual(self.status(lid)['state'],'RETAINED_ACTIVE')
    def test_repeated_damage_and_repair_keeps_retention_constant(self):
        import random
        lid,receipt=self.ready();rng=random.Random(1400);original=dict(self.keeper._lease(lid));oids=sorted(self.bundle.objects)
        for n in range(12):
            chosen=rng.sample(oids,2)
            for oid in chosen:self.damage(lid,'missing' if n%2 else 'corrupt',oid)
            self.repair(lid,self.repair_request(lid,sorted(chosen)));self.assertEqual(dict(self.keeper._lease(lid)),original)
            self.reopen();self.assertEqual(self.status(lid)['state'],'RETAINED_ACTIVE')
        self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total)
