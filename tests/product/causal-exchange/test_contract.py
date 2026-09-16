import copy, threading
from exchange_support import ExchangeTest,h
from par_wire.codec import encode,decode
from par_crypto.primitives import domain

class SourceTests(ExchangeTest):
    def test_empty_have(self):
        r=self.source.answer(self.reader['cert'],'have',{0:None,1:0,2:16})
        self.assertEqual(r[2],[]);self.assertIsNone(r[3]);self.assertEqual(r[4],0)
    def test_need_not_observed_is_not_global_absence(self):
        r=self.source.answer(self.reader['cert'],'need',[h('missing')])
        self.assertEqual(r[1],[[h('missing'),None]])
    def test_exact_get_preserves_ciphertext(self):
        a,b=self.fill();r=self.source.answer(self.reader['cert'],'need',[self.cid(a[0])]);d=r[1][0][1]
        out=self.source.answer(self.reader['cert'],'get',{0:r[0],1:d[0],2:d[1]})
        self.assertEqual((out[3],out[4]),a);self.assertEqual(out[5],'ENCRYPTED_PENDING_BYTES')
    def test_catalog_paging(self):
        self.fill();r=self.source.answer(self.reader['cert'],'have',{0:None,1:0,2:1})
        n=self.source.answer(self.reader['cert'],'have',{0:r[0],1:r[3],2:1})
        self.assertEqual(len(r[2])+len(n[2]),2);self.assertIsNone(n[3])
    def test_paging_requires_token(self):
        self.reject_exchange('INVALID_REQUEST',lambda:self.source.answer(self.reader['cert'],'have',{0:None,1:1,2:1}))
    def test_changed_catalog_rejects_old_page(self):
        r=self.source.answer(self.reader['cert'],'have',{0:None,1:0,2:1});self.receive(self.change())
        self.reject_exchange('STALE_VIEW',lambda:self.source.answer(self.reader['cert'],'have',{0:r[0],1:0,2:1}))
    def test_get_id_pair_cannot_be_substituted(self):
        a,b=self.fill();r=self.source.answer(self.reader['cert'],'need',[self.cid(a[0])])
        self.reject_exchange('NOT_OBSERVED',lambda:self.source.answer(self.reader['cert'],'get',{0:r[0],1:self.cid(a[0]),2:self.eid(b[0])}))
    def test_keeper_role_cannot_read(self):
        self.reject_exchange('NOT_AUTHORIZED',lambda:self.source.answer(self.s.devices[2]['cert'],'need',[h('x')]))
    def test_unknown_certificate_cannot_read(self):
        self.reject_exchange('NOT_AUTHORIZED',lambda:self.source.answer(b'bad','need',[h('x')]))
    def test_authority_change_requires_new_context(self):
        self.same_epoch();self.reject_exchange('STALE_AUTHORITY',lambda:self.source.answer(self.reader['cert'],'need',[h('x')]))
    def test_next_epoch_denies_old_scope(self):
        self.next_epoch();self.reject_exchange('STALE_AUTHORITY',lambda:self.source.answer(self.reader['cert'],'need',[h('x')]))
    def test_missing_or_corrupt_bytes_never_served(self):
        a=self.change();self.receive(a);p=self.path/'records'/(self.eid(a[0]).hex()+'.cbor');p.write_bytes(b'bad')
        self.reject_exchange('DATA_INVALID',lambda:self.source.answer(self.reader['cert'],'need',[self.cid(a[0])]))
    def test_equivocation_is_not_resolved_by_provider(self):
        a=self.change();b=self.change('fork');self.receive(a);self.receive(b)
        self.reject_exchange('QUARANTINED',lambda:self.source.answer(self.reader['cert'],'have',{0:None,1:0,2:16}))
    def test_no_plaintext_no_application_write(self):
        a=self.change();self.receive(a);before=self.db._storage.connection.total_changes
        r=self.source.answer(self.reader['cert'],'need',[self.cid(a[0])]);g=self.source.answer(self.reader['cert'],'get',{0:r[0],1:r[1][0][1][0],2:r[1][0][1][1]})
        self.assertNotIn(b'OPAQUE-CONTRACT',encode(g));self.assertEqual(before,self.db._storage.connection.total_changes)
    def test_store_backed_input_is_served(self):
        op,head,payload,cache=self.request();result=self.writer().write(op,head,payload,cache)
        r=self.source.answer(self.reader['cert'],'need',[head[12]])
        self.assertIsNotNone(r[1][0][1]);self.assertEqual(r[1][0][1][0],head[12])
    def test_private_owner_thread_required(self):
        errors=[]
        def wrong():
            try:self.source.answer(self.reader['cert'],'need',[h('x')])
            except Exception as e:errors.append(e)
        t=threading.Thread(target=wrong);t.start();t.join();self.assertEqual(errors[0].code,'WRONG_OWNER')

