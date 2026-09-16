from recovery_support import *
import unittest
class Pipeline(RecoveryTest):
    def test_file_roundtrip_without_source_store(self):
        b=self.collect();self.close();view=self.verify(b);view.export_file(self.receipt.envelope_id,self.output)
        self.assertEqual(self.output.read_bytes(),self.data)
    def test_payload_is_opaque_not_applied(self):
        v=self.verify(self.collect());self.assertEqual(v.read_change(self.receipt.envelope_id),self.request()[2]);self.assertFalse(v.status()['inner_validated'])
    def test_seed_is_available_but_not_crdt(self):
        v=self.verify(self.collect());self.assertEqual(v.read_seed(h('object-seed')),self.b['plain']);self.assertEqual(v.status()['seed_semantics'],'OPAQUE_BYTES')
    def test_readonly_view_has_no_writer(self):
        v=self.verify(self.collect());self.assertFalse(hasattr(v,'commit'));self.reject_rc('READ_ONLY',lambda:v._enter(True))
    def test_file_name_not_plaintext_in_transfer(self):
        b=self.collect()
        for raw in b.objects.values():self.assertNotIn('資料.txt'.encode(),raw)
    def test_private_writer_data_not_included(self):
        b=self.collect()
        for raw in b.objects.values():
            for secret in (self.s.secret,self.reader['secret'],self.s.devices[0]['seed'],h('local-secret')):self.assertNotIn(secret,raw)
    def test_all_public_object_refs_consumed(self):
        b=self.collect();v=self.rc.verify_public(b,self.pin(b),self.p);self.assertIsNone(v.state.active_epoch)
    def test_empty_file_supported(self):
        req=list(self.request(op=2));req[1]=dict(req[1]);req[1][3]=h('empty-doc');req[1][6]=h('empty-actor')[:16]
        self.source.write_bytes(b'');r=self.write(request=tuple(req));b=self.collect(roots=(r.envelope_id,));pin=replace(self.pin(b),roots=(r.envelope_id,))
        v=self.verify(b,pin);self.assertEqual(v.file_info(r.envelope_id).size,0)
    def test_previous_commit_collected(self):
        req=list(self.request(op=2,sequence=2,previous=self.receipt.envelope_id));req[1]=dict(req[1]);req[1][12]=h('second-change')
        r=self.write(request=tuple(req));b=self.collect(roots=(r.envelope_id,));pin=replace(self.pin(b),roots=(r.envelope_id,))
        self.assertEqual(self.verify(b,pin).status()['envelopes'],2)
    def test_dependency_collected(self):
        req=list(self.request(op=2,index=0));req[1]=dict(req[1]);req[1][6]=h('other-generation')[:16];req[1][10]=[h('inner-hash')];req[1][12]=h('second-change')
        # An actor generation rollover is not allowed by this Store; use a second document is also invalid.
        # Test explicit dependency together with the valid predecessor.
        req[1][6]=self.request()[1][6];req[1][7]=2;req[1][8]=self.receipt.envelope_id
        r=self.write(request=tuple(req));b=self.collect(roots=(r.envelope_id,));pin=replace(self.pin(b),roots=(r.envelope_id,))
        self.assertEqual(self.verify(b,pin).status()['envelopes'],2)
    def test_missing_dependency_refused_by_collector(self):
        req=list(self.request(op=2,sequence=2,previous=self.receipt.envelope_id));req[1]=dict(req[1]);req[1][10]=[h('absent-change')];req[1][12]=h('second-change')
        r=self.write(request=tuple(req));self.reject_rc('DEPENDENCY_MISSING',lambda:self.collect(roots=(r.envelope_id,)))
    def test_old_epoch_not_silently_recovered(self):
        b2=self.next_epoch();self.activate(b2)
        self.reject_rc('EPOCH_UNSUPPORTED',lambda:self.collect())
    def test_pending_membership_refused(self):
        self.db.observe(self.s.space,self.s.raw(self.s.next(self.b['raw'])))
        self.reject_rc(None,lambda:self.collect())
    def test_failed_control_persistence_refuses_export(self):
        def fail(event):
            if event=='auth.before_commit':raise RuntimeError('fault')
        self.db.observer=fail
        try:self.same_epoch()
        except Exception:pass
        finally:self.db.observer=None
        self.assertEqual(self.db.status(self.s.space)['state'],'AUTH_PERSISTENCE_UNCERTAIN')
        self.reject_rc('AUTH_PERSISTENCE_UNCERTAIN',lambda:self.collect())
    def test_signed_but_wrong_attachment_order(self):
        def mut(raw):
            o=decode(raw);v=decode(o[0]);v[6].reverse();body=encode(v)
            return encode({0:body,1:self.p.sign(self.s.devices[0]['seed'],domain('blob-store-local/attachment-sign',[body]))})
        b=self.patch_object(self.collect(),'attachment',mut);self.reject_rc('ATTACHMENT_INVALID',lambda:self.verify(b))
    def test_unreferenced_valid_object_rejected(self):
        from par_recovery.contract import sign_index
        b=self.collect();v=decode(decode(b.index,max_bytes=524288)[0],max_bytes=524288)
        raw=b'unreferenced';oid=self.rc.object_id('certificate',raw);v[15].append([oid,'certificate',len(raw)]);v[15].sort()
        b=self.rc.Bundle(sign_index(self.p,self.s.devices[0]['seed'],v),dict(b.objects)|{oid:raw})
        self.reject_rc('OBJECT_UNUSED',lambda:self.verify(b))
    def test_replay_corruption_with_resigned_index(self):
        b=self.patch_object(self.collect(),'replay',lambda raw:raw[:-1]+bytes([raw[-1]^1]));self.reject_rc('AUTHORITY_INVALID',lambda:self.verify(b))
    def test_invalid_grant_package_root(self):
        def mut(raw):
            v=decode(raw);v[2]=[h('bad-package')];return encode(v)
        b=self.patch_object(self.collect(),'grant',mut);self.reject_rc('GRANT_INVALID',lambda:self.verify(b))
    def test_missing_seed_declared_by_grant(self):
        def mut(raw):v=decode(raw);v[4]=[];return encode(v)
        b=self.patch_object(self.collect(),'grant',mut);self.reject_rc('GRANT_INVALID',lambda:self.verify(b))
    def test_duplicate_seed_declared(self):
        def mut(raw):v=decode(raw);v[4].append(v[4][0]);return encode(v)
        b=self.patch_object(self.collect(),'grant',mut);self.reject_rc('GRANT_INVALID',lambda:self.verify(b))
    def test_resigned_index_does_not_enable_foreign_recipient_package(self):
        wrong=self.s.devices[0];g=replace(self.grant,package=self.b['packages'][wrong['id']])
        self.reject_rc('GRANT_INVALID',lambda:self.collect(grant=g))
    def test_signed_attachments_are_not_whole_file(self):
        req=list(self.request(op=2,sequence=2,previous=self.receipt.envelope_id));req[1]=dict(req[1]);req[1][12]=h('other')
        r=self.writer().write(*req,attachments=(self.attachment(),))
        b=self.collect(roots=(r.envelope_id,));pin=replace(self.pin(b),roots=(r.envelope_id,))
        self.reject_rc('FILE_INVALID',lambda:self.verify(b,pin))
    def test_nonblob_envelope_supported(self):
        req=list(self.request(op=2,sequence=2,previous=self.receipt.envelope_id));req[1]=dict(req[1]);req[1][12]=h('other')
        r=self.legacy_writer().write(*req);b=self.collect(roots=(r.envelope_id,));pin=replace(self.pin(b),roots=(r.envelope_id,))
        self.assertEqual(self.verify(b,pin).status()['envelopes'],2)
    def test_unknown_payload_read_refused(self):
        v=self.verify(self.collect());self.reject_rc('OBJECT_REFERENCE',lambda:v.read_change(h('bad')))
    def test_partial_manifest_removed_not_empty(self):
        b=self.collect();v=decode(decode(b.index,max_bytes=524288)[0],max_bytes=524288);oid=v[14][0][3];del b.objects[oid]
        self.reject_rc('OBJECT_SET',lambda:self.verify(b))

    def test_unreachable_envelope_rejected_after_valid_resign(self):
        req=list(self.request(op=2));req[1]=dict(req[1]);req[1][3]=h('independent-doc');req[1][6]=h('independent-actor')[:16]
        r=self.write(request=tuple(req));b=self.collect(roots=tuple(sorted((self.receipt.envelope_id,r.envelope_id))))
        b=self.rewrite(b,lambda v:v.__setitem__(9,[self.receipt.envelope_id]))
        self.reject_rc('UNREACHABLE_ENVELOPE',lambda:self.verify(b))
    def test_source_index_has_byte_budget(self):
        from unittest.mock import patch
        with patch('par_recovery.collector.MAX_BYTES',1):
            self.reject_rc('SOURCE_INDEX_LIMIT',lambda:self.collect())

