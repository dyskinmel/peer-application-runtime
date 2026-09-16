import hashlib, importlib, os
from dataclasses import replace
from test_host_service import WindowService
from host_support import h,pr
from snapshot_support import module

class CachedWindowService(WindowService):
    """Existing live socket/authority guards run unchanged with a warm verifier."""
    def setUp(self):
        super().setUp();self.snapmod=module(self);self.cache=self.snapmod.VerificationProvider(self.p,mode='signatures')
        self.keeper.provider=self.cache;self.window.provider=self.cache;self.window._inner.provider=self.cache
    def tearDown(self):
        try:super().tearDown()
        finally:
            if hasattr(self,'cache'):self.cache.close()

class SnapshotLiveState(CachedWindowService):
    # No inherited test duplicates in discovery: runner only exposes this class's
    # newly declared cases, and CachedWindowService separately exposes old cases.
    def observe(self):
        m=importlib.import_module('par_verified_host.host');return m.observe_host(self.cache,self.keeper,self.window)
    def test_warm_stamp_reuses_crypto_but_rechecks_bytes(self):
        t,_=self.complete_index();q=self.wrap(self.cmd('progress',t));self.observe();a=self.window.stamp(q);one=self.cache.statistics();b=self.window.stamp(q);two=self.cache.statistics()
        self.assertEqual(a,b);self.assertGreater(two['hits'],one['hits'])
        self.assertEqual(two['backend_calls'],one['backend_calls'])
    def test_same_mtime_binding_mutation_rejected(self):
        self.complete_index();self.window.diagnostics();path=next((self.wroot/'bindings').glob('*.bound'));raw=path.read_bytes();st=path.stat()
        path.write_bytes(raw[:-1]+bytes([raw[-1]^1]));os.utime(path,ns=(st.st_atime_ns,st.st_mtime_ns))
        self.err(None,lambda:self.window.diagnostics())
    def test_same_mtime_state_mutation_rejected(self):
        self.observe();self.window.diagnostics();path=self.wroot/'STATE.cbor';raw=path.read_bytes();st=path.stat()
        path.write_bytes(raw[:-1]+bytes([raw[-1]^1]));os.utime(path,ns=(st.st_atime_ns,st.st_mtime_ns))
        self.err('WINDOW_STATE_CHANGED',lambda:self.window.diagnostics())
    def test_missing_warm_archive_rejected(self):
        self.finish();self.window.diagnostics();next((self.wroot/'archives').iterdir()).unlink();self.err('ARCHIVE_MISSING',lambda:self.window.diagnostics())
    def test_warm_archive_replacement_rejected(self):
        self.finish();self.window.diagnostics();p=next((self.wroot/'archives').iterdir());raw=p.read_bytes();p.write_bytes(raw[:-1]+bytes([raw[-1]^1]));self.err(None,lambda:self.window.diagnostics())
    def test_signed_wrong_state_semantics_still_rejected(self):
        self.window.diagnostics();from par_upload_window import contract as c;state=c.load(c.dump(self.window.state));state[4][0][1]='NOT_A_PHASE'
        raw=c.signed(self.cache,self.ks,'state',state);path=self.wroot/'STATE.cbor';path.write_bytes(raw);self.window._last_raw=raw
        self.err('WINDOW_STATE',lambda:self.window.diagnostics())
    def test_scope_change_discards_signatures(self):
        self.observe();self.window.diagnostics();self.assertGreater(self.cache.statistics()['entries'],0);e=self.cache.statistics()['epoch'];self.change_authority();self.observe()
        self.assertEqual(self.cache.statistics()['entries'],0);self.assertGreater(self.cache.statistics()['epoch'],e)
    def test_scope_unchanged_does_not_imply_authorized(self):
        t,_=self.complete_index();q=self.wrap(self.cmd('progress',t));self.observe();self.window.stamp(q);self.change_authority();self.err('CAPABILITY_SCOPE',lambda:self.window.stamp(q))
    def test_window_scope_change_discards(self):
        self.observe();self.window.diagnostics();self.finish();self.observe();self.assertEqual(self.cache.statistics()['entries'],0)
    def test_database_authority_mismatch_rejected(self):
        self.complete_index();q=self.wrap(self.cmd('progress',pr.token_for(self.p,self.beginraw)));self.window.stamp(q)
        self.keeper.connection.execute('UPDATE metadata SET authority=?',(b'bad',));self.err(None,lambda:self.window.stamp(q))
    def test_gatekeeper_provider_mismatch_rejected(self):
        self.keeper.provider=self.p;self.err('PROVIDER_SCOPE',self.observe)
    def test_poisoned_gateway_refused(self):
        self.observe();self.window.poison=True;self.err('RECOVERY_REQUIRED',self.observe);self.assertEqual(self.cache.statistics()['entries'],0)
    def test_scope_failure_keeps_state_checks(self):
        self.complete_index();self.window.diagnostics();self.window.close();self.err('CLOSED',self.observe)
    def test_mutation_result_equal_in_full_and_cached(self):
        q=self.command();first=self.window.execute(q);self.cache.invalidate('comparison')
        with self.cache.full_verification():second=self.window.execute(q)
        self.assertEqual(first,second);self.assertEqual(self.window.diagnostics()['records'],1)

    def test_foreign_observer_cannot_clear_owner_snapshot(self):
        import threading
        self.observe();self.window.diagnostics();before=self.cache.statistics();errors=[]
        def call():
            try:self.observe()
            except Exception as exc:errors.append(getattr(exc,'code',None))
        t=threading.Thread(target=call);t.start();t.join()
        self.assertEqual(errors,['OWNER_REQUIRED'])
        self.assertEqual(self.cache.statistics(),before)
