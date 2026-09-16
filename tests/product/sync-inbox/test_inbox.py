import copy,json,os,threading
from pathlib import Path
from inbox_support import InboxTest,h
from par_wire.codec import encode,decode

class ReceiveTests(InboxTest):
    def test_basic_receipt_never_claims_shared_commit_or_apply(self):
        self.create();a=self.change();r=self.receive(a)
        self.assertEqual(r['state'],'PENDING_BYTES');self.assertTrue(r['inboxStored'])
        self.assertFalse(r['applied']);self.assertFalse(r['localCommitted']);self.assertFalse(r['innerValidated'])
        self.assertEqual(self.box.inspect(self.eid(a[0]))['state'],'READY_FOR_CORE')
    def test_out_of_order_waits_then_becomes_ready(self):
        self.create();a=self.change();b=self.change('b',parents=[self.cid(a[0])],previous=self.eid(a[0]),seq=2)
        self.receive(b);s=self.box.inspect(self.eid(b[0]));self.assertEqual(s['state'],'WAITING_DEPENDENCIES');self.assertEqual(s['missing'],[self.cid(a[0]).hex()])
        self.receive(a);self.assertEqual(self.box.inspect(self.eid(b[0]))['state'],'READY_FOR_CORE')
    def test_exact_duplicate_does_not_consume_extra_capacity(self):
        self.create();a=self.change();one=self.receive(a);pin=self.box.pin();two=self.receive(a)
        self.assertEqual(one,two);self.assertEqual(pin,self.box.pin());self.assertEqual(self.box.usage()['records'],1)
    def test_invalid_signature_never_consumes_capacity(self):
        self.create();raw,cert=self.change();o=decode(raw);o[3]=b'\x00'*64
        self.bad('AUTH_REJECTED',lambda:self.box.receive(encode(o),cert));self.assertEqual(self.box.usage()['records'],0)
    def test_wrong_document_never_stored(self):
        self.create();self.bad('SCOPE_MISMATCH',lambda:self.receive(self.change(header_patch={3:h('else')})));self.assertEqual(self.box.usage()['records'],0)
    def test_reader_cannot_write(self):
        self.create();self.bad('AUTH_REJECTED',lambda:self.receive(self.change(index=1)));self.assertEqual(self.box.usage()['records'],0)
    def test_inner_payload_not_written_as_plaintext(self):
        self.create();a=self.change();self.receive(a)
        for p in self.path.rglob('*'):
            if p.is_file():self.assertNotIn(b'OPAQUE-CONTRACT-NOT-AUTOMERGE',p.read_bytes())
    def test_missing_core_not_faked(self):
        self.create();a=self.change();self.receive(a)
        r=self.box.validate(self.eid(a[0]),None);self.assertEqual(r['state'],'CORE_BLOCKED');self.assertFalse(r['innerValidated']);self.assertFalse(r['applied'])
    def test_unknown_id_is_not_global_not_found(self):
        self.create();self.assertEqual(self.box.inspect(h('unknown'))['state'],'NOT_OBSERVED')
    def test_refuses_mutable_input(self):
        self.create();a,c=self.change();self.bad('INVALID_INPUT',lambda:self.box.receive(bytearray(a),c))
    def test_scope_boolean_epoch_refused(self):
        scope=dict(self.scope,epoch=True);self.bad('INVALID_INPUT',lambda:self.cls.create(self.path,self.db,**scope))
    def test_input_mutation_from_hook_cannot_change_record(self):
        self.create();a=self.change();self.receive(a);x=self.box.inspect(self.eid(a[0]));x['missing'].append('bad');self.assertEqual(self.box.inspect(self.eid(a[0]))['missing'],[])