class Graph(unittest.TestCase):
    def h(self,i,**kw):
        x={0:'org.example.test',1:h('space'),2:1,3:h('doc'),5:h('writer'),6:h('gen')[:16],7:i,8:None,10:[],12:h('hash-'+str(i))}
        return x|kw
    def check(self,code,roots,headers):
        from par_recovery.graph import closure
        from par_recovery import RecoveryError
        with self.assertRaises(RecoveryError) as cm:closure(roots,headers)
        self.assertEqual(cm.exception.code,code)
    def test_graph_order(self):
        from par_recovery.graph import closure
        a,b=h('a'),h('b');one=self.h(1);two=self.h(2);two[8]=a
        self.assertEqual(closure((b,),{a:one,b:two}),(a,b))
    def test_cycle(self):
        a=h('a');v=self.h(1);v[10]=[v[12]];self.check('DEPENDENCY_CYCLE',(a,),{a:v})
    def test_ambiguous_change_hash(self):
        a,b,c=h('a'),h('b'),h('c');x,y,z=self.h(1),self.h(1),self.h(1);z[10]=[x[12]]
        self.check('DEPENDENCY_AMBIGUOUS',(c,),{a:x,b:y,c:z})
    def test_wrong_document(self):
        a,b=h('a'),h('b');x,y=self.h(1),self.h(2);y[8]=a;x[3]=h('else')
        self.check('DEPENDENCY_CONTEXT',(b,),{a:x,b:y})
    def test_wrong_previous_actor(self):
        a,b=h('a'),h('b');x,y=self.h(1),self.h(2);y[8]=a;x[5]=h('else')
        self.check('PREVIOUS_CONTEXT',(b,),{a:x,b:y})
    def test_missing_previous(self):self.check('DEPENDENCY_MISSING',(h('a'),),{h('a'):self.h(2)})
    def test_missing_dependency(self):
        x=self.h(1);x[10]=[h('absent')];self.check('DEPENDENCY_MISSING',(h('a'),),{h('a'):x})
    def test_wrong_previous_sequence(self):
        a,b=h('a'),h('b');x,y=self.h(1),self.h(3);y[8]=a
        self.check('PREVIOUS_CONTEXT',(b,),{a:x,b:y})
    def test_wrong_epoch_dependency(self):
        a,b=h('a'),h('b');x,y=self.h(1),self.h(2);y[8]=a;y[2]=2
        self.check('DEPENDENCY_CONTEXT',(b,),{a:x,b:y})
