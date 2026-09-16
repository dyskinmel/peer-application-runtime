from keeper_support import KeeperTest,h,decode,replace
import os,sqlite3
class KeeperStore(KeeperTest):
    def test_reserve_exact_payload_budget(self):
        self.open_keeper();lid=self.reserve();self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total);self.assertEqual(self.status(lid)['state'],'AWAITING_OBJECTS')
    def test_duplicate_reserve_no_double_charge(self):
        self.open_keeper();a=self.reserve(h('reserve'));b=self.reserve(h('reserve'));self.assertEqual(a,b);self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total)
    def test_same_operation_different_duration_rejected(self):
        self.open_keeper();self.reserve(h('reserve'));self.err('OPERATION_CONFLICT',lambda:self.reserve(h('reserve'),seconds=40))
    def test_quota_checked_before_acceptance(self):
        self.open_keeper(quota_bytes=self.total-1);self.err('CAPACITY',self.reserve);self.assertEqual(self.keeper.diagnostics()['leases'],0)
    def test_second_lease_counts_independently(self):
        self.open_keeper(quota_bytes=self.total);self.reserve();self.err('CAPACITY',self.reserve)
    def test_lease_count_limit(self):
        self.open_keeper(max_leases=1);self.reserve();self.err('LEASE_LIMIT',self.reserve)
    def test_put_duplicate_is_idempotent(self):
        self.open_keeper();lid=self.reserve();oid=next(iter(self.bundle.objects));self.put(lid,oid);self.put(lid,oid);self.assertEqual(self.status(lid)['received'],1)
    def test_unknown_object_rejected(self):
        self.open_keeper();lid=self.reserve();self.err('OBJECT_SCOPE',lambda:self.put(lid,h('unknown'),b'data'))
    def test_corrupt_object_rejected(self):
        self.open_keeper();lid=self.reserve();oid=next(iter(self.bundle.objects));self.err('OBJECT_HASH',lambda:self.put(lid,oid,self.bundle.objects[oid]+b'x'))
    def test_partial_inventory_cannot_seal(self):
        self.open_keeper();lid=self.reserve();self.put(lid,next(iter(self.bundle.objects)));self.err('INCOMPLETE',lambda:self.seal(lid))
    def test_complete_but_unsealed_not_receipt(self):
        self.open_keeper();lid=self.reserve();self.fill(lid);self.err('NOT_SEALED',lambda:self.keeper.receipt(lid,self.cap,self.call('receipt',lid)))
    def test_seal_exact_inventory_signed(self):
        lid,rc=self.ready();nonce=decode(decode(self.sealcall)[0])[7]
        b=self.k.verify_receipt(self.p,rc,self.kp,self.bundle.index,self.rpin,lid,self.authority,nonce,self.k.capability_id(self.cap))
        self.assertEqual(b[13],self.total);self.assertFalse(b[23]);self.assertEqual(b[11],len(self.bundle.objects));self.assertEqual(self.status(lid)['state'],'RETAINED_ACTIVE')
    def test_duplicate_seal_same_receipt(self):
        self.open_keeper();lid=self.reserve();self.fill(lid);a=self.seal(lid,h('seal'));self.clock.ns+=1_000_000_000;b=self.seal(lid,h('seal'));self.assertEqual(a,b)
    def test_sealed_duplicate_with_new_operation_rejected(self):
        lid,rc=self.ready();self.err('ALREADY_SEALED',lambda:self.seal(lid))
    def test_reopen_recovers_reservation_and_receipt(self):
        lid,rc=self.ready();self.keeper.close();self.open_keeper();self.assertEqual(self.keeper.receipt(lid,self.cap,self.call('receipt',lid)),rc);self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total)
    def test_missing_committed_object_invalidates_fresh_receipt(self):
        lid,rc=self.ready();oid=next(iter(self.bundle.objects));self.keeper.object_path(lid,oid).unlink()
        self.assertEqual(self.status(lid)['state'],'DEGRADED');self.err('INCOMPLETE',lambda:self.keeper.receipt(lid,self.cap,self.call('receipt',lid)))
    def test_missing_object_can_be_repaired_with_exact_bytes(self):
        lid,rc=self.ready();oid=next(iter(self.bundle.objects));self.keeper.object_path(lid,oid).unlink();self.put(lid,oid);self.assertEqual(self.status(lid)['state'],'RETAINED_ACTIVE')
    def test_corruption_not_silently_overwritten(self):
        lid,rc=self.ready();oid=next(iter(self.bundle.objects));self.keeper.object_path(lid,oid).write_bytes(b'bad');self.err('OBJECT_HASH',lambda:self.put(lid,oid))
    def test_get_exact_object_under_capability(self):
        lid,rc=self.ready();oid=next(iter(self.bundle.objects));self.assertEqual(self.get(lid,oid),self.bundle.objects[oid])
    def test_wrong_request_proof_denied(self):
        lid,rc=self.ready();oid=next(iter(self.bundle.objects));raw=decode(self.call('get',lid,oid));raw[1]=bytes(64)
        from par_wire.codec import encode
        self.err('REQUEST_AUTH',lambda:self.keeper.fetch(lid,oid,self.cap,encode(raw)))
    def test_get_never_fetches_unlisted_hash(self):
        lid,rc=self.ready();self.err('OBJECT_SCOPE',lambda:self.get(lid,h('not-in-index')))
    def test_readonly_capability_cannot_put(self):
        self.open_keeper();lid=self.reserve();g=self.k.issue_capability(self.p,self.s.owner,self.authority,self.kp,self.cp,self.rpin.index_id,('get',),60,h('read'))
        self.err('METHOD_DENIED',lambda:self.put(lid,next(iter(self.bundle.objects)),cap=g))
    def test_scope_index_cannot_be_swapped(self):
        self.open_keeper();g=self.k.issue_capability(self.p,self.s.owner,self.authority,self.kp,self.cp,h('other-index'),tuple(self.k.METHODS),60,h('other'))
        self.err('INDEX_SCOPE',lambda:self.reserve(cap=g));self.assertEqual(self.keeper.diagnostics()['leases'],0)
    def test_same_keeper_root_second_writer_rejected(self):
        self.open_keeper();self.err('WRITER_BUSY',lambda:self.k.Keeper(self.path,self.p,self.ks,self.authority,quota_bytes=self.total*3,clock=self.clock,allow_unpatched_sqlite=True))
    def test_different_keeper_key_cannot_open(self):
        self.open_keeper();self.keeper.close();self.err('KEEPER_IDENTITY',lambda:self.k.Keeper(self.path,self.p,h('wrong'),self.authority,quota_bytes=self.total*3,clock=self.clock,allow_unpatched_sqlite=True))
    def test_ddl_tampering_rejected_on_open(self):
        self.open_keeper();self.keeper.connection.execute('CREATE TABLE unexpected(x)');self.keeper.close();self.err('SCHEMA_MISMATCH',self.open_keeper)
    def test_receipt_tampering_rejected_on_open(self):
        lid,rc=self.ready();self.keeper.connection.execute('UPDATE leases SET receipt=? WHERE id=?',(b'bad',lid));self.keeper.close();self.err('CORRUPT_STORE',self.open_keeper)
    def test_legacy_sqlite_is_opt_in_only(self):
        from par_store.model import wal_reset_fixed
        if wal_reset_fixed(sqlite3.sqlite_version):
            k=self.k.Keeper(self.path,self.p,self.ks,self.authority,quota_bytes=self.total*3);k.close()
        else:self.err('SQLITE_PATCH_REQUIRED',lambda:self.k.Keeper(self.path,self.p,self.ks,self.authority,quota_bytes=self.total*3))
    def test_symlink_root_denied(self):
        target=self.path.parent/'elsewhere';target.mkdir();self.path.symlink_to(target,target_is_directory=True);self.err('UNSAFE_PATH',self.open_keeper)
    def test_quota_configuration_mismatch_rejected(self):
        self.open_keeper();self.keeper.close();self.err('CONFIGURATION_MISMATCH',lambda:self.open_keeper(quota_bytes=self.total*4))
    def test_deleted_renewal_record_rejected_on_reopen(self):
        lid,rc=self.ready();self.renew(lid)
        self.keeper.connection.execute("DELETE FROM operations WHERE action='renew'");self.keeper.close();self.err('CORRUPT_STORE',self.open_keeper)
    def test_mutated_cached_response_rejected_without_reopening(self):
        self.open_keeper();lid=self.reserve();self.fill(lid);self.seal(lid,h('seal'))
        self.keeper.connection.execute("UPDATE operations SET response=? WHERE action='seal'",(b'not-a-receipt',))
        self.err('CORRUPT_STORE',lambda:self.seal(lid,h('seal')))
    def test_same_nonce_across_mutation_actions_denied(self):
        self.open_keeper();lid=self.reserve(h('same'));self.fill(lid);self.err('OPERATION_CONFLICT',lambda:self.seal(lid,h('same')))
    def test_get_does_not_grow_mutation_ledger(self):
        lid,rc=self.ready();n=self.keeper.diagnostics()['operations'];oid=next(iter(self.bundle.objects))
        for _ in range(20):self.get(lid,oid)
        self.assertEqual(self.keeper.diagnostics()['operations'],n)
    def test_receipt_cannot_be_bound_to_wrong_completion_nonce(self):
        lid,rc=self.ready();self.err('RECEIPT_SCOPE',lambda:self.k.verify_receipt(self.p,rc,self.kp,self.bundle.index,self.rpin,lid,self.authority,h('wrong'),self.k.capability_id(self.cap)))
    def test_receipt_cannot_be_bound_to_wrong_grant(self):
        lid,rc=self.ready();nonce=decode(decode(self.sealcall)[0])[7]
        self.err('RECEIPT_SCOPE',lambda:self.k.verify_receipt(self.p,rc,self.kp,self.bundle.index,self.rpin,lid,self.authority,nonce,h('wrong-grant')))
    def test_keeper_disk_never_contains_content_or_private_keys(self):
        lid,rc=self.ready();self.keeper.connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        forbidden=[self.s.secret,self.reader['secret'],self.ks,self.cs,self.data[:128]]
        for file in self.path.rglob('*'):
            if file.is_file():
                raw=file.read_bytes()
                for value in forbidden:self.assertNotIn(value,raw)
