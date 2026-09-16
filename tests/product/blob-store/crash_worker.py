"""Kill only this owned child after recording an exact reached stage."""
from pathlib import Path
import os,signal,sys
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True
for path in ['experiments/blob-store','experiments/auth-store','experiments/space-auth','experiments/g0-crypto','experiments/g0-wire','experiments/g0-store','tests/product/space-auth','tests/product/auth-store','tests/product/blob-store']:sys.path.insert(0,str(ROOT/path))
from blob_support import provider,Scenario,epoch_bundle,h,control_id,encode,objects
from par_blob_store import BlobStore,BlobWriter,Attachment,IncomingQueue
root=Path(sys.argv[1]);action=sys.argv[2];stage=sys.argv[3]
p=provider();s=Scenario(p);b=epoch_bundle(s)
seen_stages={}
def kill(here):
    seen_stages[here]=seen_stages.get(here,0)+1
    base,_,count=stage.partition('#')
    if here==base and seen_stages[here]==(int(count) if count else 1):
        print('REACHED:'+stage,flush=True);os.kill(os.getpid(),signal.SIGKILL)
if action=='migration':BlobStore.migrate_v2(root,provider=p,allow_unpatched_sqlite=True,observer=kill).close()
elif action=='incoming':
    q=IncomingQueue.open(root,observer=kill);token=sys.argv[4]
    bh={0:s.app,1:s.space,2:1,3:h('blob-object'),4:3,5:0,6:0,7:20}
    raw=objects.seal_block(p,s.secret,bh,b'synthetic attachment',(1).to_bytes(24,'big'))
    q.append(token,0,raw);q.close()
elif action=='discard':
    q=IncomingQueue.open(root,observer=kill);q.discard(sys.argv[4]);q.close()
else:
    db=BlobStore.open(root,provider=p,allow_unpatched_sqlite=True);db.reactivate(s.space,s.devices[0]['secret']);db.observer=kill
    if action=='backup':db.export_snapshot(Path(sys.argv[4]))
    else:
        payload=b'opaque inner change - not an Automerge document';cache=b'candidate materialization not semantically checked';d=s.devices[0]
        header={0:s.app,1:s.space,2:1,3:h('doc'),4:1,5:d['id'],6:h('actor-generation')[:16],7:1,8:None,9:h('schema'),10:[],11:len(payload),12:h('inner-hash'),13:control_id(b['raw']),14:1,15:0}
        bh={0:s.app,1:s.space,2:1,3:h('blob-object'),4:3,5:0,6:0,7:20};raw=objects.seal_block(p,s.secret,bh,b'synthetic attachment',(1).to_bytes(24,'big'));a=Attachment(objects.block_id(raw),encode(bh),raw)
        attachments=[a]
        if action=='write_multi':
            for index in (1,2):
                bh[5]=index;raw=objects.seal_block(p,s.secret,bh,b'synthetic attachment',(index+1).to_bytes(24,'big'));attachments.append(Attachment(objects.block_id(raw),encode(bh),raw))
        BlobWriter(db,d['cert'],s.secret,d['seed'],h('local-secret'),observer=kill).write((1).to_bytes(16,'big'),header,payload,cache,attachments=tuple(attachments))
    db.close()
raise RuntimeError('requested crash stage not reached')
