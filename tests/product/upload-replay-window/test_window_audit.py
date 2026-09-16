import hashlib,os,threading
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from window_support import WindowTest,h,pr
from par_upload_window import contract as c
from par_keeper_upload.spool import Spool
from par_keeper_upload_retire import RetiringSpool
from par_keeper.contract import put_payload
class WindowAudit(WindowTest):
    def test_empty_window_can_close(self):
        self.finish();self.assertEqual(self.window.diagnostics()['records'],0)
    def test_no_signature_generated_for_verification(self):
        self.terminal();r=self.finish();self.reopen_window()
        with patch.object(self.p,'sign',side_effect=AssertionError('unexpected signing')):
            self.assertEqual(self.window.compact(),r);self.window.diagnostics()
    def test_record_slots_reusable_after_closed_barrier(self):
        self.window.close();self.wroot=self.path/'small-window'
        self.window=self.w.ReplaySpool(self.keeper,self.wroot,self.store_id,max_records=2);self.window.open_window(self.grant)
        self.terminal();self.terminal();self.err('STAGING_CAPACITY',self.upload_stage)
        self.next_window();self.terminal();self.assertEqual(self.window.diagnostics()['records'],1)
    def test_archive_budget_is_separate_and_enforced(self):
        self.window.close();self.wroot=self.path/'budget-window'
        self.window=self.w.ReplaySpool(self.keeper,self.wroot,self.store_id,max_archive_bytes=1);self.window.open_window(self.grant)
        self.err('ARCHIVE_CAPACITY',self.upload_stage);self.assertEqual(self.window.diagnostics()['records'],0)
    def test_no_unbounded_window_rotation(self):
        self.window.close();self.wroot=self.path/'one-window'
        self.window=self.w.ReplaySpool(self.keeper,self.wroot,self.store_id,max_windows=1);self.window.open_window(self.grant)
        self.terminal();r=self.finish();self.err('WINDOW_LIMIT',lambda:self.window.open_window(self.grant_for(2,self.w.digest(r))))
    def test_reused_generation_nonce_rejected(self):
        self.terminal();r=self.finish();nonce=c.check_window(self.p,self.grant)[6]
        self.err('WINDOW_LIMIT',lambda:self.window.open_window(self.grant_for(2,c.digest(r),nonce)))
    def test_archive_missing_refused_on_reopen(self):
        self.terminal();self.finish();self.window.close();(self.wroot/'archives/00000001.cbor').unlink()
        self.err(None,self.reopen_window)
    def test_archive_corrupt_refused_on_reopen(self):
        self.terminal();self.finish();p=self.wroot/'archives/00000001.cbor';p.write_bytes(b'broken');self.err(None,self.reopen_window)
    def test_extra_archive_not_ignored(self):
        p=self.wroot/'archives/00000042.cbor';p.write_bytes(b'x');p.chmod(0o600);self.err('ARCHIVE_SET',self.window.diagnostics)
    def test_closed_metadata_reappeared_refused(self):
        t=self.terminal();old=self.live(t).read_bytes();self.finish();p=self.live(t);p.write_bytes(old);p.chmod(0o600)
        self.err('WINDOW_DATA_REAPPEARED',self.window.diagnostics)
    def test_changed_file_during_cleanup_refused(self):
        t=self.terminal();a,q=self.proposed();self.window.close_window(q,a);self.live(t).write_bytes(b'changed')
        self.err('WINDOW_RECORD_CHANGED',self.window.compact)
    def test_extra_file_during_cleanup_not_deleted(self):
        self.terminal();a,q=self.proposed();self.window.close_window(q,a);p=self.wroot/'live/unrelated.txt';p.write_bytes(b'keep');p.chmod(0o600)
        self.err(None,self.window.compact);self.assertEqual(p.read_bytes(),b'keep')
    def test_symlink_refused_before_deletion(self):
        t=self.terminal();a,q=self.proposed();self.window.close_window(q,a);target=self.path/'outside';target.write_bytes(b'keep')
        self.live(t).unlink();self.live(t).symlink_to(target);self.err(None,self.window.compact);self.assertEqual(target.read_bytes(),b'keep')
    def test_hardlink_refused_before_deletion(self):
        t=self.terminal();a,q=self.proposed();self.window.close_window(q,a);os.link(self.live(t),self.path/'alias')
        self.err(None,self.window.compact);self.assertTrue(self.live(t).exists())
    def test_state_corruption_refused(self):
        (self.wroot/'STATE.cbor').write_bytes(b'bad');self.err(None,self.window.diagnostics)
    def test_configuration_change_refused(self):
        p=self.wroot/'LIMITS.cbor';v=c.load(p.read_bytes());v[5]-=1;p.write_bytes(c.dump(v));self.err('WINDOW_SETTINGS_OR_LEGACY',self.window.diagnostics)
    def test_private_permission_required(self):
        self.wroot.chmod(0o755);self.err(None,self.window.diagnostics);self.wroot.chmod(0o700)
    def test_wrong_thread_refused(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(1) as e:self.err('OWNER_REQUIRED',lambda:e.submit(self.window.diagnostics).result())
    def test_concurrent_owner_refused(self):self.err(None,lambda:self.w.ReplaySpool(self.keeper,self.wroot,self.store_id))
    def test_old_hosts_reject_new_root(self):
        self.window.close()
        for typ in (Spool,RetiringSpool):self.err(None,lambda:typ(self.keeper,self.wroot))
    def test_legacy_root_not_silently_migrated(self):
        self.err('WINDOW_SETTINGS_OR_LEGACY',lambda:self.w.ReplaySpool(self.keeper,self.stage_root,self.store_id))
    def test_unbound_inserted_record_refused(self):
        t=self.terminal();(self.wroot/'bindings'/(t.hex()+'.bound')).unlink();self.err('WINDOW_BINDING_SET',self.window.diagnostics)
    def test_pin_detects_old_open_state(self):
        self.terminal();old=(self.wroot/'STATE.cbor').read_bytes();self.finish();pin=self.window.pin();self.window.close()
        (self.wroot/'STATE.cbor').write_bytes(old);self.err('WINDOW_PIN',lambda:self.reopen_window(expected_pin=pin))
    def test_pin_allows_forward_progress(self):
        self.terminal();self.finish();pin=self.window.pin();self.next_window(self.window.compact());self.reopen_window(expected_pin=pin)
    def test_pin_rejects_wrong_store(self):
        pin=self.window.pin();pin[0]=h('wrong');self.err('WINDOW_PIN',lambda:self.window.verify_pin(pin))
    def test_no_automatic_claim_of_rollback_protection(self):
        self.terminal();self.finish();d=self.window.diagnostics();self.assertFalse(d['physical_space_reclaimed']);self.assertFalse(d['product_qualified'])
    def test_archive_extra_trailing_bytes_refused(self):
        self.terminal();a,_=self.proposed();self.err(None,lambda:c.check_archive(self.p,a+b'extra',self.grant))
    def test_archive_duplicate_file_refused_even_when_keeper_signed(self):
        self.terminal();a,_=self.proposed();b=c.check_archive(self.p,a,self.grant);b[5].append(b[5][0]);raw=c.sign_archive(self.p,self.ks,b)
        self.err(None,lambda:c.check_archive(self.p,raw,self.grant))
    def test_archive_omitted_binding_refused(self):
        self.terminal();a,_=self.proposed();b=c.check_archive(self.p,a,self.grant);b[5]=[e for e in b[5] if not e[0].startswith('bindings/')]
        self.err('ARCHIVE_SET',lambda:c.check_archive(self.p,c.sign_archive(self.p,self.ks,b),self.grant))
    def test_archive_wrong_file_count_refused(self):
        self.terminal();a,_=self.proposed();b=c.check_archive(self.p,a,self.grant);b[6]+=1
        self.err('ARCHIVE_SET',lambda:c.check_archive(self.p,c.sign_archive(self.p,self.ks,b),self.grant))
    def test_object_handoff_terminal_and_keeper_unchanged(self):
        _,lid=self.complete_index();oid=sorted(self.bundle.objects)[0];data=self.bundle.objects[oid]
        call=self.call('put',lid,put_payload(oid,data));b=self.cmd('begin',['object',oid,len(data),hashlib.sha256(data).digest()],lid,call)
        t=self.execute(b)[0]
        for i in range(0,len(data),pr.CHUNK):self.execute(self.cmd('chunk',[t,i,data[i:i+pr.CHUNK]],lid))
        self.execute(self.cmd('put',t,lid,call));before=list(self.keeper.connection.iterdump());self.finish();self.assertEqual(list(self.keeper.connection.iterdump()),before)
    def test_missing_destination_proof_refuses_closure(self):
        self.complete_index();self.keeper.connection.execute('DELETE FROM operations');self.err('HANDOFF_NOT_VERIFIED',self.window.export_archive)
    def test_archive_larger_than_wire_frame_supported(self):
        # The archive is a framed local audit container, NOT a >1MiB wire message.
        self.terminal();a,_=self.proposed();body=c.check_archive(self.p,a,self.grant)
        # Exercise byte budget without claiming synthetic padding is a valid terminal record.
        entry=list(body[5][0]);entry[5]=b'x'*200000;entry[1]=len(entry[5]);entry[2]=hashlib.sha256(entry[5]).digest()
        body[5]=[entry]*6
        raw=c.sign_archive(self.p,self.ks,body);self.assertGreater(len(raw),1048576)
        self.err(None,lambda:c.check_archive(self.p,raw,self.grant))
