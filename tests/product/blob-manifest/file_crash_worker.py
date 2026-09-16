"""Kill only this owned subprocess after reporting the exact requested boundary."""
from pathlib import Path
import os,signal,sys
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True
for path in ['experiments/blob-manifest','experiments/blob-store','experiments/auth-store','experiments/space-auth','experiments/g0-crypto','experiments/g0-wire','experiments/g0-store','tests/product/space-auth','tests/product/auth-store','tests/product/blob-store']:sys.path.insert(0,str(ROOT/path))
from blob_support import provider,Scenario,epoch_bundle,h,control_id
from par_blob_store import BlobStore
from par_file import FileWriter,export_file
root=Path(sys.argv[1]);action=sys.argv[2];stage=sys.argv[3];source=Path(sys.argv[4]);dest=Path(sys.argv[5])
p=provider();s=Scenario(p);b=epoch_bundle(s);d=s.devices[0]
def kill(here):
    if here==stage:
        print('REACHED:'+stage,flush=True);os.kill(os.getpid(),signal.SIGKILL)
with BlobStore.open(root,provider=p,allow_unpatched_sqlite=True) as db:
    db.reactivate(s.space,d['secret'])
    payload=b'opaque inner change - not an Automerge document';cache=b'candidate materialization not semantically checked'
    header={0:s.app,1:s.space,2:1,3:h('doc'),4:1,5:d['id'],6:h('actor-generation')[:16],7:1,8:None,9:h('schema'),10:[],11:len(payload),12:h('inner-hash'),13:control_id(b['raw']),14:1,15:0}
    op=(1).to_bytes(16,'big');w=FileWriter(db,d['cert'],s.secret,d['seed'],h('local-secret'),observer=kill)
    if action=='stage':w.stage(op,header,payload,cache,source,name='資料.txt',media_type='text/plain')
    elif action=='commit':
        db.observer=kill;w.commit(w.load_staged(op),header,payload,cache)
    elif action=='export':
        eid=db._storage.connection.execute('SELECT commit_id FROM commit_ledger WHERE operation_id=?',(op,)).fetchone()[0]
        export_file(db,eid,s.secret,dest,observer=kill)
    else:raise RuntimeError('unknown action')
raise RuntimeError('requested stage not reached')
