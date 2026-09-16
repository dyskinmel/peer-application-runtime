from keeper_support import KeeperTest,h,replace,decode
class KeeperLifecycle(KeeperTest):
    def test_expiry_retains_bytes_and_quota(self):
        lid,rc=self.ready();self.clock.ns+=31*10**9;self.assertEqual(self.status(lid)['state'],'EXPIRED_RETAINED');self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total);self.assertTrue(self.get(lid,next(iter(self.bundle.objects))))
    def test_reboot_retains_unknown(self):
        lid,rc=self.ready();self.keeper.close();self.clock.boot=h('new-boot');self.clock.ns=0;self.open_keeper();self.assertEqual(self.status(lid)['state'],'UNKNOWN_RETAINED');self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total)
    def test_backward_clock_is_unknown(self):
        lid,rc=self.ready();self.clock.ns-=1;self.assertEqual(self.status(lid)['state'],'UNKNOWN_RETAINED')
    def test_backward_clock_cannot_issue_receipt(self):
        self.open_keeper();lid=self.reserve();self.fill(lid);self.clock.ns-=1;self.err('CLOCK_UNCERTAIN',lambda:self.seal(lid))
    def test_explicit_renew_after_reboot(self):
        lid,rc=self.ready();self.keeper.close();self.clock.boot=h('new-boot');self.clock.ns=5;self.open_keeper();new=self.renew(lid);self.assertNotEqual(rc,new);self.assertEqual(self.status(lid)['state'],'RETAINED_ACTIVE')
    def test_renew_increments_generation(self):
        lid,rc=self.ready();self.clock.ns+=5*10**9;new=self.renew(lid);b=decode(decode(new)[0]);self.assertEqual(b[17],2);self.assertEqual(b[20],self.clock.ns+30*10**9)
    def test_duplicate_renew_does_not_extend_twice(self):
        lid,rc=self.ready();a=self.renew(lid,nonce=h('renew'));self.clock.ns+=10**9;b=self.renew(lid,nonce=h('renew'));self.assertEqual(a,b)
    def test_renew_shorter_promise_denied(self):
        lid,rc=self.ready();self.err('RETENTION_SHORTENING',lambda:self.renew(lid,seconds=1))
    def test_renew_longer_than_cap_denied(self):
        lid,rc=self.ready();self.err('DURATION_DENIED',lambda:self.renew(lid,seconds=61))
    def test_renew_missing_bytes_denied(self):
        lid,rc=self.ready();self.keeper.object_path(lid,next(iter(self.bundle.objects))).unlink();self.err('INCOMPLETE',lambda:self.renew(lid))
    def test_release_never_deletes_or_refunds(self):
        lid,rc=self.ready();self.release(lid);self.assertEqual(self.status(lid)['state'],'RELEASED_RETAINED');self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total)
        self.assertTrue(all(self.keeper.object_path(lid,x).exists() for x in self.bundle.objects))
    def test_release_stops_get(self):
        lid,rc=self.ready();self.release(lid);self.err('LEASE_RELEASED',lambda:self.get(lid,next(iter(self.bundle.objects))))
    def test_release_stops_renew(self):
        lid,rc=self.ready();self.release(lid);self.err('LEASE_RELEASED',lambda:self.renew(lid))
    def test_release_is_idempotent(self):
        lid,rc=self.ready();a=self.release(lid,h('release'));b=self.release(lid,h('release'));self.assertEqual(a,b)
    def test_release_persists_on_restart(self):
        lid,rc=self.ready();self.release(lid);self.keeper.close();self.open_keeper();self.assertEqual(self.status(lid)['state'],'RELEASED_RETAINED');self.err('LEASE_RELEASED',lambda:self.get(lid,next(iter(self.bundle.objects))))
    def test_new_authority_revokes_old_capability(self):
        lid,rc=self.ready();a=replace(self.authority,head=h('new-head'),sequence=2);self.keeper.update_authority(a);self.err('CAPABILITY_SCOPE',lambda:self.get(lid,next(iter(self.bundle.objects))))
    def test_stale_authority_reopen_denied(self):
        lid,rc=self.ready();self.keeper.update_authority(replace(self.authority,head=h('new-head'),sequence=2));self.keeper.close();self.err('STALE_AUTHORITY',self.open_keeper)
    def test_authority_rollback_rejected(self):
        self.open_keeper();self.keeper.update_authority(replace(self.authority,head=h('new-head'),sequence=2));self.err('STALE_AUTHORITY',lambda:self.keeper.update_authority(self.authority))
    def test_same_sequence_fork_authority_rejected(self):
        self.open_keeper();self.err('STALE_AUTHORITY',lambda:self.keeper.update_authority(replace(self.authority,head=h('fork'))))
    def test_regrant_old_closure_by_current_authority(self):
        lid,rc=self.ready();a=replace(self.authority,head=h('new-head'),sequence=2);self.keeper.update_authority(a)
        g=self.k.issue_capability(self.p,self.s.owner,a,self.kp,self.cp,self.rpin.index_id,('get',),60,h('regrant'));self.assertTrue(self.get(lid,next(iter(self.bundle.objects)),g))
    def test_challenge_signature_binds_nonce(self):
        lid,rc=self.ready();c=self.call('challenge',lid,h('challenge'));raw=self.keeper.challenge(lid,h('challenge'),self.cap,c)
        v=decode(raw);from par_crypto.primitives import domain
        self.p.verify(self.kp,domain('keeper-local/observation-sign',[v[0]]),v[1]);body=decode(v[0]);self.assertEqual(body[4],h('challenge'));self.assertIs(body[8],False)
    def test_challenge_corruption_never_proves_complete(self):
        lid,rc=self.ready();self.keeper.object_path(lid,next(iter(self.bundle.objects))).unlink();self.err('INCOMPLETE',lambda:self.keeper.challenge(lid,h('challenge'),self.cap,self.call('challenge',lid,h('challenge'))))
    def test_reentrant_callback_cannot_mutate_authority(self):
        self.open_keeper();lid=self.reserve();self.fill(lid)
        self.keeper.observer=lambda e:self.keeper.update_authority(replace(self.authority,head=h('other'),sequence=2)) if e=='seal.before_commit' else None
        self.err('REENTRANT_OPERATION',lambda:self.seal(lid));self.keeper.observer=None;self.assertEqual(self.status(lid)['state'],'BYTES_COMPLETE_UNSEALED')
    def test_wall_clock_does_not_drive_expiry(self):
        from unittest.mock import patch
        lid,rc=self.ready()
        with patch('time.time',return_value=10**20):self.assertEqual(self.status(lid)['state'],'RETAINED_ACTIVE')
    def test_opaque_keeper_feeds_new_recipient_without_donor(self):
        import shutil,subprocess,sys,json
        from pathlib import Path
        from par_recovery import Inbox
        lid,rc=self.ready();trusted=self.trusted_file(self.bundle)
        self.db.close();shutil.rmtree(self.root);self.source.unlink()
        # Keeper only receives its own signing key, never the content key or recipient DH key.
        remote=self.k.AuthorizedProvider(self.keeper,lid,self.cap,self.p,self.cs)
        rxroot=Path(self.tmp.name)/'recipient-inbox'
        with Inbox(rxroot,self.bundle.index,self.rpin) as rx:
            rx.pull(remote,limit=2)
        with Inbox(rxroot,self.bundle.index,self.rpin) as rx:
            while rx.missing():rx.pull(remote,limit=32)
            self.assertEqual(rx.status()['state'],'BYTES_COMPLETE')
        worker=Path(__file__).parents[1]/'recovery-closure/recovery_worker.py';out=Path(self.tmp.name)/'recipient-output'
        proc=subprocess.run([sys.executable,'-I','-S',str(worker),'open',str(rxroot),'unused',str(out),str(trusted),'none'],capture_output=True,timeout=20)
        self.assertEqual(proc.returncode,0,proc.stderr.decode());v=json.loads(proc.stdout)
        self.assertFalse(v['applied']);self.assertFalse(v['writable']);self.assertEqual(out.read_bytes(),self.data)
    def test_read_capability_with_other_subject_cannot_manage_lease(self):
        lid,rc=self.ready();other=h('delegate')
        cap=self.k.issue_capability(self.p,self.s.owner,self.authority,self.kp,self.p.sign_public(other),self.rpin.index_id,('get','release'),60,h('delegate-grant'))
        c=self.call('release',lid,cap=cap,seed=other);self.err('LEASE_OWNER',lambda:self.keeper.release(lid,cap,c))
