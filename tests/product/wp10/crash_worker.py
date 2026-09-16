#!/usr/bin/env python3
"""Owned child process; synthetic credentials only; kills ONLY itself at a named seam."""
import os,signal,sys
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True
for p in [R,R/'tests/product/wp10',R/'tests/product/auth-store',R/'tests/product/space-auth']+[p for p in (R/'experiments').iterdir() if p.is_dir()]:sys.path.insert(0,str(p))
from auth_support import Scenario,provider,epoch_bundle,h
from par_auth_store import AuthorityStore
from product.wp10.events import EventJournal

def main():
 base,action,stage=sys.argv[1:];base=Path(base);p=provider();s=Scenario(p);b=epoch_bundle(s);d=s.devices[0]
 with AuthorityStore.open(base/'db',provider=p,allow_unpatched_sqlite=True) as owner:
  owner.activate(s.space,d['cert'],d['secret'],b['packages'][d['id']],b['ids'],b['manifest'],b['seeds'])
  def observer(current):
   if current==stage:os.kill(os.getpid(),signal.SIGKILL)
  with EventJournal.open(base/'events',owner=owner,certificate=d['cert'],sign_seed=d['seed'],local_secret=h('event-local-key'),app_id=s.app,space_id=s.space,stream_id=h('events'),epoch=1,schema={'body':'text','count':'uint64'},allow_legacy_experiment=True,observer=observer) as j:
   if action=='publish':j.publish((2).to_bytes(16,'big'),{'body':'secret-note-2','count':2**63+1})
   elif action=='ack':sub=j.subscribe(b'c'*16);sub.ack(sub.poll().token)
   else:raise ValueError('unknown action')
if __name__=='__main__':main()
