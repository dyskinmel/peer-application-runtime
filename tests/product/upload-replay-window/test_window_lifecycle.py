from window_support import WindowTest,h,pr
class WindowLifecycle(WindowTest):
    def test_active_upload_blocks_close(self):self.upload_stage();self.err('WINDOW_NOT_TERMINAL',self.window.export_archive)
    def test_retired_stage_allows_close(self):
        self.terminal();r=self.finish();self.assertTrue(r);self.assertEqual(self.window.diagnostics()['phase'],'CLEANED')
    def test_committed_handoff_allows_close_without_keeper_change(self):
        t,lid=self.complete_index();before=self.keeper.diagnostics();self.finish();self.assertEqual(self.keeper.diagnostics(),before)
    def test_closed_commands_rejected_before_cleanup(self):
        self.terminal();raw,req=self.proposed();self.window.close_window(req,raw)
        self.err('WINDOW_CLOSED',lambda:self.window.execute(self.beginwrapped))
    def test_closed_cannot_start_next_until_compacted(self):
        self.terminal();raw,req=self.proposed();self.window.close_window(req,raw)
        self.err('WINDOW_NOT_CLEANED',lambda:self.window.open_window(self.grant_for(2,h('fake'))))
    def test_old_begin_replay_after_new_window(self):
        self.terminal();old=self.beginwrapped;self.next_window();self.err('WINDOW_SCOPE',lambda:self.window.execute(old))
    def test_new_signed_window_can_reuse_operation_id(self):
        self.terminal();inner=self.beginraw;self.next_window();r=self.window.execute(self.wrap(inner));self.assertEqual(r[1],0)
    def test_delayed_chunk_rejected_after_new_window(self):
        t=self.terminal();old=self.wrap(self.cmd('chunk',[t,8,b'late']));self.next_window();self.err('WINDOW_SCOPE',lambda:self.window.execute(old))
    def test_retirement_replay_rejected_after_new_window(self):
        self.terminal();old=self.wrap(self.retirement_request(),'retire');self.next_window();self.err('WINDOW_SCOPE',lambda:self.window.execute(old))
    def test_old_seal_rejected_before_destination_lookup(self):
        self.terminal();call=self.call('seal',h('lease'));old=self.wrap(self.cmd('seal',None,h('lease'),call));self.next_window();self.err('WINDOW_SCOPE',lambda:self.window.execute(old))
    def test_compaction_idempotent(self):
        self.terminal();r=self.finish();self.assertEqual(self.window.compact(),r)
    def test_open_retry_idempotent(self):
        self.upload_stage();self.window.open_window(self.grant);self.assertEqual(self.window.diagnostics()['records'],1)
    def test_no_automatic_new_window(self):
        self.terminal();self.finish();self.reopen_window();self.assertEqual(self.window.diagnostics()['phase'],'CLEANED')
    def test_wrong_predecessor_denied(self):
        self.terminal();self.finish();self.err('WINDOW_ORDER',lambda:self.window.open_window(self.grant_for(2,h('wrong'))))
    def test_sequence_jump_denied(self):
        self.terminal();r=self.finish();self.err('WINDOW_ORDER',lambda:self.window.open_window(self.grant_for(3,self.w.digest(r))))
    def test_state_survives_restart(self):
        self.terminal();r=self.finish();self.reopen_window();self.assertEqual(self.window.compact(),r)
    def test_keeper_database_bytes_unchanged_by_cleanup(self):
        self.terminal();before=list(self.keeper.connection.iterdump());self.finish();self.assertEqual(list(self.keeper.connection.iterdump()),before)
    def test_archive_keeps_exact_old_metadata(self):
        t=self.terminal();raw=self.live(t).read_bytes();a,req=self.proposed();entries=self.w.check_archive(self.p,a,self.grant)[5]
        self.assertIn(raw,[x[5] for x in entries]);self.window.close_window(req,a);self.window.compact();self.assertFalse(self.live(t).exists())
    def test_snapshot_stale_on_new_stage(self):
        self.terminal();a,q=self.proposed();self.terminal();self.err('ARCHIVE_CHANGED',lambda:self.window.close_window(q,a))
    def test_current_authority_needed_to_close(self):
        self.terminal();a,q=self.proposed();self.change_authority();self.err('STALE_AUTHORITY',lambda:self.window.close_window(q,a))
    def test_committed_close_cleanup_survives_authority_change(self):
        self.terminal();a,q=self.proposed();self.window.close_window(q,a);self.change_authority();self.window.compact();self.assertEqual(self.window.diagnostics()['phase'],'CLEANED')
