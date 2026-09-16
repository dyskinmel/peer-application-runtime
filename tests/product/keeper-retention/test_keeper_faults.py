from keeper_support import KeeperTest,h,replace,decode,encode
from pathlib import Path
from unittest.mock import patch
import errno,json,os,signal,sqlite3,subprocess,sys

BOUNDARIES={
 'initialize':['initialize.schema','initialize.before_commit','initialize.durable'],
 'reserve':['reserve.begin','reserve.recorded','reserve.before_commit','reserve.after_commit','reserve.ack'],
 'put':['object.written','object.synced','object.published','object.durable','object.ack','put.begin','put.recorded','put.before_commit','put.after_commit','put.ack'],
 'seal':['seal.signed','seal.begin','seal.recorded','seal.before_commit','seal.after_commit','seal.ack'],
 'renew':['renew.signed','renew.begin','renew.recorded','renew.before_commit','renew.after_commit','renew.ack'],
 'release':['release.begin','release.recorded','release.before_commit','release.after_commit','release.ack'],
 'authority':['authority.begin','authority.recorded','authority.before_commit','authority.after_commit','authority.ack']}
class KeeperFaults(KeeperTest):
    def crash_case(self,action,event):
        self.open_keeper();lid=None;call=None;oid=next(iter(self.bundle.objects));rc=None
        if action in ('put','seal','renew','release','authority'):lid=self.reserve()
        if action in ('seal','renew','release'):self.fill(lid)
        if action in ('renew','release'):rc=self.seal(lid)
        if action=='reserve':call=self.call(action,payload=self.k.reserve_payload(self.bundle.index,self.rpin,30),nonce=h('fault-op'))
        elif action=='put':call=self.call(action,lid,self.k.put_payload(oid,self.bundle.objects[oid]),nonce=h('fault-op'))
        elif action in ('seal','release'):call=self.call(action,lid,nonce=h('fault-op'))
        elif action=='renew':call=self.call(action,lid,30,nonce=h('fault-op'))
        self.keeper.close()
        if action=='initialize':
            self.path=Path(self.tmp.name)/'new-keeper'
        j={'root':str(self.path),'seed':self.ks.hex(),'app':self.authority.app,'space':self.authority.space.hex(),'head':self.authority.head.hex(),
           'seq':self.authority.sequence,'epoch':self.authority.epoch,'issuer':self.authority.issuer.hex(),'boot':self.clock.boot.hex(),'ns':self.clock.ns,
           'quota':self.total*3,'kill':event,'marker':str(Path(self.tmp.name)/'marker'),'action':action,'cap':self.cap.hex(),
           'index':self.bundle.index.hex(),'pin':encode(__import__('par_keeper.contract',fromlist=['pin_values']).pin_values(self.rpin)).hex(),
           'call':(call or b'').hex(),'lease':(lid or b'').hex(),'oid':oid.hex(),'raw':self.bundle.objects[oid].hex(),'new_head':h('new-head').hex()}
        jf=Path(self.tmp.name)/'job.json';jf.write_text(json.dumps(j));worker=Path(__file__).with_name('keeper_worker.py')
        r=subprocess.run([sys.executable,'-I','-S',str(worker),str(jf)],capture_output=True,timeout=15)
        self.assertEqual(r.returncode,-signal.SIGKILL,(event,r.stderr.decode()));self.assertEqual(Path(j['marker']).read_text(),event)
        committed=event.endswith('.after_commit') or event.endswith('.ack') or event=='initialize.durable'
        if action=='authority' and committed:self.authority=replace(self.authority,head=h('new-head'),sequence=2)
        self.open_keeper()
        if action=='reserve':
            before=self.keeper.diagnostics()['leases'];self.assertEqual(before,1 if committed else 0)
            lid=self.keeper.reserve(self.bundle.index,self.rpin,30,self.cap,call);self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total)
        elif action=='put':
            # file acknowledgment is not a DB-object acknowledgment.
            dbcommitted=event in ('put.after_commit','put.ack')
            self.assertEqual(self.status(lid)['received'],int(dbcommitted));self.put(lid,oid);self.assertEqual(self.status(lid)['received'],1)
        elif action=='seal':
            self.assertEqual(self.keeper.connection.execute('SELECT generation FROM leases').fetchone()[0],int(committed))
            new=self.keeper.seal(lid,self.cap,call);self.assertEqual(self.keeper.seal(lid,self.cap,call),new)
        elif action=='renew':
            self.assertEqual(self.keeper.connection.execute('SELECT generation FROM leases').fetchone()[0],2 if committed else 1)
            new=self.keeper.renew(lid,30,self.cap,call);self.assertEqual(self.keeper.renew(lid,30,self.cap,call),new)
        elif action=='release':
            self.assertEqual(self.status(lid)['state'],'RELEASED_RETAINED' if committed else 'RETAINED_ACTIVE');self.keeper.release(lid,self.cap,call)
            self.assertEqual(self.status(lid)['state'],'RELEASED_RETAINED');self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],self.total)
        elif action=='authority':
            if committed:self.err('CAPABILITY_SCOPE',lambda:self.status(lid))
            else:self.assertEqual(self.status(lid)['state'],'AWAITING_OBJECTS')
        else:self.assertEqual(self.keeper.diagnostics()['leases'],0)
    def test_real_sqlite_full_does_not_reserve(self):
        self.open_keeper(quota_bytes=self.total*200,max_leases=256);c=self.keeper.connection;c.execute('PRAGMA wal_checkpoint(TRUNCATE)');pages=c.execute('PRAGMA page_count').fetchone()[0];c.execute('PRAGMA max_page_count='+str(pages))
        for _ in range(100):
            before=self.keeper.diagnostics()['leases']
            try:self.reserve()
            except self.k.KeeperError as ex:
                self.assertEqual(ex.code,'SQLITE_FULL');self.assertEqual(self.keeper.diagnostics()['leases'],before)
                self.assertEqual(self.keeper.diagnostics()['reserved_bytes'],before*self.total);break
        else:self.fail('max_page_count did not exercise SQLITE_FULL')
    def test_real_sqlite_writer_contention(self):
        self.open_keeper();c=sqlite3.connect(self.path/'keeper.sqlite',isolation_level=None);c.execute('BEGIN IMMEDIATE')
        try:self.err('SQLITE_BUSY',self.reserve)
        finally:c.execute('ROLLBACK');c.close()
        self.assertEqual(self.keeper.diagnostics()['leases'],0)
    def test_fsync_failure_cannot_ack_put(self):
        self.open_keeper();lid=self.reserve();oid=next(iter(self.bundle.objects))
        from par_recovery.transfer import mkdir
        mkdir(self.path/'objects'/lid.hex())
        with patch('os.fsync',side_effect=OSError(errno.ENOSPC,'synthetic full')):self.err('TRANSFER_IO',lambda:self.put(lid,oid))
        self.assertEqual(self.status(lid)['received'],0)
    def test_receipt_commit_ack_loss_is_queryable(self):
        self.open_keeper();lid=self.reserve();self.fill(lid)
        def stop(e):
            if e=='seal.after_commit':raise OSError('synthetic acknowledgment loss')
        self.keeper.observer=stop;nonce=h('seal-lost');self.err('OUTCOME_UNKNOWN',lambda:self.seal(lid,nonce));self.keeper.observer=None
        a=self.seal(lid,nonce);self.assertEqual(a,self.keeper.receipt(lid,self.cap,self.call('receipt',lid)))
    def test_scope_update_failure_stops_instance(self):
        self.open_keeper();lid=self.reserve()
        def stop(e):
            if e=='authority.before_commit':raise OSError('synthetic write failure')
        self.keeper.observer=stop;self.err('STORAGE_IO',lambda:self.keeper.update_authority(replace(self.authority,head=h('new'),sequence=2)))
        self.keeper.observer=None;self.err('STORAGE_UNCERTAIN',lambda:self.status(lid))
    def test_mutation_operation_budget_rolls_back(self):
        self.open_keeper(max_operations=1);lid=self.reserve();self.fill(lid);self.err('OPERATION_LIMIT',lambda:self.seal(lid));self.assertEqual(self.status(lid)['state'],'BYTES_COMPLETE_UNSEALED')
    def test_no_side_effect_with_bad_possession(self):
        self.open_keeper();lid=self.reserve();oid=next(iter(self.bundle.objects));g=bytearray(self.cap);g[-1]^=1
        self.err('CAPABILITY_AUTH',lambda:self.keeper.put(lid,oid,self.bundle.objects[oid],bytes(g),self.call('put',lid,self.k.put_payload(oid,self.bundle.objects[oid]))))
        self.assertFalse(self.keeper.object_path(lid,oid).exists())

def install_case(action,event):
    def test(self):self.crash_case(action,event)
    test.__name__='test_sigkill_'+event.replace('.','_');test.__doc__='Real owned subprocess kill at '+event
    setattr(KeeperFaults,test.__name__,test)
for _action,_events in BOUNDARIES.items():
    for _event in _events:install_case(_action,_event)
