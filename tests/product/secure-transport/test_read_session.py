import asyncio,dataclasses,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from secure_support import API
from process_fixture import Peer,h
from product.wp04.exchange import Source,ExchangeError

class ReadSessionTests(API,unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.load();self.raw=[];self.streams=[]
        self.assertTrue(hasattr(self.m,'ReadSession'),'TLS-bound signed read session missing')
        self.tmp=tempfile.TemporaryDirectory(prefix='par-read-tls-');root=Path(self.tmp.name)
        self.provider=Peer(root/'provider');self.reader=Peer(root/'reader')
        d=self.reader.s.devices[1];self.reader.source=Source(self.reader.box,d['cert'],d['seed'])
        self.generation=9
    async def asyncTearDown(self):
        await self.cleanup()
        for name in ('provider','reader'):
            if hasattr(self,name):getattr(self,name).close()
        if hasattr(self,'tmp'):self.tmp.cleanup()
    def bind(self,server,**kw):
        args=dict(peer_id='reader' if server else 'provider',
                  certificate=(self.reader if server else self.provider).source.certificate,
                  scope=tuple(self.provider.source.scope),peer_sha256=self.pki.pin('client' if server else 'server'),generation=9)
        args.update(kw);return self.m.PeerBinding(**args)
    async def sessions(self,*,server_binding=None,client_binding=None):
        s,c=await self.good_pair()
        server=self.m.ReadSession(s,self.provider.source,server_binding or self.bind(True),lambda:self.generation)
        client=self.m.ReadSession(c,self.reader.source,client_binding or self.bind(False),lambda:self.generation)
        return server,client
    async def rpc(self,action,args,**kw):
        s,c=await self.sessions(**kw)
        return await asyncio.gather(s.serve(),c.request(action,args),return_exceptions=True)
    async def test_empty_have(self):
        served,result=await self.rpc('have',{0:None,1:0,2:16})
        self.assertEqual(served['state'],'SERVED_READ_ONLY');self.assertEqual(result[2],[])
    async def test_real_store_have_need_get_preserves_ciphertext(self):
        a,b=self.provider.chain()
        for pair in (a,b):self.provider.box.receive(*pair)
        _,have=await self.rpc('have',{0:None,1:0,2:16});self.assertEqual(len(have[2]),2)
        _,need=await self.rpc('need',[h('inner:a')]);d=need[1][0][1]
        _,got=await self.rpc('get',{0:need[0],1:d[0],2:d[1]})
        self.assertEqual(got[3],a[0]);self.assertEqual(got[4],a[1]);self.assertEqual(got[5],'ENCRYPTED_PENDING_BYTES')
    async def test_read_does_not_mutate_either_store(self):
        for p in self.provider.chain():self.provider.box.receive(*p)
        before=[p.db._storage.connection.total_changes for p in (self.provider,self.reader)]
        await self.rpc('have',{0:None,1:0,2:16})
        self.assertEqual(before,[p.db._storage.connection.total_changes for p in (self.provider,self.reader)])
        self.assertEqual(self.reader.box.usage()['records'],0)
    async def test_one_request_per_connection(self):
        s,c=await self.sessions();await asyncio.gather(s.serve(),c.request('need',[h('missing')]))
        with self.assertRaises(self.m.TransportError) as cm:await c.request('need',[h('missing')])
        self.assertEqual(cm.exception.code,'SESSION_USED')
    async def test_publish_rejected(self):
        s,c=await self.sessions()
        with self.assertRaises(Exception):await c.request('publish',{})
        self.assertTrue(c.stream.closed)
    async def test_ack_rejected(self):
        s,c=await self.sessions()
        with self.assertRaises(Exception):await c.request('ack',{})
        self.assertTrue(c.stream.closed)
    async def test_peer_certificate_cannot_substitute_another_authorized_device(self):
        # TLS client is enrolled as device 1; it signs using another valid member.
        self.reader.source=Source(self.reader.box,self.reader.s.devices[0]['cert'],self.reader.s.devices[0]['seed'])
        binding=self.bind(True,certificate=self.provider.s.devices[1]['cert'])
        results=await self.rpc('need',[h('missing')],server_binding=binding)
        self.assertIsInstance(results[0],self.m.TransportError)
        self.assertEqual(results[0].code,'DEVICE_BINDING');self.assertIsInstance(results[1],Exception)
    async def test_scope_is_exact(self):
        s,c=await self.good_pair();scope=list(self.provider.source.scope);scope[2]=h('different-doc')
        with self.assertRaises(self.m.TransportError):self.m.ReadSession(s,self.provider.source,self.bind(True,scope=tuple(scope)),lambda:9)
    async def test_tls_pin_is_bound_to_membership_enrollment(self):
        s,c=await self.good_pair()
        with self.assertRaises(self.m.TransportError):self.m.ReadSession(s,self.provider.source,self.bind(True,peer_sha256='0'*64),lambda:9)
    async def test_stale_generation_before_request(self):
        s,c=await self.sessions();self.generation=10
        with self.assertRaises(self.m.TransportError):await c.request('need',[h('x')])
    async def test_generation_changed_while_answering(self):
        original=self.provider.source.answer
        def changed(*args):
            result=original(*args);self.generation=10;return result
        with patch.object(self.provider.source,'answer',side_effect=changed):results=await self.rpc('need',[h('x')])
        self.assertTrue(all(isinstance(v,Exception) for v in results))
    async def test_actual_authority_head_change_rejects_old_binding(self):
        s,c=await self.sessions();p=self.provider
        raw=p.s.raw(p.s.next(p.b['raw']));p.db.observe(p.s.space,raw);p.db.provide_membership(p.s.space,p.b['pages'])
        results=await asyncio.gather(s.serve(),c.request('need',[h('x')]),return_exceptions=True)
        self.assertTrue(all(isinstance(v,Exception) for v in results))
    async def test_keeper_only_member_denied(self):
        s,c=await self.good_pair()
        with self.assertRaises(Exception):self.m.ReadSession(s,self.provider.source,self.bind(True,certificate=self.provider.s.devices[2]['cert']),lambda:9)
    async def test_wrong_response_signature_rejected(self):
        from product.wp04 import exchange
        original=exchange.make_response
        def corrupt(*args):
            raw=original(*args);return raw[:-1]+bytes([raw[-1]^1])
        with patch.object(exchange,'make_response',side_effect=corrupt):results=await self.rpc('need',[h('x')])
        self.assertIsInstance(results[1],Exception)
    async def test_missing_is_signed_observation_not_global_absence(self):
        _,value=await self.rpc('need',[h('not-present')]);self.assertEqual(value[1],[[h('not-present'),None]])
    async def test_current_certificate_bounded_copy(self):
        b=self.bind(True)
        with self.assertRaises(dataclasses.FrozenInstanceError):b.generation=10
        with self.assertRaises(self.m.TransportError):self.bind(True,certificate=b'x'*4097)
    async def test_peer_binding_rejects_bool_generation(self):
        with self.assertRaises(self.m.TransportError):self.bind(True,generation=True)
    async def test_waiting_client_cancellation_is_not_absence(self):
        s,c=await self.sessions();cancel=asyncio.Event();t=asyncio.create_task(c.request('need',[h('x')],cancel=cancel))
        await asyncio.sleep(.02);cancel.set()
        with self.assertRaises(self.m.TransportError) as cm:await t
        self.assertEqual(cm.exception.code,'CANCELLED');self.assertTrue(c.stream.closed)
    async def test_disconnected_provider_is_not_absence(self):
        s,c=await self.sessions();s.stream.abort()
        with self.assertRaises(Exception):await c.request('need',[h('x')])
    async def test_snapshot_changed_before_get_rejected(self):
        a,b=self.provider.chain();self.provider.box.receive(*a)
        _,need=await self.rpc('need',[h('inner:a')]);d=need[1][0][1];self.provider.box.receive(*b)
        results=await self.rpc('get',{0:need[0],1:d[0],2:d[1]})
        self.assertTrue(all(isinstance(v,Exception) for v in results))
    async def test_caller_args_snapshotted_before_waiting_for_hello(self):
        s,c=await self.sessions();args=[h('original')]
        task=asyncio.create_task(c.request('need',args));await asyncio.sleep(.015)
        args[0]=h('changed')
        served,result=await asyncio.gather(s.serve(),task)
        self.assertEqual(result[1][0][0],h('original'))
    async def test_generation_change_during_cleanup_cannot_return_stale_success(self):
        s,c=await self.sessions();original=c.stream.close
        async def changed():
            await original();self.generation=10
        with patch.object(c.stream,'close',side_effect=changed):
            results=await asyncio.gather(s.serve(),c.request('need',[h('x')]),return_exceptions=True)
        self.assertIsInstance(results[1],self.m.TransportError)
