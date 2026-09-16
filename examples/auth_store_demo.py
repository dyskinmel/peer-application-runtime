#!/usr/bin/env python3
"""Disposable synthetic demo. All fixture keys are public test data, never real identities."""
from pathlib import Path
import json,sys,tempfile
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for p in [ROOT/'tests/product/space-auth',ROOT/'experiments/space-auth',ROOT/'experiments/g0-wire',ROOT/'experiments/g0-crypto',ROOT/'experiments/g0-store',ROOT/'experiments/auth-store']:sys.path.insert(0,str(p))
# Test-only fixture construction is deliberately reused by this developer demo.
from auth_support import Scenario,provider,epoch_bundle,h,control_id
from par_auth_store import AuthorityStore,AuthenticatedWriter
from par_store.errors import StoreError

def main():
    p=provider();s=Scenario(p);b=epoch_bundle(s);d=s.devices[0]
    with tempfile.TemporaryDirectory(prefix='par-auth-store-demo-') as temp:
        root=Path(temp)
        with AuthorityStore.create(root/'data',provider=p,allow_unpatched_sqlite=True) as db:
            db.enroll(s.app,s.space,s.genesis);db.observe(s.space,b['raw']);db.provide_membership(s.space,b['pages'])
            db.activate(s.space,d['cert'],d['secret'],b['packages'][d['id']],b['ids'],b['manifest'],b['seeds'])
            w=AuthenticatedWriter(db,d['cert'],s.secret,d['seed'],h('demo-local-key'))
            payload=b'opaque inner change, not Automerge';cache=b'opaque candidate cache'
            header={0:s.app,1:s.space,2:1,3:h('demo-doc'),4:1,5:d['id'],6:h('demo-actor')[:16],7:1,8:None,9:h('schema'),10:[],11:len(payload),12:h('inner-hash'),13:control_id(b['raw']),14:1,15:0}
            op=h('demo-op')[:16];receipt=w.write(op,header,payload,cache)
            same=w.write(op,header,payload,cache)==receipt
            stale_header=dict(header);stale_header[7]=2;stale_header[8]=receipt.envelope_id
            candidate=w.prepare(h('demo-stale')[:16],stale_header,payload,cache)
            db.observe(s.space,s.raw(s.next(b['raw'])))
            try:db.commit(candidate)
            except StoreError as exc:rejection=exc.code
            else:raise AssertionError('stale candidate was accepted')
            db.provide_membership(s.space,b['pages'])
            db.export_snapshot(root/'backup')
            initial_audit=db.audit()['valid']
        AuthorityStore.restore_snapshot(root/'backup',root/'restore',provider=p,allow_unpatched_sqlite=True)
        with AuthorityStore.open(root/'restore',provider=p,allow_unpatched_sqlite=True) as restored:
            status=restored.status(s.space);audit=restored.audit()['valid']
        result={'scope':'SYNTHETIC_LOCAL_EXPERIMENT','exact_retry':same,'stale_commit_error':rejection,'source_audit':initial_audit,'restored_audit':audit,'restored_read_only':status['restore_read_only'],'inner_applied':False,'production_qualified':False}
        print(json.dumps(result,indent=2));return 0 if same and rejection=='STALE_DECISION' and initial_audit and audit and status['restore_read_only'] else 1
if __name__=='__main__':raise SystemExit(main())
