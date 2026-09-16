"""Synthetic test owner; commands use fd3, subscriptions fd4, never stdout.

No external keys/DBs/network. All children retain their harness process group.
Fault modes are fixture-only observer actions, never a product command opcode.
"""
from pathlib import Path
import asyncio,json,os,signal,socket,sys,threading
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+list((ROOT/'experiments').iterdir()):sys.path.insert(0,str(p))
from auth_support import Scenario,provider,epoch_bundle,h
from par_auth_store import AuthorityStore
from product.wp10.events import EventJournal,EventError
from product.wp10.sdk import EventOwnerPort
from product.wp10.host import EventHost
from product.wp10.commands import EventCommandHost
from product.wp10.transport import serve_connected
from product.wp10.command_transport import serve_commands_connected

async def main():
    root=Path(sys.argv[1]);mode=sys.argv[2];p=provider();s=Scenario(p);b=epoch_bundle(s)
    d=s.devices[1] if mode=='reader' else s.devices[0]
    if not (root/'db').exists():
        owner=AuthorityStore.create(root/'db',provider=p,allow_unpatched_sqlite=True)
        owner.enroll(s.app,s.space,s.genesis);owner.observe(s.space,b['raw']);owner.provide_membership(s.space,b['pages'])
    else:owner=AuthorityStore.open(root/'db',provider=p,allow_unpatched_sqlite=True)
    owner.activate(s.space,d['cert'],d['secret'],b['packages'][d['id']],b['ids'],b['manifest'],b['seeds'])
    kw=dict(owner=owner,certificate=d['cert'],sign_seed=d['seed'],local_secret=h('event-local-key'),app_id=s.app,space_id=s.space,stream_id=h('events'),epoch=1,
            schema={'body':'text','count':'uint64','delta':'int64','data':'bytes','ok':'bool'},allow_legacy_experiment=True)
    journal=(EventJournal.open if (root/'events').exists() else EventJournal.create)(root/'events',**kw)
    host=EventHost(journal,heartbeat_seconds=.02,wait_seconds=.5)
    commands=EventCommandHost(host)
    grant=mode!='inquire-only';preview=commands.attach(allow_publish=grant)
    command_context=commands.context(preview);commands.detach(preview)
    sub_context=EventOwnerPort(journal,b'c'*16).context()
    threads=set()
    def observe(stage):
        threads.add(threading.get_ident())
        if (mode=='kill-nonce' and stage=='nonce.after_commit' or
            mode=='kill-commit' and stage=='event.after_commit' or
            mode=='kill-before-commit' and stage=='event.before_commit'):
            os.kill(os.getpid(),signal.SIGKILL)
        if mode=='cancel-nonce' and stage=='nonce.after_commit':
            for attachment in commands._channels.values():
                if attachment.pending is not None:attachment.pending.future.cancel()
        if mode=='commit-error' and stage=='event.after_commit':raise OSError('synthetic response boundary loss')
    journal.observer=observe
    sockets=[socket.socket(fileno=3),socket.socket(fileno=4)]
    print(json.dumps({'ready':True,'commandContext':command_context,'subscriptionContext':sub_context,
                      'socket_families':[x.family for x in sockets],'pid':os.getpid(),'pgid':os.getpgrp(),
                      'owner_thread':threading.get_ident(),'journal':journal.inspect()}),flush=True)
    tasks=[asyncio.create_task(serve_commands_connected(commands,sockets[0],allow_publish=grant,read_timeout=4,write_timeout=2)),
           asyncio.create_task(serve_connected(host,sockets[1],b'c'*16,read_timeout=4,write_timeout=2))]
    try:await asyncio.gather(*tasks)
    finally:
        commands.close();host.close();await commands.wait_closed()
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        try:state=journal.inspect()
        except EventError as exc:state={'error':exc.code}
        stats={'commands':commands.stats(),'subscriptions':host.stats()}
        journal.close();owner.close()
        print(json.dumps({'ended':True,'stats':stats,'journal':state,'storage_threads':sorted(threads)}),flush=True)
if __name__=='__main__':asyncio.run(main())
