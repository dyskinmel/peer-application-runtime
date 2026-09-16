"""Owned child; inherits harness process group. Public synthetic fixtures only."""
from pathlib import Path
import json,os,signal,sys
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/space-auth']+[p for p in (ROOT/'experiments').iterdir() if p.is_dir()]:sys.path.insert(0,str(p))
from auth_support import provider,Scenario,h
from par_auth_store import AuthorityStore
from product.wp04.inbox import SyncInbox
from par_wire.codec import decode
base=Path(sys.argv[1]);stage=sys.argv[2];p=provider();s=Scenario(p)
with AuthorityStore.open(base/'db',provider=p,allow_unpatched_sqlite=True) as owner:
    owner.reactivate(s.space,s.devices[0]['secret'])
    def kill(phase):
        if phase==stage:
            print(json.dumps({'stage':phase,'pgid':os.getpgrp()}),flush=True)
            os.kill(os.getpid(),signal.SIGKILL)
    box=SyncInbox.open(base/'inbox',owner,app_id=s.app,space_id=s.space,document_id=h('doc'),epoch=1,schema_id=h('schema'),observer=kill)
    raw,cert=decode((base/'receive-input.cbor').read_bytes())
    if stage=='inspect':print(json.dumps(box.inspect(__import__('par_crypto.objects',fromlist=['envelope_id']).envelope_id(raw))),flush=True)
    else:print(json.dumps(box.receive(raw,cert)),flush=True)
    box.close()
