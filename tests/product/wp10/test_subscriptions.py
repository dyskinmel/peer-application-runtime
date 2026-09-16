import importlib, threading, unittest

class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        try:self.m=importlib.import_module('product.wp10.subscriptions')
        except ModuleNotFoundError:self.m=None
        self.assertTrue(self.m is not None and hasattr(self.m,'LatestSnapshot'),'bounded snapshot SDK not implemented')
    def test_initial_snapshot_delivered(self):
        seen=[];s=self.m.LatestSnapshot(1,b'initial',seen.append);self.assertEqual(s.dispatch(),'DELIVERED');self.assertEqual(seen[0].value,b'initial')
    def test_only_latest_pending_value(self):
        seen=[];s=self.m.LatestSnapshot(0,b'initial',seen.append)
        for n in range(1,100):s.publish(n,str(n).encode())
        self.assertEqual(s.pending_count,1);s.dispatch();self.assertEqual(len(seen),1);self.assertEqual(seen[0].revision,99)
    def test_same_revision_same_bytes_no_duplicate(self):
        seen=[];s=self.m.LatestSnapshot(1,b'x',seen.append);s.dispatch();s.publish(1,b'x');self.assertEqual(s.dispatch(),'IDLE');self.assertEqual(len(seen),1)
    def test_same_revision_different_bytes_refused(self):
        s=self.m.LatestSnapshot(1,b'x',lambda _:None)
        with self.assertRaises(self.m.SubscriptionError):s.publish(1,b'y')
    def test_older_revision_refused(self):
        s=self.m.LatestSnapshot(2,b'x',lambda _:None)
        with self.assertRaises(self.m.SubscriptionError):s.publish(1,b'y')
    def test_unsigned64_exact(self):
        seen=[];s=self.m.LatestSnapshot(2**64-1,b'x',seen.append);s.dispatch();self.assertEqual(seen[0].revision,2**64-1)
    def test_bool_revision_refused(self):
        with self.assertRaises(self.m.SubscriptionError):self.m.LatestSnapshot(True,b'x',lambda _:None)
    def test_maximum_bytes(self):
        with self.assertRaises(self.m.SubscriptionError):self.m.LatestSnapshot(0,b'x'*65537,lambda _:None)
    def test_mutable_buffer_refused(self):
        with self.assertRaises(self.m.SubscriptionError):self.m.LatestSnapshot(0,bytearray(b'x'),lambda _:None)
    def test_close_idempotent_no_future_callback(self):
        seen=[];s=self.m.LatestSnapshot(1,b'x',seen.append);s.close();s.close();self.assertEqual(s.dispatch(),'CLOSED');self.assertEqual(seen,[])
    def test_callback_throw_isolated(self):
        def cb(_):raise ValueError('private')
        s=self.m.LatestSnapshot(0,b'x',cb);self.assertEqual(s.dispatch(),'CALLBACK_FAILED');self.assertEqual(s.dispatch(),'IDLE')
    def test_callback_closes_itself(self):
        seen=[]
        def cb(v):seen.append(v);s.close()
        s=self.m.LatestSnapshot(1,b'x',cb);self.assertEqual(s.dispatch(),'DELIVERED');self.assertEqual(s.dispatch(),'CLOSED');self.assertEqual(len(seen),1)
    def test_callback_publishes_next_snapshot(self):
        seen=[]
        def cb(v):
            seen.append(v)
            if v.revision==1:s.publish(2,b'next')
        s=self.m.LatestSnapshot(1,b'x',cb);s.dispatch();s.dispatch();self.assertEqual([v.revision for v in seen],[1,2])
    def test_callback_reentrant_dispatch_refused(self):
        codes=[]
        def cb(_):
            try:s.dispatch()
            except self.m.SubscriptionError as e:codes.append(e.code)
        s=self.m.LatestSnapshot(1,b'x',cb);s.dispatch();self.assertEqual(codes,['REENTRANT_DISPATCH'])
    def test_wrong_thread_rejected(self):
        s=self.m.LatestSnapshot(1,b'x',lambda _:None);codes=[]
        def run():
            try:s.close()
            except self.m.SubscriptionError as e:codes.append(e.code)
        t=threading.Thread(target=run);t.start();t.join();self.assertEqual(codes,['WRONG_OWNER']);self.assertEqual(s.dispatch(),'DELIVERED')
    def test_not_durable_event_delivery(self):
        s=self.m.LatestSnapshot(1,b'x',lambda _:None);self.assertFalse(s.durable);self.assertEqual(s.capacity,1)

class PresenceTests(unittest.TestCase):
    def setUp(self):
        try:self.m=importlib.import_module('product.wp10.subscriptions')
        except ModuleNotFoundError:self.m=None
        self.assertTrue(self.m is not None and hasattr(self.m,'PresenceHints'),'volatile hints not implemented')
        self.now=100;self.p=self.m.PresenceHints(clock=lambda:self.now,max_peers=2);self.p.activate(b'a'*32,b's'*16)
    def update(self,seq=1,ttl=20):return self.p.update(b'a'*32,b's'*16,seq,b'editing',ttl_ns=ttl)
    def test_recent_then_unknown_not_offline(self):
        self.update();self.assertEqual(self.p.get(b'a'*32).state,'RECENT_HINT');self.now=120;self.assertEqual(self.p.get(b'a'*32).state,'RECENT_STATE_UNKNOWN')
    def test_duplicate_does_not_refresh_ttl(self):
        self.update();self.now=119;self.update();self.now=120;self.assertEqual(self.p.get(b'a'*32).state,'RECENT_STATE_UNKNOWN')
    def test_old_session_refused(self):
        self.update();self.p.activate(b'a'*32,b't'*16)
        with self.assertRaises(self.m.SubscriptionError):self.update(2)
    def test_recreated_cache_has_no_history(self):
        self.update();q=self.m.PresenceHints(clock=lambda:self.now);self.assertEqual(q.get(b'a'*32).state,'RECENT_STATE_UNKNOWN')
    def test_lower_sequence_refused(self):
        self.update(3)
        with self.assertRaises(self.m.SubscriptionError):self.update(2)
    def test_changed_duplicate_refused(self):
        self.update()
        with self.assertRaises(self.m.SubscriptionError):self.p.update(b'a'*32,b's'*16,1,b'other',ttl_ns=20)
    def test_ttl_upper_bound(self):
        with self.assertRaises(self.m.SubscriptionError):self.update(ttl=60000000001)
    def test_peer_limit(self):
        self.p.activate(b'b'*32,b's'*16)
        with self.assertRaises(self.m.SubscriptionError):self.p.activate(b'c'*32,b's'*16)
    def test_clock_regression_stops_hints(self):
        self.update();self.now=99
        with self.assertRaises(self.m.SubscriptionError) as e:self.p.get(b'a'*32)
        self.assertEqual(e.exception.code,'CLOCK_UNCERTAIN')
    def test_presence_not_durable(self):self.assertFalse(self.p.durable)