class DependencyTests(InboxTest):
    def chain(self):
        a=self.change('a');b=self.change('b',parents=[self.cid(a[0])],previous=self.eid(a[0]),seq=2);c=self.change('c',parents=[self.cid(b[0])],previous=self.eid(b[0]),seq=3);return a,b,c
    def test_all_delivery_orders_have_same_readiness(self):
        import itertools
        for order in itertools.permutations(range(3)):
            self.path=self.root.parent/('box'+''.join(map(str,order)));self.create();items=self.chain()
            for i in order:self.receive(items[i])
            self.assertEqual([self.box.inspect(self.eid(x[0]))['state'] for x in items],['READY_FOR_CORE']*3);self.close_box()
    def test_need_set_is_exact_and_bounded(self):
        self.create();a,b,c=self.chain();self.receive(c);self.assertEqual(self.box.needed(limit=1),[self.cid(b[0]).hex()]);self.receive(b);self.assertEqual(self.box.needed(),[self.cid(a[0]).hex()])
    def test_cycle_never_becomes_ready(self):
        self.create();a=self.change('a',parents=[h('inner:b')]);b=self.change('b',parents=[h('inner:a')],header_patch={6:h('other-gen')[:16]});self.receive(a);self.receive(b)
        self.assertEqual(self.box.inspect(self.eid(a[0]))['state'],'INVALID_DEPENDENCY_GRAPH')
    def test_author_fork_quarantines_scope(self):
        self.create();a=self.change('a');b=self.change('b');self.receive(a);self.receive(b)
        for x in [a,b]:self.assertEqual(self.box.inspect(self.eid(x[0]))['state'],'QUARANTINED')
    def test_equivocation_evidence_reserved_when_full(self):
        self.create(max_records=1);a=self.change('a');b=self.change('b');self.receive(a);self.receive(b)
        self.assertEqual(self.box.usage()['records'],2);self.assertEqual(self.box.inspect(self.eid(a[0]))['state'],'QUARANTINED')
    def test_third_fork_does_not_unbound_evidence(self):
        self.create(max_records=1);self.receive(self.change('a'));self.receive(self.change('b'));self.bad('RESOURCE_BLOCKED',lambda:self.receive(self.change('c')));self.assertEqual(self.box.usage()['records'],2)
    def test_resource_blocked_is_retryable_not_invalid(self):
        self.create(max_records=1);self.receive(self.change());self.bad('RESOURCE_BLOCKED',lambda:self.receive(self.change('b',header_patch={6:h('other')[:16]})));self.assertEqual(self.box.usage()['records'],1)
    def test_previous_link_must_be_in_causal_closure(self):
        self.create();a=self.change();b=self.change('b',seq=2,previous=self.eid(a[0]));self.receive(a);self.receive(b);self.assertEqual(self.box.inspect(self.eid(b[0]))['state'],'INVALID_DEPENDENCY_GRAPH')
    def test_unknown_previous_is_requested_as_envelope_id(self):
        self.create();b=self.change('b',seq=2,previous=h('prev'),parents=[h('parent')]);self.receive(b);s=self.box.inspect(self.eid(b[0]));self.assertEqual(s['state'],'WAITING_DEPENDENCIES');self.assertEqual(s['missingPrevious'],[h('prev').hex()])
    def test_dependency_from_actual_local_store(self):
        self.create();op,head,body,cache=self.request();r=self.writer().write(op,head,body,cache)
        b=self.change('b',seq=2,previous=r.envelope_id,parents=[head[12]]);self.receive(b);self.assertEqual(self.box.inspect(self.eid(b[0]))['state'],'READY_FOR_CORE')
    def test_core_double_requires_explicit_option(self):
        from test_writer import ContractPort
        self.create();a=self.change();self.receive(a);self.assertEqual(self.box.validate(self.eid(a[0]),ContractPort())['state'],'CORE_BLOCKED')
    def test_contract_double_never_promotes_semantics(self):
        from test_writer import ContractPort
        self.create();a=self.change();self.receive(a);r=self.box.validate(self.eid(a[0]),ContractPort(),allow_contract_double=True)
        self.assertEqual(r['state'],'CONTRACT_CHECKED');self.assertFalse(r['innerValidated']);self.assertFalse(r['applied'])
    def test_dependency_wait_does_not_call_core(self):
        from test_writer import ContractPort
        self.create();a,b,c=self.chain();self.receive(c);p=ContractPort();r=self.box.validate(self.eid(c[0]),p,allow_contract_double=True);self.assertEqual(r['state'],'WAITING_DEPENDENCIES');self.assertEqual(p.calls,0)
    def test_core_change_during_validation_rejected(self):
        from test_writer import ContractPort
        self.create();a=self.change();self.receive(a);p=ContractPort();p.hook=lambda:setattr(p,'identity',dict(p.identity,digest='b'*64))
        r=self.box.validate(self.eid(a[0]),p,allow_contract_double=True);self.assertEqual(r['state'],'CORE_BLOCKED');self.assertEqual(r['reason'],'CORE_IDENTITY_CHANGED')
    def test_wrong_report_stays_unapplied(self):
        from test_writer import ContractPort
        class Bad(ContractPort):
            def validate(s,r):
                x=super().validate(r);x['changes'][0]['sequence']='90';return x
        self.create();a=self.change();self.receive(a);r=self.box.validate(self.eid(a[0]),Bad(),allow_contract_double=True);self.assertEqual(r['state'],'CORE_REJECTED');self.assertFalse(r['applied'])

