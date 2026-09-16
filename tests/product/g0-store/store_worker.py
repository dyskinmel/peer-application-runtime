"""Test worker only. No code in the store exits processes or manufactures crash outcomes."""
import argparse,hashlib,signal,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
for p in ('experiments/g0-store','experiments/g0-wire'):sys.path.insert(0,str(ROOT/p))
from par_store.store import Store
from par_store.model import PreparedCommit

def h(x):return hashlib.sha256(x.encode()).digest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--cut',required=True);args=ap.parse_args()
    with Store.open(args.root,allow_unpatched_sqlite=True) as s:
        op=(100).to_bytes(16,'big');inp=h('input-100');res=s.reserve_nonce(op,inp,h('key'),(100).to_bytes(24,'big'))
        def barrier(stage):
            if stage==args.cut:
                print('BARRIER '+stage,flush=True)
                # Only the owning test parent sends SIGKILL. This is a pipe-synchronized pause.
                while True:signal.pause()
        s.observer=barrier
        p=PreparedCommit(op,inp,h('space'),h('object'),h('actor'),b'a'*16,1,1,None,h('change-100'),res,
                         b'opaque-child-envelope',b'opaque-child-cache',b'opaque-child-receipt',(h('dep'),),(b'opaque-child-block',))
        s.commit(p,fencing_token=s.fencing_token)
        print('COMMIT_RETURNED',flush=True)
if __name__=='__main__':main()
