import copy,socket,time,struct
from unittest.mock import patch
from exchange_support import ExchangeTest,h
from par_wire.codec import decode,encode

class HardeningTests(ExchangeTest):
    def reply(self,action,args,value):
        he=self.x.make_hello(self.p,self.s.devices[0]['seed'],self.source.scope,h('boot'),h('challenge'),5000)
        req=self.x.make_request(self.p,self.reader['seed'],he,self.reader['cert'],action,args)
        raw=self.x.make_response(self.p,self.s.devices[0]['seed'],he,req,True,value)
        return self.x.check_response(self.p,self.source.public,he,req,raw,action,args)
    def test_signed_have_cannot_alias_two_inner_ids_to_one_envelope(self):
        rows=sorted([[h('x'),h('envelope'),10],[h('y'),h('envelope'),10]])
        self.reject_exchange('RESPONSE_SCHEMA',lambda:self.reply('have',{0:None,1:0,2:16},{0:h('token'),1:0,2:rows,3:None,4:2}))
    def test_signed_get_cannot_substitute_a_different_scope(self):
        raw,cert=self.change(header_patch={3:h('wrong-doc')});cid=self.cid(raw);eid=self.eid(raw);args={0:h('token'),1:cid,2:eid}
        self.reject_exchange('RESPONSE_SCHEMA',lambda:self.reply('get',args,{0:h('token'),1:cid,2:eid,3:raw,4:cert,5:'ENCRYPTED_PENDING_BYTES'}))
    def test_signed_need_cannot_omit_requested_id(self):
        self.reject_exchange('RESPONSE_SCHEMA',lambda:self.reply('need',[h('a'),h('b')],{0:h('token'),1:[[h('a'),None]]}))
    def test_signed_need_cannot_reorder_ids(self):
        self.reject_exchange('RESPONSE_SCHEMA',lambda:self.reply('need',[h('a'),h('b')],{0:h('token'),1:[[h('b'),None],[h('a'),None]]}))
    def test_signed_page_cannot_make_no_progress(self):
        self.reject_exchange('RESPONSE_SCHEMA',lambda:self.reply('have',{0:None,1:0,2:1},{0:h('token'),1:0,2:[],3:0,4:2}))
    def test_signed_page_cannot_hide_more_rows(self):
        self.reject_exchange('RESPONSE_SCHEMA',lambda:self.reply('have',{0:None,1:0,2:1},{0:h('token'),1:0,2:[[h('a'),h('e'),1]],3:None,4:2}))
    def test_signed_get_tamper_fails_identity(self):
        a=self.change();args={0:h('token'),1:self.cid(a[0]),2:self.eid(a[0])}
        self.reject_exchange('RESPONSE_SCHEMA',lambda:self.reply('get',args,{**args,3:a[0][:-1]+bytes([a[0][-1]^1]),4:a[1],5:'ENCRYPTED_PENDING_BYTES'}))
    def test_current_source_key_must_match_certificate(self):
        self.reject_exchange('NOT_AUTHORIZED',lambda:self.x.Source(self.box,self.s.devices[0]['cert'],h('wrong')))
    def test_storage_only_member_cannot_run_source(self):
        d=self.s.devices[2];self.reject_exchange('NOT_AUTHORIZED',lambda:self.x.Source(self.box,d['cert'],d['seed']))
    def test_source_scope_returned_copy(self):
        scope=self.source.scope;scope[2]=h('change');self.assertNotEqual(scope,self.source.scope)
    def test_page_limit_bool_rejected(self):
        self.reject_exchange('INVALID_REQUEST',lambda:self.source.answer(self.reader['cert'],'have',{0:None,1:0,2:True}))
    def test_mutable_need_id_rejected(self):
        self.reject_exchange('INVALID_REQUEST',lambda:self.source.answer(self.reader['cert'],'need',[bytearray(h('x'))]))
    def test_catalog_bound_reports_resource_not_invalid_data(self):
        self.fill()
        with patch.object(self.x,'MAX_CATALOG',1):
            self.reject_exchange('RESOURCE_BLOCKED',lambda:self.source.answer(self.reader['cert'],'need',[h('inner:a')]))
    def test_total_deadline_does_not_extend_on_partial_progress(self):
        self.start_server(deadline_ms=100);s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.addCleanup(s.close);s.connect(str(self.socket_path))
        for _ in range(4):self.server.poll(.002)
        s.sendall(b'\0');end=time.monotonic()+.17
        while time.monotonic()<end:self.server.poll(.01)
        self.assertFalse(self.server.connections);self.assertGreaterEqual(self.server.counts['expired'],1)
    def test_overload_bounded_and_other_client_recovers(self):
        self.start_server(max_connections=1);a=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);b=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.addCleanup(a.close);self.addCleanup(b.close)
        a.connect(str(self.socket_path));self.server.poll(.002);b.connect(str(self.socket_path))
        for _ in range(5):self.server.poll(.002)
        self.assertEqual(len(self.server.connections),1);self.assertGreaterEqual(self.server.counts['overloaded'],1)
        a.close()
        for _ in range(5):self.server.poll(.002)
        self.rpc(lambda:self.client().need([h('none')]))
    def test_refuses_symlink_endpoint_parent(self):
        p=self.root.parent/'alias';p.symlink_to(self.root.parent,target_is_directory=True)
        from par_keeper_service.errors import ServiceError
        with self.assertRaises(ServiceError):self.x.Server(self.source,p/'socket')