class PersistenceTests(InboxTest):
    def test_restart_rederives_waiting_state(self):
        self.create();a=self.change('b',parents=[h('absent')]);self.receive(a);p=self.box.pin();self.reopen_box(expected_pin=p);self.assertEqual(self.box.inspect(self.eid(a[0]))['state'],'WAITING_DEPENDENCIES')
    def test_pin_detects_missing_record(self):
        self.create();a=self.change();self.receive(a);pin=self.box.pin();self.close_box();(self.path/'records'/(self.eid(a[0]).hex()+'.cbor')).unlink();self.bad('PIN_MISMATCH',lambda:self.reopen_box(expected_pin=pin))
    def test_record_tamper_detected_on_read(self):
        self.create();a=self.change();self.receive(a);p=self.path/'records'/(self.eid(a[0]).hex()+'.cbor');p.write_bytes(p.read_bytes()[:-1]+b'\0');self.bad('INBOX_CORRUPT',lambda:self.box.inspect(self.eid(a[0])))
    def test_wrong_scope_open_refused(self):
        self.create();self.close_box();s=dict(self.scope,document_id=h('other'));self.bad('SCOPE_MISMATCH',lambda:self.cls.open(self.path,self.db,**s))
    def test_unknown_disk_record_refused(self):
        self.create();p=self.path/'records'/'unexpected';p.write_bytes(b'x');p.chmod(0o600);self.bad('INBOX_CORRUPT',self.box.pin)
    def test_single_writer_lock(self):
        self.create();self.bad('INBOX_BUSY',lambda:self.cls.open(self.path,self.db,**self.scope))
    def test_wrong_thread_does_not_close_owner(self):
        self.create();errors=[]
        def f():
            try:self.box.close()
            except Exception as e:errors.append(e.code)
        t=threading.Thread(target=f);t.start();t.join();self.assertEqual(errors,['WRONG_OWNER']);self.assertEqual(self.box.usage()['records'],0)
    def test_same_epoch_authority_update_rechecked(self):
        self.create();a=self.change();self.receive(a);self.same_epoch();self.assertEqual(self.box.inspect(self.eid(a[0]))['state'],'READY_FOR_CORE')
    def test_epoch_update_requires_rebase_without_deleting(self):
        self.create();a=self.change();self.receive(a);self.next_epoch();r=self.box.inspect(self.eid(a[0]));self.assertEqual(r['state'],'REBASE_REQUIRED');self.assertEqual(self.box.usage()['records'],1)
    def test_not_activated_owner_never_decrypts(self):
        self.create();a=self.change();self.receive(a);self.close_box();self.reopen();self.reopen_box();r=self.box.inspect(self.eid(a[0]));self.assertEqual(r['state'],'WAITING_AUTHORITY')
    def test_inspection_does_not_write_source_store(self):
        self.create();a=self.change();self.receive(a);before=self.db._storage.connection.total_changes;self.box.inspect(self.eid(a[0]));self.box.needed();self.assertEqual(before,self.db._storage.connection.total_changes)
    def test_usage_is_derived_not_trusted_counter(self):
        self.create();a=self.change();self.receive(a);u=self.box.usage();self.reopen_box();self.assertEqual(u,self.box.usage());self.assertFalse(u['physicalQuotaGuaranteed'])
    def test_no_plaintext_or_semantic_status_in_persisted_record(self):
        self.create();a=self.change();self.receive(a);record=decode((self.path/'records'/(self.eid(a[0]).hex()+'.cbor')).read_bytes());self.assertEqual(set(record),{0,1,2});self.assertEqual(record[1],a[0])
    def test_permissions_are_private(self):
        import stat
        self.create();self.receive(self.change())
        for p in [self.path,self.path/'records',self.path/'staging']:self.assertEqual(stat.S_IMODE(p.stat().st_mode),0o700)
        for p in (self.path/'records').iterdir():self.assertEqual(stat.S_IMODE(p.stat().st_mode),0o600)

