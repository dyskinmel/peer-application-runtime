"""Actual private socket/process I/O; DNS and IP path are explicit local fixtures."""
import asyncio,os,socket,subprocess,sys,unittest,json
from pathlib import Path
from unittest.mock import patch
from product.wp09 import par_connectivity as api
from fixtures import Resolver,Dialer,Authenticator,settled
from test_policy import grant,policy,PUBLIC,DNS
PEER=Path(__file__).with_name('fixture_peer.py')

class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertTrue(callable(getattr(api,'SocketConnection',None)),'real adapter integration is not implemented')
        self.children=[];self.clients=[];self.transports=[];self.r=Resolver();self.d=Dialer();self.a=Authenticator();self.mode='ok';self.entered=asyncio.Event()
        outer=self
        class FixtureSocket:
            observed_path='local-fixture'
            def __init__(self,target,inner):self.target=target;self.inner=inner
            def peername(self):return (self.target.ip,self.target.port)
            async def close(self):await self.inner.close()
        async def dial(target,cancel):
            a,b=socket.socketpair()
            child=subprocess.Popen([sys.executable,'-I','-S','-B',str(PEER),str(b.fileno()),outer.mode],pass_fds=(b.fileno(),),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            b.close();outer.children.append(child);inner=api.SocketConnection(a,io_timeout=0.3);outer.transports.append(inner);return FixtureSocket(target,inner)
        async def auth(connection,peer,scope,cancel):
            await connection.inner.write(b'P');outer.entered.set();result=await connection.inner.read_exact(2)
            if result!=b'OK':raise ValueError('fixture peer refused')
            return api.PeerProof(peer,scope)
        self.d.handler=dial;self.a.handler=auth
    async def asyncTearDown(self):
        for c in getattr(self,'clients',[]):await c.close();await c.wait_for_cleanup()
        for c in getattr(self,'transports',[]):await c.close()
        for p in getattr(self,'children',[]):
            try:p.wait(timeout=0.2)
            except subprocess.TimeoutExpired:p.terminate();p.wait(timeout=1)
    def client(self,p=None):
        c=api.Connector(p or policy(grant()),self.r,self.d,self.a,'scope-A');self.clients.append(c);return c
    async def test_separate_process_fixture_handshake(self):
        c=self.client();r=await c.connect((api.Candidate(PUBLIC,'peer-A'),));self.assertEqual((r.state,r.observed_path),('CONNECTED','local-fixture'));await c.close()
        self.assertTrue(all(x.io_state()['closed'] for x in self.transports));self.children[0].wait(timeout=1);self.assertEqual(self.children[0].returncode,0)
    async def test_wrong_fixture_transcript_not_authenticated(self):
        self.mode='bad';c=self.client();r=await c.connect((api.Candidate(PUBLIC,'peer-A'),));self.assertEqual(r.reason,'AUTH_FAILED');self.assertEqual(c.diagnostics()['connections'],0)
    async def test_process_exit_during_auth_not_success(self):
        self.mode='eof';c=self.client();r=await c.connect((api.Candidate(PUBLIC,'peer-A'),));self.assertEqual(r.reason,'AUTH_FAILED');self.assertTrue(self.transports[0].io_state()['closed'])
    async def test_stalled_process_deadline_and_descriptor_cleanup(self):
        self.mode='stall';c=self.client(policy(grant(),timeout=0.06));r=await c.connect((api.Candidate(PUBLIC,'peer-A'),));self.assertEqual(r.reason,'DEADLINE');self.assertTrue(self.transports[0].io_state()['closed'])
    async def test_network_change_during_real_socket_read(self):
        self.mode='stall';c=self.client();t=asyncio.create_task(c.connect((api.Candidate(PUBLIC,'peer-A'),)));await self.entered.wait();await c.change_network(metered=True);r=await t
        self.assertEqual(r.reason,'STALE_GENERATION');self.assertTrue(self.transports[0].io_state()['closed']);self.assertEqual(len(self.d.calls),1)
    async def test_cancel_during_real_socket_read(self):
        self.mode='stall';stop=asyncio.Event();c=self.client();t=asyncio.create_task(c.connect((api.Candidate(PUBLIC,'peer-A'),),cancel=stop));await self.entered.wait();stop.set();r=await t
        self.assertEqual(r.reason,'CANCELLED');self.assertTrue(self.transports[0].io_state()['closed'])
    async def test_no_dns_or_ip_socket_egress_in_fixture_integration(self):
        c=self.client(policy(grant(DNS,resolver_id='fixture')))
        with patch('socket.getaddrinfo',side_effect=AssertionError('UNEXPECTED_DNS')),patch.object(socket.socket,'connect',side_effect=AssertionError('UNEXPECTED_EGRESS')):
            r=await c.connect((api.Candidate(DNS,'peer-A'),));self.assertEqual(r.state,'CONNECTED')
    async def test_forbidden_dns_never_creates_child(self):
        async def resolve(h,r,s):return api.Resolution(h,r,('8.8.8.8','127.0.0.1'))
        self.r.handler=resolve;c=self.client(policy(grant(DNS,resolver_id='fixture')));r=await c.connect((api.Candidate(DNS,'peer-A'),))
        self.assertEqual(r.reason,'LOCAL_ADDRESS_DENIED');self.assertEqual(self.children,[])
    async def test_private_fixture_child_stays_in_harness_group(self):
        self.mode='stall';c=self.client();t=asyncio.create_task(c.connect((api.Candidate(PUBLIC,'peer-A'),)));await self.entered.wait()
        self.assertEqual(os.getpgid(self.children[0].pid),os.getpgrp());await c.close();self.assertEqual((await t).reason,'CLOSED')
    async def test_repeated_explicit_connect_disconnect_no_descriptor_growth(self):
        fd_dir='/proc/self/fd' if os.path.isdir('/proc/self/fd') else '/dev/fd'
        before=len(os.listdir(fd_dir));c=self.client()
        for _ in range(5):
            r=await c.connect((api.Candidate(PUBLIC,'peer-A'),));self.assertEqual(r.state,'CONNECTED');await c.disconnect(r.connection_id);self.children[-1].wait(timeout=1)
        self.assertEqual(len(os.listdir(fd_dir)),before);self.assertEqual(c.diagnostics()['connections'],0)
    async def test_explicit_reconnect_is_new_generation_without_implicit_dial(self):
        c=self.client();r=await c.connect((api.Candidate(PUBLIC,'peer-A'),));await c.change_network(metered=False)
        self.assertEqual(len(self.d.calls),1);self.assertEqual(len(self.children),1)
        second=await c.connect((api.Candidate(PUBLIC,'peer-A'),));self.assertEqual(second.generation,1);self.assertNotEqual(r.connection_id,second.connection_id)
        self.assertEqual(len(self.d.calls),2);self.assertEqual(len(self.children),2)
    async def test_development_demo_reports_fixture_not_public_auth(self):
        path=Path(__file__).resolve().parents[3]/'examples/connectivity_demo.py'
        p=await asyncio.create_subprocess_exec(sys.executable,'-I','-S','-B',str(path),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        out,err=await p.communicate();self.assertEqual(p.returncode,0,err.decode())
        r=json.loads(out);self.assertEqual(r['result'],'PASS');self.assertEqual(r['observed_path'],'local-fixture')
        self.assertFalse(r['real_peer_auth_executed']);self.assertFalse(r['public_network_executed'])
        self.assertTrue(r['cleanup']['cleanup_complete']);self.assertEqual(r['dial_calls'],1)
        self.assertEqual(r['network_change_generation'],1)
