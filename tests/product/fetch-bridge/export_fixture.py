"""Real owner observation fixture. Inner payloads are deliberately NOT a CRDT."""
from pathlib import Path
import sys,tempfile,json
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True
for p in[ROOT,ROOT/'tests/product/causal-exchange',ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+[p for p in(ROOT/'experiments').iterdir()if p.is_dir()]:sys.path.insert(0,str(p))
from process_fixture import Peer
from product.wp04.exchange import Source
from par_crypto import objects
from product.wp09.par_secure_transport import PeerBinding
from product.wp09.par_secure_fetch import FetchPlan
from product.runtime_read.fetch import FetchApplicationController

def export():
    with tempfile.TemporaryDirectory()as temp:
        remote=Peer(Path(temp)/'remote');local=Peer(Path(temp)/'local')
        try:
            a,b=remote.chain()
            for row in(a,b):remote.box.receive(*row)
            local.box.receive(*b);d=local.s.devices[1];local.source=Source(local.box,d['cert'],d['seed'])
            token,ds,_=remote.source.catalog(d['cert']);binding=PeerBinding('provider',remote.s.devices[0]['cert'],local.source.scope,'a'*64,9)
            plan=FetchPlan(local.source.scope,token,ds,binding,local.box.pin()['generation'])
            controller=FetchApplicationController(plan,local.source,[objects.envelope_id(b[0])],lambda:9)
            waiting=controller.observe();local.box.receive(*a);ready=controller.observe();blocked=controller.validate(expected_revision=ready['revision'])
            return dict(pin=controller.pin(),waiting=waiting,ready=ready,blocked=blocked)
        finally:local.close();remote.close()
if __name__=='__main__':print(json.dumps(export()))
