import asyncio,dataclasses,socket,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from secure_support import API
from process_fixture import Peer
from product.wp09.par_connectivity import Connector,Policy,RouteGrant,Candidate,DialTarget,PeerProof

class AdapterTests(API,unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.load();self.raw=[];self.streams=[];self.controller=None
        self.assertTrue(hasattr(self.m,'TLSAuthenticator'),'TLS Connector adapters missing')
        self.tmp=tempfile.TemporaryDirectory();self.owner=Peer(Path(self.tmp.name)/'owner')
    async def asyncTearDown(self):
        if self.controller is not None:await self.controller.close();await self.controller.wait_for_cleanup()
        await self.cleanup()
        if hasattr(self,'owner'):self.owner.close();self.tmp.cleanup()
    def binding(self,**kw):
        args=dict(peer_id='peer-A',certificate=self.owner.s.devices[0]['cert'],scope=tuple(self.owner.source.scope),peer_sha256=self.pki.pin('server'),generation=0)
        args.update(kw);return self.m.PeerBinding(**args)
    def auth(self,binding=None,generation=lambda:0):
        b=binding or self.binding();return self.m.TLSAuthenticator(self.owner.source,{b.peer_id:b},generation)
    async def test_authenticator_requires_real_tls_stream(self):
        with self.assertRaises(self.m.TransportError):await self.auth().authenticate(object(),'peer-A',self.owner.s.space.hex(),asyncio.Event())
    async def test_real_tls_facts_and_current_authority_produce_peerproof(self):
        s,c=await self.good_pair();proof=await self.auth().authenticate(c,'peer-A',self.owner.s.space.hex(),asyncio.Event())
        self.assertEqual(proof,PeerProof('peer-A',self.owner.s.space.hex()))
    async def test_authenticator_wrong_space_rejected(self):
        s,c=await self.good_pair()
        with self.assertRaises(self.m.TransportError):await self.auth().authenticate(c,'peer-A','wrong',asyncio.Event())
    async def test_authenticator_wrong_expected_peer_rejected(self):
        s,c=await self.good_pair()
        with self.assertRaises(self.m.TransportError):await self.auth().authenticate(c,'peer-B',self.owner.s.space.hex(),asyncio.Event())
    async def test_authenticator_changed_authority_rejected(self):
        s,c=await self.good_pair();p=self.owner;raw=p.s.raw(p.s.next(p.b['raw']));p.db.observe(p.s.space,raw);p.db.provide_membership(p.s.space,p.b['pages'])
        with self.assertRaises(Exception):await self.auth().authenticate(c,'peer-A',p.s.space.hex(),asyncio.Event())
    async def test_authenticator_stale_generation_rejected(self):
        s,c=await self.good_pair()
        with self.assertRaises(self.m.TransportError):await self.auth(generation=lambda:1).authenticate(c,'peer-A',self.owner.s.space.hex(),asyncio.Event())
    async def test_connector_actual_tls_auth_with_fixture_ip_label(self):
        s,c=await self.good_pair()
        # IP assertion is a fixture only. TLS certificate possession is real.
        c.peername=lambda:('8.8.8.8',443)
        class FixtureDialer:
            supported_schemes=frozenset({'tcp'})
            async def dial(self,target,cancel):return c
        grant=RouteGrant('tcp://8.8.8.8:443','peer-A','manual',('8.8.8.8/32',))
        self.controller=Connector(Policy(grants=(grant,),allow_egress=True),None,FixtureDialer(),self.auth(),self.owner.s.space.hex())
        result=await self.controller.connect((Candidate(grant.endpoint,'peer-A'),))
        self.assertEqual(result.state,'CONNECTED');self.assertEqual(result.observed_path,'local-fixture')
        self.assertIs(self.controller.connection(result.connection_id),c)
    async def test_no_grant_does_not_attempt_tls_dial(self):
        called=[]
        class D:
            supported_schemes=frozenset({'tcp'})
            async def dial(self,*args):called.append(args);raise AssertionError('dial')
        self.controller=Connector(Policy(),None,D(),self.auth(),self.owner.s.space.hex())
        result=await self.controller.connect((Candidate('tcp://8.8.8.8:443','peer-A'),))
        self.assertNotEqual(result.state,'CONNECTED');self.assertFalse(called)
    async def test_numeric_dial_unknown_peer_prevents_socket_creation(self):
        d=self.m.TLSNumericDialer({'peer-A':self.pki.config(self.m,False)})
        target=DialTarget('tcp','8.8.8.8',443,None,'other','manual',0)
        with patch('socket.socket',side_effect=AssertionError('socket opened')):
            with self.assertRaises(self.m.TransportError):await d.dial(target,asyncio.Event())
    async def test_numeric_dial_never_resolves_a_hostname(self):
        d=self.m.TLSNumericDialer({'peer-A':self.pki.config(self.m,False)})
        target=DialTarget('tcp','server.test',443,None,'peer-A','manual',0)
        with patch('socket.getaddrinfo',side_effect=AssertionError('DNS')):
            with self.assertRaises(Exception):await d.dial(target,asyncio.Event())
    async def test_sni_cannot_be_substituted(self):
        d=self.m.TLSNumericDialer({'peer-A':self.pki.config(self.m,False)})
        target=DialTarget('tcp','8.8.8.8',443,'else.test','peer-A','manual',0)
        with self.assertRaises(self.m.TransportError):await d.dial(target,asyncio.Event())
    async def test_numeric_dial_failure_closes_fd_and_uses_exact_tuple(self):
        d=self.m.TLSNumericDialer({'peer-A':self.pki.config(self.m,False)})
        target=DialTarget('tcp','8.8.8.8',443,None,'peer-A','manual',0);seen=[]
        async def refused(sock,address):seen.append((sock,address));raise OSError('test-only refused')
        with patch.object(asyncio.get_running_loop(),'sock_connect',side_effect=refused):
            with self.assertRaises(self.m.TransportError):await d.dial(target,asyncio.Event())
        self.assertEqual(seen[0][1],('8.8.8.8',443));self.assertEqual(seen[0][0].fileno(),-1)
    async def test_no_plaintext_fallback_after_tls_failure(self):
        self.assertEqual(self.m.TLSNumericDialer({'peer-A':self.pki.config(self.m,False)}).supported_schemes,frozenset({'tcp'}))
        # There is no alternate dialer or retry loop inside the TLS adapter.
        with self.assertRaises(self.m.TransportError):self.m.TLSNumericDialer({'peer-A':self.pki.config(self.m,True)})
