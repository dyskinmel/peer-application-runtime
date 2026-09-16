"""Public synthetic keys; assert wire behavior, not mock call counts."""
import importlib,socket,struct,time,unittest
from keeper_support import ContractTest,h
from par_keeper import make_call
from par_keeper.contract import split
from par_wire.codec import encode,decode
from par_crypto.primitives import domain

class ServiceContract(ContractTest):
    def setUp(self):
        super().setUp()
        self.s=importlib.import_module('par_keeper_service')
        self.assertTrue(hasattr(self.s,'make_hello'),'Private service protocol is not implemented')
        self.capability=self.cap();self.lid=h('lease');self.oid=h('object')
        self.hello=self.s.make_hello(self.p,self.seed,h('boot'),h('connection'),1000)
    def req(self,action='get',payload=None,**kw):
        payload=self.oid if action=='get' and payload is None else payload
        inner=action if action in ('get','status','receipt','challenge') else 'status'
        call=make_call(self.p,self.subject,self.capability,inner,self.lid,h('operation'),payload if inner==action else None)
        return self.s.make_request(self.p,self.subject,kw.get('hello',self.hello),kw.get('cap',self.capability),call,action,self.lid,payload)
    def err(self,code,fn):
        with self.assertRaises(self.s.ServiceError) as c:fn()
        if code:self.assertEqual(c.exception.code,code)
    def test_hello_verifies_pinned_key_and_nonce(self):
        b=self.s.check_hello(self.p,self.pk,self.hello)
        self.assertEqual((b[2],b[3],b[4]),(self.pk,h('boot'),h('connection')))
    def test_hello_wrong_pinned_key(self):
        self.err('HELLO_AUTH',lambda:self.s.check_hello(self.p,self.sp,self.hello))
    def test_hello_signature_modified(self):
        outer=decode(self.hello);outer[1]=bytes(64)
        self.err('HELLO_AUTH',lambda:self.s.check_hello(self.p,self.pk,encode(outer)))
    def test_request_valid_get(self):
        req=self.req();r=self.s.check_request(self.p,self.pk,self.hello,req)
        self.assertEqual((r.action,r.lease,r.payload,r.capability),('get',self.lid,self.oid,self.capability))
    def test_request_wrong_subject_key(self):
        call=make_call(self.p,self.subject,self.capability,'status',self.lid,h('op'))
        self.err('REQUEST_AUTH',lambda:self.s.make_request(self.p,self.seed,self.hello,self.capability,call,'status',self.lid,None))
    def test_request_old_connection_replay(self):
        new=self.s.make_hello(self.p,self.seed,h('boot'),h('different'),1000)
        self.err('REQUEST_SCOPE',lambda:self.s.check_request(self.p,self.pk,new,self.req()))
    def test_request_old_server_boot_replay(self):
        new=self.s.make_hello(self.p,self.seed,h('new-boot'),h('connection'),1000)
        self.err('REQUEST_SCOPE',lambda:self.s.check_request(self.p,self.pk,new,self.req()))
    def test_request_signature_modified(self):
        raw=decode(self.req());raw[1]=bytes(64)
        self.err('REQUEST_AUTH',lambda:self.s.check_request(self.p,self.pk,self.hello,encode(raw)))
    def test_response_bound_to_request(self):
        q=self.req();raw=self.s.make_response(self.p,self.seed,self.hello,q,True,b'data')
        self.assertEqual(self.s.check_response(self.p,self.pk,self.hello,q,raw),b'data')
        self.err('RESPONSE_SCOPE',lambda:self.s.check_response(self.p,self.pk,self.hello,self.req('status'),raw))
    def test_response_bound_to_connection(self):
        q=self.req();raw=self.s.make_response(self.p,self.seed,self.hello,q,True,b'data')
        hello=self.s.make_hello(self.p,self.seed,h('boot'),h('other'),1000)
        self.err('RESPONSE_SCOPE',lambda:self.s.check_response(self.p,self.pk,hello,q,raw))
    def test_response_signature_modified(self):
        q=self.req();raw=decode(self.s.make_response(self.p,self.seed,self.hello,q,True,b'x'));raw[1]=bytes(64)
        self.err('RESPONSE_AUTH',lambda:self.s.check_response(self.p,self.pk,self.hello,q,encode(raw)))
    def test_response_error_is_stable_code(self):
        q=self.req();r=self.s.make_response(self.p,self.seed,self.hello,q,False,'REQUEST_REJECTED')
        self.err('REMOTE_REQUEST_REJECTED',lambda:self.s.check_response(self.p,self.pk,self.hello,q,r))
    def test_response_arbitrary_error_text_rejected(self):
        self.err('PROTOCOL_SCHEMA',lambda:self.s.make_response(self.p,self.seed,self.hello,self.req(),False,'/private/key secret'))
    def test_response_unknown_field(self):
        q=self.req();o=decode(self.s.make_response(self.p,self.seed,self.hello,q,True,b'x'));b=decode(o[0]);b[99]=1;body=encode(b)
        raw=encode({0:body,1:self.p.sign(self.seed,domain('keeper-service-local/response-sign',[body]))})
        self.err('PROTOCOL_SCHEMA',lambda:self.s.check_response(self.p,self.pk,self.hello,q,raw))
    def test_unknown_request_field(self):
        q=decode(self.req());b=decode(q[0]);b[99]='extra';body=encode(b)
        raw=encode({0:body,1:self.p.sign(self.subject,domain('keeper-service-local/request-sign',[body]))})
        self.err('PROTOCOL_SCHEMA',lambda:self.s.check_request(self.p,self.pk,self.hello,raw))
    def test_strict_duplicate_map_key(self):
        self.err('PROTOCOL_SCHEMA',lambda:self.s.check_request(self.p,self.pk,self.hello,bytes.fromhex('a2004100004100')))
    def test_noncanonical_cbor(self):
        self.err('PROTOCOL_SCHEMA',lambda:self.s.check_hello(self.p,self.pk,b'\x18\x01'))
    def test_boolean_is_not_version(self):
        o=decode(self.hello);b=decode(o[0]);b[0]=True;body=encode(b);raw=encode({0:body,1:self.p.sign(self.seed,domain('keeper-service-local/hello-sign',[body]))})
        self.err('PROTOCOL_SCHEMA',lambda:self.s.check_hello(self.p,self.pk,raw))
    def test_request_limits_before_decode(self):
        self.err('FRAME_LIMIT',lambda:self.s.check_request(self.p,self.pk,self.hello,b'X'*(self.s.MAX_REQUEST+1)))
    def test_frame_roundtrip(self):
        a,b=socket.socketpair()
        try:
            a.sendall(self.s.frame(b'hello',64));self.assertEqual(self.s.receive(b,64,time.monotonic()+1),b'hello')
        finally:a.close();b.close()
    def test_frame_excess_length_without_body(self):
        a,b=socket.socketpair()
        try:
            a.sendall(struct.pack('>I',65));self.err('FRAME_LIMIT',lambda:self.s.receive(b,64,time.monotonic()+1))
        finally:a.close();b.close()
    def test_frame_zero_length(self):
        a,b=socket.socketpair()
        try:a.sendall(bytes(4));self.err('FRAME_LIMIT',lambda:self.s.receive(b,64,time.monotonic()+1))
        finally:a.close();b.close()
    def test_frame_partial_eof(self):
        a,b=socket.socketpair()
        try:
            a.sendall(b'\x00\x00\x00\x03x');a.shutdown(socket.SHUT_WR)
            self.err('DISCONNECTED',lambda:self.s.receive(b,64,time.monotonic()+1))
        finally:a.close();b.close()
    def test_frame_deadline_is_absolute(self):
        a,b=socket.socketpair()
        try:self.err('DEADLINE',lambda:self.s.receive(b,64,time.monotonic()+.02))
        finally:a.close();b.close()
    def test_signature_domain_separation(self):
        q=self.req();o=decode(q);o[1]=self.p.sign(self.subject,domain('keeper-local/request-sign',[o[0]]))
        self.err('REQUEST_AUTH',lambda:self.s.check_request(self.p,self.pk,self.hello,encode(o)))
    def test_response_not_retention_receipt(self):
        q=self.req('status');r=self.s.make_response(self.p,self.seed,self.hello,q,True,{0:False})
        self.assertFalse(self.s.check_response(self.p,self.pk,self.hello,q,r)[0])

def add_negative(name,fn):
    def test(self):self.err(None,lambda:fn(self))
    test.__name__='test_'+name;setattr(ServiceContract,test.__name__,test)
for method in ('reserve','put','seal','renew','release','collect','repair','__import__','shutdown','diagnostics'):
    add_negative('method_not_public_'+method.replace('_','x'),lambda t,m=method:t.req(m))
for i,v in enumerate((b'',b'X'*31,bytes(33),'nonce',None)):
    add_negative('bad_hello_nonce_'+str(i),lambda t,v=v:t.s.make_hello(t.p,t.seed,h('b'),v,1000))
for v in (True,0,49,30001,1.5):
    add_negative('deadline_type_range_'+str(v).replace('.','_'),lambda t,v=v:t.s.make_hello(t.p,t.seed,h('b'),h('c'),v))
