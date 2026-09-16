"""Synthetic fixture process only; product payloads use inherited socket FD 3.
No requests or commands on stdin/stdout. No public listener. Same process group.
"""
from pathlib import Path
import asyncio,json,os,signal,socket,sys,threading
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+list((ROOT/'experiments').iterdir()):sys.path.insert(0,str(p))
from auth_support import Scenario,provider,epoch_bundle,h
from par_auth_store import AuthorityStore
from product.wp10.events import EventJournal
from product.wp10.sdk import EventOwnerPort
from product.wp10.host import EventHost
from product.wp10.transport import serve_connected

async def main():
    root=Path(sys.argv[1]);mode=sys.argv[2];p=provider();s=Scenario(p);b=epoch_bundle(s);d=s.devices[0]
    if not (root/'db').exists():
        owner=AuthorityStore.create(root/'db',provider=p,allow_unpatched_sqlite=True)
        owner.enroll(s.app,s.space,s.genesis);owner.observe(s.space,b['raw']);owner.provide_membership(s.space,b['pages'])
    else: owner=AuthorityStore.open(root/'db',provider=p,allow_unpatched_sqlite=True)
    owner.activate(s.space,d['cert'],d['secret'],b['packages'][d['id']],b['ids'],b['manifest'],b['seeds'])
    kw=dict(owner=owner,certificate=d['cert'],sign_seed=d['seed'],local_secret=h('event-local-key'),app_id=s.app,space_id=s.space,stream_id=h('events'),epoch=1,schema={'body':'text','count':'uint64'},allow_legacy_experiment=True)
    j=(EventJournal.open if (root/'events').exists() else EventJournal.create)(root/'events',**kw)
    if mode in ('existing','ack-kill','revoke-before-ack') and j.inspect()['events']==0:j.publish(b'o'*16,{'body':'persistent event','count':2**64-1})
    hst=EventHost(j,heartbeat_seconds=.02,wait_seconds=.5)
    threads=set()
    def watch(stage):
        threads.add(threading.get_ident())
        if mode=='ack-kill' and stage=='ack.after_commit':os.kill(os.getpid(),signal.SIGKILL)
        if mode=='revoke-before-ack' and stage=='ack.before_commit':
            owner.observe(s.space,s.raw(s.next(b['raw'])));owner.provide_membership(s.space,b['pages'])
    j.observer=watch
    sock=socket.socket(fileno=3)
    print(json.dumps({'ready':True,'context':EventOwnerPort(j,b'c'*16).context(),'socket_family':sock.family,'pid':os.getpid(),'pgid':os.getpgrp(),'owner_thread':threading.get_ident()}),flush=True)
    async def fixture_action():
        if mode not in ('publish-on-wait','revoke-on-wait'):return
        for _ in range(1000):
            if hst.stats()['waiters']:
                if mode=='publish-on-wait':hst.publish(b'p'*16,{'body':'created after wait registered','count':2**64-1})
                else:owner.observe(s.space,s.raw(s.next(b['raw'])));owner.provide_membership(s.space,b['pages']);hst.notify()
                return
            await asyncio.sleep(.005)
        raise RuntimeError('test fixture never observed a wait')
    action=asyncio.create_task(fixture_action())
    try:await serve_connected(hst,sock,b'c'*16,read_timeout=3,write_timeout=2)
    finally:
        action.cancel();await asyncio.gather(action,return_exceptions=True)
        hst.close();stats=hst.stats();j.close();owner.close()
        print(json.dumps({'ended':True,'stats':stats,'storage_threads':list(threads)}),flush=True)
if __name__=='__main__':asyncio.run(main())
