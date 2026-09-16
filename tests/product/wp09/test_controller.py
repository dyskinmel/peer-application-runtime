import asyncio,dataclasses,unittest
from product.wp09 import par_connectivity as api
from fixtures import Resolver,Dialer,Authenticator,FixtureConnection,settled
from test_policy import grant,policy,PUBLIC,DNS

class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertTrue(callable(getattr(api,'Connector',None)),'bounded connectivity controller is not implemented')
        self.r=Resolver();self.d=Dialer();self.a=Authenticator();self.clients=[]
    async def asyncTearDown(self):
        for c in getattr(self,'clients',[]):await c.close()
    def client(self,p=None,**kw):
        c=api.Connector(p or policy(grant()),self.r,self.d,self.a,'scope-A',**kw);self.clients.append(c);return c
    def rows(self,*endpoints):return tuple(api.Candidate(e,'peer-A') for e in endpoints or (PUBLIC,))
    async def test_explicit_success_reports_fixture_not_direct(self):
        c=self.client();r=await c.connect(self.rows())
        self.assertEqual((r.state,r.reason,r.observed_path),('CONNECTED','AUTHENTICATED','local-fixture'))
        self.assertEqual(c.connection(r.connection_id),self.d.connections[0]);self.assertEqual(self.r.calls,[])
    async def test_no_candidate_never_dials_or_resolves(self):
        c=self.client();r=await c.connect(())
        self.assertEqual(r.reason,'NO_CANDIDATES');self.assertEqual(self.r.calls+self.d.calls+self.a.calls,[])
    async def test_default_deny_never_touches_ports(self):
        c=self.client(api.Policy());r=await c.connect(self.rows());self.assertEqual(r.reason,'EGRESS_DENIED')
        self.assertEqual(self.r.calls+self.d.calls+self.a.calls,[])
    async def test_no_grant_prevents_dns(self):
        c=self.client(policy());r=await c.connect(self.rows(DNS));self.assertEqual(r.reason,'ROUTE_NOT_GRANTED');self.assertEqual(self.r.calls,[])
    async def test_no_dns_grant_no_resolver_call(self):
        c=self.client(policy(grant(DNS)));r=await c.connect(self.rows(DNS));self.assertEqual(r.reason,'DNS_NOT_GRANTED');self.assertEqual(self.r.calls,[])
    async def test_dns_query_has_only_name_and_resolver(self):
        c=self.client(policy(grant(DNS,resolver_id='dns-A')));r=await c.connect(self.rows(DNS))
        self.assertEqual(r.state,'CONNECTED');self.assertEqual(self.r.calls,[('peer.invalid','dns-A')]);self.assertEqual(self.d.calls[0].ip,'8.8.8.8')
    async def test_forbidden_second_dns_address_blocks_all_dials(self):
        async def resolve(h,r,s):return api.Resolution(h,r,('8.8.8.8','169.254.169.254'))
        self.r.handler=resolve;c=self.client(policy(grant(DNS,resolver_id='dns-A')));r=await c.connect(self.rows(DNS))
        self.assertEqual(r.reason,'SPECIAL_ADDRESS_DENIED');self.assertEqual(self.d.calls,[])
    async def test_resolver_exception_does_not_leak_sensitive_text(self):
        async def fail(*args):raise OSError('PRIVATE_ERROR_SENTINEL')
        self.r.handler=fail;c=self.client(policy(grant(DNS,resolver_id='dns-A')));r=await c.connect(self.rows(DNS))
        self.assertEqual(r.reason,'RESOLVE_FAILED');self.assertNotIn('PRIVATE',repr(r));self.assertEqual(self.d.calls,[])
    async def test_no_dns_cache_between_explicit_calls(self):
        async def resolve(h,r,s):return api.Resolution(h,r,('8.8.8.8',) if len(self.r.calls)==1 else ('127.0.0.1',))
        self.r.handler=resolve;c=self.client(policy(grant(DNS,resolver_id='dns-A')))
        r=await c.connect(self.rows(DNS));await c.disconnect(r.connection_id)
        second=await c.connect(self.rows(DNS));self.assertEqual(second.reason,'LOCAL_ADDRESS_DENIED');self.assertEqual(len(self.d.calls),1)
    async def test_dialed_peer_must_match_pinned_ip(self):
        async def dial(t,s):
            conn=FixtureConnection(t);conn.peer_override=('1.1.1.1',t.port);self.d.connections.append(conn);return conn
        self.d.handler=dial;c=self.client();r=await c.connect(self.rows())
        self.assertEqual(r.reason,'PEER_ADDRESS_MISMATCH');self.assertEqual(self.a.calls,[]);self.assertEqual(self.d.connections[0].closed,1)
    async def test_dialed_peer_must_match_pinned_port(self):
        async def dial(t,s):
            conn=FixtureConnection(t);conn.peer_override=(t.ip,1);self.d.connections.append(conn);return conn
        self.d.handler=dial;c=self.client();r=await c.connect(self.rows());self.assertEqual(r.reason,'PEER_ADDRESS_MISMATCH')
    async def test_wrong_peer_identity_never_connects(self):
        async def auth(c,p,s,a):return api.PeerProof('other',s)
        self.a.handler=auth;c=self.client();r=await c.connect(self.rows());self.assertEqual(r.reason,'AUTH_MISMATCH');self.assertIsNone(r.connection_id);self.assertEqual(self.d.connections[0].closed,1)
    async def test_wrong_space_identity_never_connects(self):
        async def auth(c,p,s,a):return api.PeerProof(p,'other')
        self.a.handler=auth;c=self.client();r=await c.connect(self.rows());self.assertEqual(r.reason,'AUTH_MISMATCH')
    async def test_auth_exception_retires_connection(self):
        async def auth(*args):raise ValueError('PRIVATE_ERROR_SENTINEL')
        self.a.handler=auth;c=self.client();r=await c.connect(self.rows());self.assertEqual(r.reason,'AUTH_FAILED');self.assertEqual(self.d.connections[0].closed,1)
    async def test_adapter_path_is_not_inferred_from_candidate(self):
        async def dial(t,s):
            conn=FixtureConnection(t);conn.observed_path='relayed';self.d.connections.append(conn);return conn
        self.d.handler=dial;c=self.client();r=await c.connect(self.rows());self.assertEqual(r.reason,'PATH_UNVERIFIED')
    async def test_quic_without_adapter_is_not_direct(self):
        ep='quic://8.8.8.8:443';c=self.client(policy(grant(ep)));r=await c.connect(self.rows(ep))
        self.assertEqual(r.reason,'ADAPTER_UNAVAILABLE');self.assertIsNone(r.observed_path);self.assertEqual(self.d.calls,[])
    async def test_relay_is_explicitly_unimplemented(self):
        g=api.RouteGrant(PUBLIC,'peer-A','relay',('0.0.0.0/0',));c=self.client(policy(g));r=await c.connect((api.Candidate(PUBLIC,'peer-A','relay'),))
        self.assertEqual(r.reason,'RELAY_UNAVAILABLE');self.assertEqual(self.d.calls,[])
    async def test_only_supplied_candidates_are_attempted(self):
        async def fail(*args):raise ConnectionError('fail')
        self.d.handler=fail;ep='tcp://1.1.1.1:443';c=self.client(policy(grant(),grant(ep)))
        r=await c.connect(self.rows());self.assertEqual(r.reason,'DIAL_FAILED');self.assertEqual([x.ip for x in self.d.calls],['8.8.8.8'])
    async def test_explicit_fallback_after_dial_failure(self):
        async def dial(t,s):
            if t.ip=='8.8.8.8':raise ConnectionError('fail')
            conn=FixtureConnection(t);self.d.connections.append(conn);return conn
        self.d.handler=dial;ep='tcp://1.1.1.1:443';c=self.client(policy(grant(),grant(ep)));r=await c.connect(self.rows(PUBLIC,ep))
        self.assertEqual(r.state,'CONNECTED');self.assertEqual([x.ip for x in self.d.calls],['8.8.8.8','1.1.1.1'])
    async def test_attempt_budget_is_not_reset_per_candidate(self):
        async def fail(*args):raise ConnectionError('fail')
        self.d.handler=fail;ep='tcp://1.1.1.1:443';c=self.client(policy(grant(),grant(ep),max_attempts=1));r=await c.connect(self.rows(PUBLIC,ep))
        self.assertEqual(r.reason,'ATTEMPT_BUDGET');self.assertEqual(len(self.d.calls),1)
    async def test_total_address_budget(self):
        async def resolve(h,r,s):return api.Resolution(h,r,('8.8.8.8','1.1.1.1'))
        self.r.handler=resolve;c=self.client(policy(grant(DNS,resolver_id='dns-A'),max_total_addresses=1));r=await c.connect(self.rows(DNS))
        self.assertEqual(r.reason,'TOTAL_ADDRESS_BUDGET');self.assertEqual(self.d.calls,[])
    async def test_precancel_has_no_side_effect(self):
        stop=asyncio.Event();stop.set();c=self.client();r=await c.connect(self.rows(),cancel=stop)
        self.assertEqual(r.reason,'CANCELLED');self.assertEqual(self.d.calls,[])
    async def test_cancel_during_resolver(self):
        entered=asyncio.Event()
        async def resolve(h,r,s):entered.set();await s.wait();return api.Resolution(h,r,('8.8.8.8',))
        self.r.handler=resolve;c=self.client(policy(grant(DNS,resolver_id='dns-A')));stop=asyncio.Event();task=asyncio.create_task(c.connect(self.rows(DNS),cancel=stop))
        await entered.wait();stop.set();r=await task;self.assertEqual(r.reason,'CANCELLED');self.assertEqual(self.d.calls,[])
    async def test_cancel_after_dial_before_auth_disposes_late_connection(self):
        entered=asyncio.Event();release=asyncio.Event()
        async def dial(t,s):
            entered.set()
            try:await release.wait()
            except asyncio.CancelledError:await release.wait()
            conn=FixtureConnection(t);self.d.connections.append(conn);return conn
        self.d.handler=dial;c=self.client();stop=asyncio.Event();task=asyncio.create_task(c.connect(self.rows(),cancel=stop))
        await entered.wait();stop.set();r=await task;self.assertEqual(r.reason,'CANCELLED');self.assertEqual(self.a.calls,[])
        self.assertEqual(c.diagnostics()['lingering'],1);release.set();await settled(lambda: self.d.connections and self.d.connections[0].closed==1)
        await settled(lambda:c.diagnostics()['lingering']==0 and c.diagnostics()['retiring']==0)
    async def test_noncooperative_cancellation_keeps_resource_reservation(self):
        entered=asyncio.Event();release=asyncio.Event()
        async def dial(t,s):
            entered.set()
            try:await release.wait()
            except asyncio.CancelledError:await release.wait()
            conn=FixtureConnection(t);self.d.connections.append(conn);return conn
        self.d.handler=dial;c=self.client(policy(grant(),max_inflight=1));stop=asyncio.Event();task=asyncio.create_task(c.connect(self.rows(),cancel=stop))
        await entered.wait();stop.set();await task
        blocked=await c.connect(self.rows());self.assertEqual(blocked.reason,'INFLIGHT_BUDGET');self.assertEqual(len(self.d.calls),1)
        release.set();await settled(lambda:self.d.connections and self.d.connections[0].closed==1)
    async def test_task_cancellation_is_propagated_after_retirement(self):
        entered=asyncio.Event()
        async def auth(c,p,s,a):entered.set();await a.wait();return api.PeerProof(p,s)
        self.a.handler=auth;c=self.client();t=asyncio.create_task(c.connect(self.rows()));await entered.wait();t.cancel()
        with self.assertRaises(asyncio.CancelledError):await t
        await settled(lambda:self.d.connections[0].closed==1)
    async def test_network_change_fences_pending_dns(self):
        entered=asyncio.Event()
        async def resolve(h,r,s):entered.set();await s.wait();return api.Resolution(h,r,('8.8.8.8',))
        self.r.handler=resolve;c=self.client(policy(grant(DNS,resolver_id='dns-A')));t=asyncio.create_task(c.connect(self.rows(DNS)))
        await entered.wait();await c.change_network(metered=False);r=await t
        self.assertEqual(r.reason,'STALE_GENERATION');self.assertEqual(c.diagnostics()['generation'],1);self.assertEqual(self.d.calls,[])
    async def test_network_change_during_auth_never_promotes_old_handle(self):
        entered=asyncio.Event()
        async def auth(c,p,s,a):entered.set();await a.wait();return api.PeerProof(p,s)
        self.a.handler=auth;c=self.client();t=asyncio.create_task(c.connect(self.rows()));await entered.wait();await c.change_network(metered=False);r=await t
        self.assertEqual(r.reason,'STALE_GENERATION');self.assertEqual(c.diagnostics()['connections'],0);self.assertEqual(self.d.connections[0].closed,1)
    async def test_network_change_closes_active_and_never_replays(self):
        c=self.client();r=await c.connect(self.rows());await c.change_network(metered=False)
        self.assertEqual(self.d.connections[0].closed,1);self.assertEqual(len(self.d.calls),1);self.assertEqual(c.diagnostics()['connections'],0)
        with self.assertRaises(api.ConnectivityError):c.connection(r.connection_id)
    async def test_policy_replacement_does_not_reuse_prior_grant(self):
        c=self.client();await c.connect(self.rows());await c.change_network(metered=False,policy=api.Policy());r=await c.connect(self.rows())
        self.assertEqual(r.reason,'EGRESS_DENIED');self.assertEqual(len(self.d.calls),1)
    async def test_metered_user_and_background_are_separate(self):
        c=self.client(policy(grant(),allow_metered_user=True));await c.change_network(metered=True)
        r=await c.connect(self.rows(),purpose='background');self.assertEqual(r.reason,'METERED_DENIED');self.assertEqual(self.d.calls,[])
        r=await c.connect(self.rows(),purpose='user');self.assertEqual(r.state,'CONNECTED')
    async def test_metered_default_denies_all(self):
        c=self.client();await c.change_network(metered=True);r=await c.connect(self.rows());self.assertEqual(r.reason,'METERED_DENIED');self.assertEqual(self.d.calls,[])
    async def test_invalid_purpose_or_cancel_is_rejected(self):
        c=self.client();self.assertEqual((await c.connect(self.rows(),purpose='relay-unlimited')).reason,'INVALID_PURPOSE')
        self.assertEqual((await c.connect(self.rows(),cancel=object())).reason,'INVALID_CANCEL')
    async def test_deadline_resolver_is_finite(self):
        async def wait(*args):await asyncio.Event().wait()
        self.r.handler=wait;c=self.client(policy(grant(DNS,resolver_id='dns-A'),timeout=0.02));r=await c.connect(self.rows(DNS))
        self.assertEqual(r.reason,'DEADLINE');self.assertEqual(self.d.calls,[])
    async def test_single_deadline_spans_dns_dial_and_auth(self):
        async def resolve(h,r,s):await asyncio.sleep(0.018);return api.Resolution(h,r,('8.8.8.8',))
        async def dial(t,s):await asyncio.sleep(0.018);conn=FixtureConnection(t);self.d.connections.append(conn);return conn
        async def auth(c,p,s,a):await asyncio.sleep(0.03);return api.PeerProof(p,s)
        self.r.handler=resolve;self.d.handler=dial;self.a.handler=auth;c=self.client(policy(grant(DNS,resolver_id='dns-A'),timeout=0.05));r=await c.connect(self.rows(DNS))
        self.assertEqual(r.reason,'DEADLINE');self.assertEqual(c.diagnostics()['connections'],0)
    async def test_parallel_connects_have_shared_inflight_limit(self):
        entered=asyncio.Event();release=asyncio.Event()
        async def dial(t,s):entered.set();await release.wait();conn=FixtureConnection(t);self.d.connections.append(conn);return conn
        self.d.handler=dial;c=self.client(policy(grant(),max_inflight=1));t=asyncio.create_task(c.connect(self.rows()));await entered.wait()
        r=await c.connect(self.rows());self.assertEqual(r.reason,'INFLIGHT_BUDGET');release.set();self.assertEqual((await t).state,'CONNECTED')
    async def test_active_connections_are_bounded(self):
        c=self.client(policy(grant(),max_connections=1));r=await c.connect(self.rows());r2=await c.connect(self.rows());self.assertEqual(r2.reason,'CONNECTION_BUDGET')
        await c.disconnect(r.connection_id);self.assertEqual((await c.connect(self.rows())).state,'CONNECTED')
    async def test_close_is_terminal_and_idempotent(self):
        c=self.client();await c.connect(self.rows());await c.close();await c.close();r=await c.connect(self.rows())
        self.assertEqual(r.reason,'CLOSED');self.assertEqual(self.d.connections[0].closed,1)
    async def test_close_unblocks_pending_auth(self):
        entered=asyncio.Event()
        async def auth(c,p,s,a):entered.set();await a.wait();return api.PeerProof(p,s)
        self.a.handler=auth;c=self.client();t=asyncio.create_task(c.connect(self.rows()));await entered.wait();await c.close();r=await t
        self.assertEqual(r.reason,'CLOSED');self.assertEqual(self.d.connections[0].closed,1)
    async def test_close_failure_is_visible_and_stops_admission(self):
        c=self.client();r=await c.connect(self.rows());self.d.connections[0].close_error=True;await c.disconnect(r.connection_id)
        self.assertEqual(c.diagnostics()['cleanup_failures'],1);r=await c.connect(self.rows());self.assertEqual(r.reason,'CLEANUP_FAILED')
    async def test_slow_cleanup_stays_reserved_and_never_claims_done(self):
        c=self.client(policy(grant(),max_connections=1,cleanup_timeout=0.01));r=await c.connect(self.rows());release=asyncio.Event();self.d.connections[0].close_wait=release
        status=await c.disconnect(r.connection_id);self.assertEqual(status['retiring'],1)
        self.assertEqual((await c.connect(self.rows())).reason,'CONNECTION_BUDGET');release.set();await settled(lambda:c.diagnostics()['retiring']==0)
    async def test_diagnostics_do_not_expose_peer_scope_or_endpoints(self):
        c=self.client();await c.connect(self.rows());text=str(c.diagnostics());self.assertNotIn('peer-A',text);self.assertNotIn('scope-A',text);self.assertNotIn('8.8.8.8',text)
