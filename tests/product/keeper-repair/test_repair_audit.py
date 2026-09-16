import os,sqlite3,shutil,subprocess,sys,json
from pathlib import Path
from unittest.mock import patch
from repair_support import RepairTest,h,replace
from par_keeper.contract import split
from par_keeper_gc import KeeperGC
from par_keeper_repair.filesystem import job_path

class RepairAudit(RepairTest):
    def test_completed_result_alteration_rejected(self):
        lid,_=self.ready();req=self.repair_request(lid);self.repair(lid,req)
        self.keeper.connection.execute("UPDATE repair_jobs SET result=x'00'");self.err('CORRUPT_REPAIR',lambda:self.repair(lid,req))
    def test_intent_alteration_rejected_on_reopen(self):
        lid,_=self.ready();self.keeper.mark_repair(lid,self.cap,self.repair_request(lid));self.keeper.connection.execute("UPDATE repair_jobs SET intent=x'00'")
        self.keeper.close();self.err('CORRUPT_REPAIR',self.open_keeper)
    def test_reappeared_stage_of_completed_job_rejected(self):
        lid,_=self.ready();req=self.repair_request(lid);self.repair(lid,req);jid=self.r.contract.job_id(split(req)[0]);job_path(self.path,jid).mkdir()
        self.err('CORRUPT_REPAIR',self.keeper.diagnostics)
    def test_unknown_stage_not_deleted(self):
        lid,_=self.ready();p=self.path/'repair-staging'/'not-owned';p.mkdir();(p/'keep').write_text('preserve')
        self.err('REPAIR_UNKNOWN_FILE',self.keeper.diagnostics);self.assertTrue((p/'keep').exists())
    def test_unlisted_stage_file_blocks_cancel(self):
        lid,_=self.ready();job=self.keeper.mark_repair(lid,self.cap,self.repair_request(lid))['job_id'];d=job_path(self.path,job);d.mkdir();(d/'alien').write_text('keep')
        self.err('CORRUPT_REPAIR',lambda:self.keeper.cancel_repair(lid,self.cap,self.cancel_request(lid,job)));self.assertTrue((d/'alien').exists())
    def test_symlink_target_rejected(self):
        lid,_=self.ready();oid=self.damage(lid);p=self.keeper.object_path(lid,oid);q=Path(self.tmp.name)/'other';q.write_bytes(b'preserve');p.symlink_to(q)
        self.err(None,lambda:self.repair(lid,self.repair_request(lid,[oid])));self.assertEqual(q.read_bytes(),b'preserve')
    def test_hardlink_target_rejected(self):
        lid,_=self.ready();oid=sorted(self.bundle.objects)[0];p=self.keeper.object_path(lid,oid);q=Path(self.tmp.name)/'linked';os.link(p,q)
        self.err('REPAIR_UNSAFE_FILE',lambda:self.repair(lid,self.repair_request(lid,[oid])));self.assertEqual(q.read_bytes(),self.bundle.objects[oid])
    def test_directory_target_rejected(self):
        lid,_=self.ready();oid=self.damage(lid);self.keeper.object_path(lid,oid).mkdir();self.err('REPAIR_UNSAFE_FILE',lambda:self.repair(lid,self.repair_request(lid,[oid])))
    def test_owner_required_even_with_put_capability(self):
        lid,_=self.ready();seed=h('other-owner');cap=self.k.issue_capability(self.p,self.s.owner,self.authority,self.kp,self.p.sign_public(seed),self.rpin.index_id,('put',),60,h('other-cap'))
        req=self.repair_request(lid,cap=cap,seed=seed);self.err('LEASE_OWNER',lambda:self.repair(lid,req,cap=cap))
    def test_pending_renew_rejected(self):
        lid,_=self.ready();self.keeper.mark_repair(lid,self.cap,self.repair_request(lid));self.err('REPAIR_PENDING',lambda:self.renew(lid))
    def test_current_grant_can_cancel_old_authority_job(self):
        lid,_=self.ready();job=self.keeper.mark_repair(lid,self.cap,self.repair_request(lid))['job_id'];self.authority=replace(self.authority,sequence=2,head=h('updated'));self.keeper.update_authority(self.authority)
        cap=self.k.issue_capability(self.p,self.s.owner,self.authority,self.kp,self.cp,self.rpin.index_id,('release',),60,h('current-cap'))
        self.keeper.cancel_repair(lid,cap,self.cancel_request(lid,job,cap));self.reopen();self.assertEqual(self.keeper.diagnostics()['repair_pending'],0)
    def test_cancel_does_not_undo_valid_published_bytes(self):
        lid,_=self.ready();oid=self.damage(lid);req=self.repair_request(lid,[oid])
        def observe(e):
            if e=='repair_file.durable':raise OSError('interrupted')
        self.keeper.observer=observe;self.err('STORAGE_IO',lambda:self.repair(lid,req));self.keeper.observer=None
        jid=self.r.contract.job_id(split(req)[0]);self.keeper.cancel_repair(lid,self.cap,self.cancel_request(lid,jid));self.assertEqual(self.get(lid,oid),self.bundle.objects[oid])
    def test_cancelled_job_cannot_resume(self):
        lid,_=self.ready();req=self.repair_request(lid);jid=self.keeper.mark_repair(lid,self.cap,req)['job_id'];self.keeper.cancel_repair(lid,self.cap,self.cancel_request(lid,jid));self.err('REPAIR_ABORTED',lambda:self.repair(lid,req))
    def test_cancel_complete_job_rejected(self):
        lid,_=self.ready();req=self.repair_request(lid);self.repair(lid,req);jid=self.r.contract.job_id(split(req)[0]);self.err('REPAIR_ALREADY_DONE',lambda:self.keeper.cancel_repair(lid,self.cap,self.cancel_request(lid,jid)))
    def test_audit_job_limit_enforced(self):
        lid,_=self.ready();self.repair(lid,self.repair_request(lid))
        with patch('par_keeper_repair.store.MAX_JOBS',1):self.err('REPAIR_LIMIT',lambda:self.repair(lid,self.repair_request(lid)))
    def test_separate_staging_budget(self):
        lid,_=self.ready();req=self.repair_request(lid);oid=split(req)[0][8][0]
        with patch('par_keeper_repair.store.MAX_STAGING',len(self.bundle.objects[oid])-1):self.err('REPAIR_STAGING_CAPACITY',lambda:self.repair(lid,req))
        self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total)
    def test_v2_requires_explicit_migration(self):
        self.keeper=KeeperGC(self.path,self.p,self.ks,self.authority,quota_bytes=self.total*3,clock=self.clock,allow_unpatched_sqlite=True);self.keeper.close();self.err('SCHEMA_MISMATCH',self.open_keeper)
    def test_v2_nonempty_migrates_then_repairs(self):
        self.keeper=KeeperGC(self.path,self.p,self.ks,self.authority,quota_bytes=self.total*3,clock=self.clock,allow_unpatched_sqlite=True)
        lid=self.reserve();self.fill(lid);rc=self.seal(lid);oid=self.damage(lid);self.keeper.close();self.open_keeper(migrate_v2=True)
        self.repair(lid,self.repair_request(lid,[oid]));self.assertEqual(self.keeper.connection.execute('PRAGMA user_version').fetchone()[0],3);self.assertEqual(self.keeper._lease(lid)['receipt'],rc)
    def test_schema_tampering_rejected(self):
        self.open_keeper();self.keeper.connection.execute('CREATE TABLE extra (id INTEGER)');self.keeper.close();self.err('SCHEMA_MISMATCH',self.open_keeper)
    def test_result_bound_to_expected_request(self):
        lid,_=self.ready();req=self.repair_request(lid);r=self.repair(lid,req);self.err('REPAIR_SCOPE',lambda:self.r.verify_result(self.p,r,self.kp,expected_request=self.repair_request(lid)))
    def test_repaired_objects_feed_new_recipient_without_donor(self):
        from par_recovery import Inbox
        lid,_=self.ready();oids=sorted(self.bundle.objects)[:3]
        for oid in oids:self.damage(lid,'corrupt',oid)
        trusted=self.trusted_file(self.bundle);self.db.close();shutil.rmtree(self.root);self.source.unlink()
        self.repair(lid,self.repair_request(lid,oids));self.reopen()
        remote=self.k.AuthorizedProvider(self.keeper,lid,self.cap,self.p,self.cs);rxroot=Path(self.tmp.name)/'inbox'
        with Inbox(rxroot,self.bundle.index,self.rpin) as rx:
            while rx.missing():rx.pull(remote,limit=32)
        worker=Path(__file__).parents[1]/'recovery-closure/recovery_worker.py';out=Path(self.tmp.name)/'out'
        r=subprocess.run([sys.executable,'-I','-S',str(worker),'open',str(rxroot),'unused',str(out),str(trusted),'none'],capture_output=True,timeout=20)
        self.assertEqual(r.returncode,0,r.stderr.decode());self.assertEqual(out.read_bytes(),self.data);v=json.loads(r.stdout);self.assertFalse(v['applied']);self.assertFalse(v['writable'])
    def test_stage_changed_after_validation_does_not_replace_target(self):
        lid,_=self.ready();oid=self.damage(lid,'corrupt');req=self.repair_request(lid,[oid]);original=self.keeper.object_path(lid,oid).read_bytes()
        def observe(e):
            if e=='repair_file.before_replace':
                jid=self.r.contract.job_id(split(req)[0]);(job_path(self.path,jid)/(oid.hex()+'.part')).write_bytes(b'changed')
        self.keeper.observer=observe;self.err('OBJECT_HASH',lambda:self.repair(lid,req));self.keeper.observer=None
        self.assertEqual(self.keeper.object_path(lid,oid).read_bytes(),original)

    def test_v2_gc_tombstone_survives_migration(self):
        self.keeper=KeeperGC(self.path,self.p,self.ks,self.authority,quota_bytes=self.total*3,clock=self.clock,allow_unpatched_sqlite=True)
        lid=self.reserve();self.fill(lid);self.seal(lid);self.release(lid);req=self.gc_request(lid);rc=self.gc(lid,req);self.keeper.close();self.open_keeper(migrate_v2=True)
        self.assertEqual(rc,self.gc(lid,req));self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],len(self.bundle.index))
    def test_nonboolean_migration_rejected(self):self.err('CONTRACT_SCHEMA',lambda:self.open_keeper(migrate_v2=1))
    def test_result_signature_tampering_rejected(self):
        lid,_=self.ready();result=self.repair(lid,self.repair_request(lid));wrong=result[:-1]+bytes([result[-1]^1]);self.err('REPAIR_SIGNATURE',lambda:self.r.verify_result(self.p,wrong,self.kp))
    def test_released_damaged_bytes_not_implicitly_destroyed(self):
        lid,_=self.ready();oid=self.damage(lid,'corrupt');self.release(lid)
        self.err('LEASE_RELEASED',lambda:self.repair(lid,self.repair_request(lid,[oid])));self.err('OBJECT_HASH',lambda:self.gc(lid,self.gc_request(lid)))
        self.assertTrue(self.keeper.object_path(lid,oid).exists())
    def test_stage_symlink_is_not_followed(self):
        lid,_=self.ready();oid=self.damage(lid);req=self.repair_request(lid,[oid]);jid=self.keeper.mark_repair(lid,self.cap,req)['job_id'];d=job_path(self.path,jid);d.mkdir()
        other=Path(self.tmp.name)/'unrelated';other.write_bytes(b'keep');(d/(oid.hex()+'.part')).symlink_to(other)
        self.err('CORRUPT_REPAIR',lambda:self.repair(lid,req));self.assertEqual(other.read_bytes(),b'keep')
    def test_postrepair_gc_keeps_historical_observation(self):
        lid,_=self.ready();req=self.repair_request(lid);rc=self.repair(lid,req);self.release(lid);self.gc(lid,self.gc_request(lid));self.reopen()
        self.assertEqual(self.keeper._repair_job(self.r.contract.job_id(split(req)[0]))['result'],rc);self.assertEqual(self.status(lid)['state'],'RECLAIMED')