class ProtocolTests(ExchangeTest):
    def hello(self):return self.x.make_hello(self.p,self.s.devices[0]['seed'],self.source.scope,h('boot'),h('nonce'),5000)
    def test_hello_pin(self):
        b=self.x.check_hello(self.p,self.source.public,self.source.scope,self.hello());self.assertEqual(b[1],self.x.PROFILE)
    def test_wrong_server_key(self):
        self.reject_exchange('HELLO_AUTH',lambda:self.x.check_hello(self.p,self.p.sign_public(h('wrong')),self.source.scope,self.hello()))
    def test_wrong_document_scope(self):
        s=list(self.source.scope);s[2]=h('elsewhere');self.reject_exchange('SCOPE_MISMATCH',lambda:self.x.check_hello(self.p,self.source.public,s,self.hello()))
    def test_request_is_connection_bound(self):
        hello=self.hello();req=self.x.make_request(self.p,self.reader['seed'],hello,self.reader['cert'],'need',[h('x')])
        other=self.x.make_hello(self.p,self.s.devices[0]['seed'],self.source.scope,h('boot'),h('other'),5000)
        self.reject_exchange('REQUEST_BINDING',lambda:self.x.check_request(self.source,other,req))
    def test_wrong_request_signature(self):
        hello=self.hello();req=self.x.make_request(self.p,self.s.devices[0]['seed'],hello,self.reader['cert'],'need',[h('x')])
        self.reject_exchange('REQUEST_AUTH',lambda:self.x.check_request(self.source,hello,req))
    def test_response_connection_binding(self):
        he=self.hello();req=self.x.make_request(self.p,self.reader['seed'],he,self.reader['cert'],'need',[h('x')]);value=self.source.answer(self.reader['cert'],'need',[h('x')])
        raw=self.x.make_response(self.p,self.s.devices[0]['seed'],he,req,True,value)
        other=self.x.make_request(self.p,self.reader['seed'],he,self.reader['cert'],'need',[h('z')])
        self.reject_exchange('RESPONSE_BINDING',lambda:self.x.check_response(self.p,self.source.public,he,other,raw,'need',[h('z')]))
    def test_unknown_method_before_signing(self):
        self.reject_exchange('METHOD_DENIED',lambda:self.x.make_request(self.p,self.reader['seed'],self.hello(),self.reader['cert'],'put',None))
    def test_duplicate_need_is_rejected(self):
        self.reject_exchange('INVALID_REQUEST',lambda:self.source.answer(self.reader['cert'],'need',[h('x'),h('x')]))
    def test_too_many_need_is_rejected(self):
        self.reject_exchange('INVALID_REQUEST',lambda:self.source.answer(self.reader['cert'],'need',[h(str(i)) for i in range(17)]))
    def test_negative_or_bool_offset(self):
        for offset in (-1,True):
            with self.subTest(offset=offset):self.reject_exchange('INVALID_REQUEST',lambda:self.source.answer(self.reader['cert'],'have',{0:None,1:offset,2:1}))
    def test_extra_key_rejected(self):
        self.reject_exchange('INVALID_REQUEST',lambda:self.source.answer(self.reader['cert'],'have',{0:None,1:0,2:1,3:0}))
    def test_claiming_applied_in_response_rejected(self):
        a=self.change();self.receive(a);r=self.source.answer(self.reader['cert'],'need',[self.cid(a[0])]);args={0:r[0],1:self.cid(a[0]),2:self.eid(a[0])};value=self.source.answer(self.reader['cert'],'get',args);value[5]='APPLIED'
        he=self.hello();req=self.x.make_request(self.p,self.reader['seed'],he,self.reader['cert'],'get',args);raw=self.x.make_response(self.p,self.s.devices[0]['seed'],he,req,True,value)
        self.reject_exchange('RESPONSE_SCHEMA',lambda:self.x.check_response(self.p,self.source.public,he,req,raw,'get',args))