class HardeningTests(InboxTest):
    def test_reserved_evidence_slot_covers_conflict_with_local_store(self):
        self.create(max_records=1);self.receive(self.change('unrelated',header_patch={6:h('other-gen')[:16]}))
        op,hdr,body,cache=self.request();self.writer().write(op,hdr,body,cache)
        a=self.change('stored-fork');self.receive(a);self.assertEqual(self.box.usage()['records'],2);self.assertEqual(self.box.inspect(self.eid(a[0]))['state'],'QUARANTINED')
    def test_local_store_actor_fork_quarantines_received_scope(self):
        self.create();op,hdr,body,cache=self.request();self.writer().write(op,hdr,body,cache)
        a=self.change('conflicting');self.receive(a);self.assertEqual(self.box.inspect(self.eid(a[0]))['state'],'QUARANTINED')
    def test_disk_change_during_core_validation_invalidates_result(self):
        from test_writer import ContractPort
        self.create();a=self.change();self.receive(a);p=ContractPort()
        def mutate():
            dest=self.path/'records'/(self.eid(a[0]).hex()+'.cbor');dest.write_bytes(dest.read_bytes()[:-1]+b'\0')
        p.hook=mutate;self.bad('INBOX_CORRUPT',lambda:self.box.validate(self.eid(a[0]),p,allow_contract_double=True))
    def test_core_exception_is_not_document_invalidity(self):
        from test_writer import ContractPort
        class Broken(ContractPort):
            def validate(s,r):raise OSError('unavailable')
        self.create();a=self.change();self.receive(a);r=self.box.validate(self.eid(a[0]),Broken(),allow_contract_double=True)
        self.assertEqual(r['state'],'CORE_BLOCKED');self.assertEqual(r['reason'],'CORE_FAILURE')
    def test_owner_change_at_last_callback_returns_unknown(self):
        self.create();a=self.change()
        self.box.observer=lambda phase:self.same_epoch() if phase=='inbox.before_receipt' else None
        self.bad('INBOX_OUTCOME_UNKNOWN',lambda:self.receive(a))
        self.reopen_box();self.assertEqual(self.box.inspect(self.eid(a[0]))['state'],'READY_FOR_CORE')
    def test_prepublication_authority_change_does_not_publish(self):
        self.create();a=self.change();self.box.observer=lambda phase:self.same_epoch() if phase=='inbox.before_publish' else None
        self.bad('OWNER_STATE_CHANGED',lambda:self.receive(a));self.assertEqual(self.box.usage()['records'],0)
    def test_no_nonce_created_by_receive_or_inspect(self):
        self.create();a=self.change();before=self.count('issued_nonces');self.receive(a);self.box.inspect(self.eid(a[0]));self.assertEqual(self.count('issued_nonces'),before)
    def test_id_length_checked(self):
        self.create();self.bad('INVALID_INPUT',lambda:self.box.inspect(b'x'))
    def test_invalid_limit_boolean(self):
        self.create();self.bad('INVALID_INPUT',lambda:self.box.needed(limit=True))
    def test_future_epoch_never_retained(self):
        self.create();self.bad('SCOPE_MISMATCH',lambda:self.receive(self.change(header_patch={2:2})));self.assertEqual(self.box.usage()['records'],0)
    def test_symlink_record_rejected(self):
        self.create();a=self.change();self.receive(a);p=self.path/'records'/(self.eid(a[0]).hex()+'.cbor');dest=self.root.parent/'outside';p.rename(dest);p.symlink_to(dest)
        with self.assertRaises(Exception):self.box.inspect(self.eid(a[0]))
    def test_hardlink_record_rejected(self):
        self.create();a=self.change();self.receive(a);p=self.path/'records'/(self.eid(a[0]).hex()+'.cbor');os.link(p,self.root.parent/'outside');self.bad('UNSAFE_PATH',self.box.pin)
    def test_wide_directory_permissions_rejected(self):
        self.create();self.path.chmod(0o755);self.bad('UNSAFE_PATH',self.box.pin)
    def test_invalid_file_before_capacity_check_does_not_poison_scope(self):
        self.create(max_records=1);a=self.change();self.receive(a);raw,cert=self.change('b');o=decode(raw);o[3]=b'\x00'*64
        self.bad('AUTH_REJECTED',lambda:self.box.receive(encode(o),cert));self.assertEqual(self.box.inspect(self.eid(a[0]))['state'],'READY_FOR_CORE')
    def test_pin_allows_new_legitimate_records_but_keeps_known_bytes(self):
        self.create();a=self.change();self.receive(a);pin=self.box.pin();b=self.change('b',parents=[self.cid(a[0])],previous=self.eid(a[0]),seq=2);self.receive(b);self.reopen_box(expected_pin=pin);self.assertEqual(self.box.usage()['records'],2)
    def test_byte_capacity_rejection_preserves_existing_record(self):
        a=self.change();b=self.change('b',parents=[self.cid(a[0])],previous=self.eid(a[0]),seq=2)
        self.create(max_bytes=len(encode({0:1,1:a[0],2:a[1]})));self.receive(a);self.bad('RESOURCE_BLOCKED',lambda:self.receive(b));self.assertEqual(self.box.usage()['records'],1)
    def test_report_does_not_expose_core_preview_text(self):
        from test_writer import ContractPort
        self.create();a=self.change();self.receive(a);r=self.box.validate(self.eid(a[0]),ContractPort(),allow_contract_double=True)
        self.assertNotIn('synthetic, not CRDT',json.dumps(r));self.assertNotIn('note',r)
