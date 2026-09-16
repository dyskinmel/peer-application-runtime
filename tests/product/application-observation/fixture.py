"""Emit real-Store observations. The materializer is an explicit test double.
The actual-kind fixture only tests the trusted-port boundary, NOT actual CRDT.
"""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/document-apply',ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+[p for p in (ROOT/'experiments').iterdir() if p.is_dir()]:sys.path.insert(0,str(p))
from apply_support import ApplyTest
from product.runtime_read.application import ApplicationObserver

def scenario(simulate_actual_kind=False):
    t=ApplyTest();t.setUp()
    try:
        if simulate_actual_kind:t.port.identity['kind']='automerge'
        o=ApplicationObserver(t.a,expected_engine=t.port.identity if simulate_actual_kind else None)
        pin=o.pin();empty=o.observe()
        eid,_=t.saved();t.call([eid])
        recorded=o.observe((10).to_bytes(16,'big'))
        unknown=o.observe(b'?'*16)
        refreshed=o.observe((10).to_bytes(16,'big'))
        return dict(pin=pin,empty=empty,recorded=recorded,unknown=unknown,refreshed=refreshed)
    finally:t.doCleanups()
if __name__=='__main__':print(json.dumps({'scope':'EXPLICIT_SIMULATED_SEMANTICS_REAL_STORE','candidate':scenario(),'simulated':scenario(True)}))
