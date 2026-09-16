from dataclasses import replace
from window_support import WindowTest,h,pr
class WindowContract(WindowTest):
    def test_issuer_grant_roundtrip(self):
        g=self.w.check_window(self.p,self.grant);self.assertEqual((g[4],g[5],g[7]),(self.store_id,1,None))
    def test_window_tamper(self):
        q=self.grant[:-1]+bytes([self.grant[-1]^1]);self.err(None,lambda:self.w.check_window(self.p,q))
    def test_wrong_issuer_cannot_issue(self):
        self.err(None,lambda:self.w.make_window(self.p,self.cs,self.keeper.authority,self.kp,self.store_id,1,h('n'),None))
    def test_boolean_sequence_denied(self):self.err(None,lambda:self.grant_for(True,None))
    def test_zero_sequence_denied(self):self.err(None,lambda:self.grant_for(0,None))
    def test_large_sequence_denied(self):self.err(None,lambda:self.grant_for(65,h('previous')))
    def test_first_predecessor_denied(self):self.err(None,lambda:self.grant_for(1,h('previous')))
    def test_later_without_predecessor_denied(self):self.err(None,lambda:self.grant_for(2,None))
    def test_raw_legacy_command_not_admitted(self):
        self.upload_stage();self.err(None,lambda:self.window.execute(self.beginraw))
    def test_wrong_subject_cannot_wrap(self):
        self.upload_stage();self.err(None,lambda:self.w.wrap_command(self.p,self.s.owner,self.grant,'execute',self.beginraw))
    def test_unknown_kind_denied(self):
        self.upload_stage();self.err(None,lambda:self.wrap(self.beginraw,'shell'))
    def test_signed_wrapper_binds_generation(self):
        self.upload_stage();other=self.grant_for(1,None,h('other'))
        self.err('WINDOW_SCOPE',lambda:self.window.execute(self.wrap(self.beginraw,grant=other)))
    def test_signed_wrapper_tamper(self):
        self.upload_stage();raw=self.beginwrapped[:-1]+bytes([self.beginwrapped[-1]^1]);self.err(None,lambda:self.window.execute(raw))
    def test_close_wrong_issuer(self):
        self.terminal();raw=self.window.export_archive()
        self.err(None,lambda:self.w.approve_close(self.p,self.cs,self.authority,self.grant,raw,h('op')))
    def test_archive_wrong_signature(self):
        self.terminal();raw=self.window.export_archive();bad=raw[:-1]+bytes([raw[-1]^1])
        self.err(None,lambda:self.w.check_archive(self.p,bad,self.grant))
    def test_close_binds_archive(self):
        self.terminal();raw,req=self.proposed();bad=raw[:-1]+bytes([raw[-1]^1])
        self.err(None,lambda:self.window.close_window(req,bad))
    def test_no_expiry_clock_based_rollover(self):
        self.clock.ns+=10**18;self.assertEqual(self.window.diagnostics()['phase'],'OPEN')
    def test_existing_upload_methods_unchanged(self):
        self.assertEqual(pr.METHODS,frozenset(('begin','chunk','progress','reserve','put','seal')))
