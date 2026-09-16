#!/usr/bin/env python3
"""Synthetic, disposable demo: receive encrypted chunk -> authorize -> store -> restore."""
from pathlib import Path
import sys,tempfile,json
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for path in ['experiments/blob-store','experiments/auth-store','experiments/space-auth','experiments/g0-crypto','experiments/g0-wire','experiments/g0-store','tests/product/space-auth','tests/product/auth-store']:sys.path.insert(0,str(ROOT/path))
from auth_store_support import provider,Scenario,epoch_bundle,h,control_id
from par_crypto import objects
from par_wire.codec import encode
from par_blob_store import BlobStore,BlobWriter,IncomingQueue,Attachment

def main():
    p=provider();s=Scenario(p);b=epoch_bundle(s);d=s.devices[0]
    plain=b'public synthetic attachment';payload=b'opaque candidate - not Automerge';cache=b'synthetic cache'
    bh={0:s.app,1:s.space,2:1,3:h('demo-blob'),4:3,5:0,6:0,7:len(plain)}
    # Fixed public key/nonce solely for this deterministic disposable demonstration.
    raw=objects.seal_block(p,s.secret,bh,plain,b'\1'*24);typed=objects.block_id(raw)
    header={0:s.app,1:s.space,2:1,3:h('doc'),4:1,5:d['id'],6:h('demo-actor')[:16],7:1,8:None,9:h('schema'),10:[],11:len(payload),12:h('inner-hash'),13:control_id(b['raw']),14:1,15:0}
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        with IncomingQueue.create(root/'incoming') as q:
            token=q.begin(typed,encode(bh),len(raw));q.append(token,0,raw[:17])
        with IncomingQueue.open(root/'incoming') as q:
            offset=q.status(token)['acknowledged_bytes'];q.append(token,offset,raw[offset:]);attachment=q.finish(token,p,s.secret,app=s.app,space=s.space,epoch=1)
            with BlobStore.create(root/'db',provider=p,allow_unpatched_sqlite=True) as db:
                db.enroll(s.app,s.space,s.genesis);db.observe(s.space,b['raw']);db.provide_membership(s.space,b['pages']);db.activate(s.space,d['cert'],d['secret'],b['packages'][d['id']],b['ids'],b['manifest'],b['seeds'])
                w=BlobWriter(db,d['cert'],s.secret,d['seed'],h('local-secret'));args=(b'\1'*16,header,payload,cache)
                r=w.write(*args,attachments=(attachment,));assert r==w.write(*args,attachments=(attachment,));assert db.read_attachment(r.envelope_id,0,s.secret)==plain
                q.discard(token);db.export_snapshot(root/'snapshot');audit=db.audit()
            BlobStore.restore_snapshot(root/'snapshot',root/'restored',provider=p,allow_unpatched_sqlite=True)
            with BlobStore.open(root/'restored',provider=p,allow_unpatched_sqlite=True) as restored:
                assert restored.read_attachment(r.envelope_id,0,s.secret)==plain
                result={'result':'PASS','source_data':'PUBLIC_SYNTHETIC_ONLY','resumed_at_bytes':offset,'same_receipt_retry':True,'typed_id':typed.hex(),'restored_read_only':restored._storage.restore_read_only,'local_audit':audit,'whole_file_validated':False,'automerge_applied':False,'production_qualified':False}
    print(json.dumps(result,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
