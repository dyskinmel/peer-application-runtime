import errno,hashlib
from window_support import WindowTest,h,pr
class WindowHardening(WindowTest):
    def test_payload_capacity_rejection_does_not_leave_binding(self):
        self.window.close();self.wroot=self.path/'payload-small'
        self.window=self.w.ReplaySpool(self.keeper,self.wroot,self.store_id,max_bytes=len(self.bundle.index));self.window.open_window(self.grant)
        self.upload_stage();before=set(self.window.bindings.iterdir());self.err('STAGING_CAPACITY',self.upload_stage)
        self.assertEqual(set(self.window.bindings.iterdir()),before)
    def test_archive_capacity_reserved_before_acknowledging_begin(self):
        self.window.close();self.wroot=self.path/'archive-small'
        self.window=self.w.ReplaySpool(self.keeper,self.wroot,self.store_id,max_archive_bytes=10000);self.window.open_window(self.grant)
        self.err('ARCHIVE_CAPACITY',self.upload_stage);self.assertEqual(self.window.diagnostics()['records'],0)
    def test_sealed_lease_rejects_new_binding(self):
        _,lid=self.complete_index()
        for oid in self.bundle.objects:self.put(lid,oid)
        self.seal(lid);oid=sorted(self.bundle.objects)[0];raw=self.bundle.objects[oid]
        call=self.call('put',lid,self.k.put_payload(oid,raw));req=self.cmd('begin',['object',oid,len(raw),hashlib.sha256(raw).digest()],lid,call)
        before=set(self.window.bindings.iterdir());self.err('NOT_UPLOADING',lambda:self.execute(req));self.assertEqual(set(self.window.bindings.iterdir()),before)
    def binding_only(self):
        self.beginraw=self.cmd('begin',['index',self.rpin.index_id,len(self.bundle.index),hashlib.sha256(self.bundle.index).digest()]);raw=self.wrap(self.beginraw)
        def stop(e):
            if e=='window.bind.after_sync':raise OSError(errno.EIO,'synthetic ack loss')
        self.window.observer=stop;self.err('OUTCOME_UNKNOWN',lambda:self.window.execute(raw));self.reopen_window()
        return pr.token_for(self.p,self.beginraw)
    def test_binding_only_can_retire_with_current_authority(self):
        self.binding_only();self.change_authority();self.retire_stage();self.finish();self.assertEqual(self.window.diagnostics()['records'],0)
    def test_binding_only_retirement_requires_current_grant(self):
        self.binding_only();old=self.wrap(self.retirement_request(),'retire');self.change_authority()
        self.err('STALE_AUTHORITY',lambda:self.window.execute(old));self.assertFalse(list(self.window.live.glob('*.part')))
    def test_binding_only_retirement_never_mutates_keeper(self):
        self.binding_only();before=list(self.keeper.connection.iterdump());self.retire_stage();self.finish();self.assertEqual(list(self.keeper.connection.iterdump()),before)
    def test_old_window_id_cannot_be_renamed_without_subject_resigning(self):
        self.terminal();old=self.beginwrapped;self.next_window()
        from par_upload_window import contract as c
        b,o=c.unpack(old);b[2]=c.digest(self.grant);o[0]=c.dump(b)
        self.err('WINDOW_SIGNATURE',lambda:self.window.execute(c.dump(o)))
    def test_valid_large_audit_container_exceeds_single_wire_frame(self):
        # A synthetic signed audit of many distinct terminal stages, not network I/O.
        from par_upload_window import contract as c
        from par_keeper_upload_retire import contract as r
        self.terminal();a,_=self.proposed();body=c.check_archive(self.p,a,self.grant)
        prototype={e[0].rsplit('.',1)[1]:e[5] for e in body[5]};origin=pr.check_command(self.p,self.beginraw)
        entries=[]
        for i in range(600):
            begin=pr.make_command(self.p,self.cs,origin[4],'begin',h('archive-'+str(i)),None,None,origin[7])
            token=pr.token_for(self.p,begin);bound=self.wrap(begin)
            meta=pr.load(prototype['cbor'],c.MAX_CONTROL);meta[1]=token;meta[2]=begin;meta_raw=pr.dump(meta,c.MAX_CONTROL)
            grant=r.issue_grant(self.p,self.s.owner,self.authority,self.kp,begin,h('grant-'+str(i)))
            req=r.make_request(self.p,self.cs,grant,h('ret-'+str(i)))
            j=r.verified(self.p,prototype['retirement'],'journal',self.kp);j[3]=token;j[4]=r.digest(meta_raw);j[5]=[req]
            receipt={0:1,1:r.PROFILE,2:self.kp,3:token,4:r.digest(req),5:j[8],6:j[7][2],7:'TOMBSTONED',8:False,9:False,10:False}
            j[9]=r.signed(self.p,self.ks,'receipt',receipt);jr=r.signed(self.p,self.ks,'journal',j)
            for directory,ext,raw in [('bindings','bound',bound),('live','cbor',meta_raw),('live','retirement',jr)]:
                entries.append([directory+'/'+token.hex()+'.'+ext,len(raw),hashlib.sha256(raw).digest(),1,i+1,raw])
        body[5]=sorted(entries);body[6]=600;raw=c.sign_archive(self.p,self.ks,body)
        self.assertGreater(len(raw),1048576);self.assertLess(len(raw),c.MAX_ARCHIVE)
        verified=c.check_archive(self.p,raw,self.grant);self.assertEqual(verified[6],600);self.assertEqual(verified[5],body[5])

    def test_archive_sequence_boolean_is_not_integer(self):
        from par_upload_window import contract as c
        self.terminal();a,_=self.proposed();body=c.check_archive(self.p,a,self.grant);body[4]=True
        self.err(None,lambda:c.check_archive(self.p,c.sign_archive(self.p,self.ks,body),self.grant))
    def test_cleaned_receipt_flags_require_actual_false(self):
        from par_upload_window import contract as c
        self.terminal();self.finish();p=self.wroot/'STATE.cbor'
        state=c.verified(self.p,p.read_bytes(),'state',self.kp)
        receipt=c.verified(self.p,state[4][-1][4],'cleaned',self.kp);receipt[6]=0
        state[4][-1][4]=c.signed(self.p,self.ks,'cleaned',receipt)
        self.window.close();p.write_bytes(c.signed(self.p,self.ks,'state',state))
        self.err(None,self.reopen_window)
