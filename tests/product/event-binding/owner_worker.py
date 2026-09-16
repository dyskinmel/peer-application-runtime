#!/usr/bin/env python3
"""TEST/DEMO bridge only. Synthetic keys, explicit temporary root, no public listener.

Same process group as its harness parent. One JSON request at a time, fixed
operations, 1 MiB line bound. The adapter does not create this transport itself.
"""
import json,sys,os,signal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+list((ROOT/'experiments').iterdir()):sys.path.insert(0,str(p))
from auth_support import Scenario,provider,epoch_bundle,h
from par_auth_store import AuthorityStore
from product.wp10.events import EventJournal
from product.wp10.sdk import EventOwnerPort

def main():
    base=Path(sys.argv[1]);p=provider();s=Scenario(p);b=epoch_bundle(s);d=s.devices[0]
    if not (base/'db').exists():
        owner=AuthorityStore.create(base/'db',provider=p,allow_unpatched_sqlite=True)
        owner.enroll(s.app,s.space,s.genesis);owner.observe(s.space,b['raw']);owner.provide_membership(s.space,b['pages'])
    else:owner=AuthorityStore.open(base/'db',provider=p,allow_unpatched_sqlite=True)
    owner.activate(s.space,d['cert'],d['secret'],b['packages'][d['id']],b['ids'],b['manifest'],b['seeds'])
    kwargs=dict(owner=owner,certificate=d['cert'],sign_seed=d['seed'],local_secret=h('event-local-key'),app_id=s.app,space_id=s.space,stream_id=h('events'),epoch=1,schema={'body':'text','count':'uint64'},allow_legacy_experiment=True)
    create=not (base/'events').exists();journal=(EventJournal.create if create else EventJournal.open)(base/'events',**kwargs)
    if create:
        for n in (1,2):journal.publish(n.to_bytes(16,'big'),{'body':f'公開試験{n}','count':2**64-1})
    adapter=EventOwnerPort(journal,b'c'*16)
    print(json.dumps({'ready':True,'context':adapter.context(),'pid':os.getpid(),'pgid':os.getpgrp()}),flush=True)
    try:
        while True:
            line=sys.stdin.buffer.readline(1048577)
            if not line:break
            if len(line)>1048576 or not line.endswith(b'\n'):raise ValueError('frame limit')
            req=json.loads(line);rid=req['id'];method=req['method'];params=req.get('params',{})
            try:
                if method=='quit':print(json.dumps({'id':rid,'value':True}),flush=True);break
                elif method=='test_authority_change':
                    raw=s.raw(s.next(b['raw']));owner.observe(s.space,raw);owner.provide_membership(s.space,b['pages']);value=True
                elif method=='test_ack_loss':
                    def lost(stage):
                        if stage=='ack.after_commit':raise OSError('synthetic lost ack')
                    journal.observer=lost;value=True
                elif method=='test_ack_kill':
                    def kill(stage):
                        if stage=='ack.after_commit':os.kill(os.getpid(),signal.SIGKILL)
                    journal.observer=kill;value=True
                elif method in ('open','poll','ack','cursor','cancel','context'):
                    value=getattr(adapter,method)(params) if method!='context' else adapter.context()
                else:raise ValueError('operation not exposed')
                print(json.dumps({'id':rid,'value':value},ensure_ascii=False),flush=True)
            except Exception as e:print(json.dumps({'id':rid,'error':getattr(e,'code','OWNER_FAILURE')}),flush=True)
    finally:journal.close();owner.close()
if __name__=='__main__':main()
