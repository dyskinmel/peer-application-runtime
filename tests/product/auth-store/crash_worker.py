"""Owned child process, synthetic data only. The selected stage sends real SIGKILL."""
from pathlib import Path
import os, signal, sys
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True
for path in ['experiments/auth-store','experiments/space-auth','experiments/g0-crypto','experiments/g0-wire','experiments/g0-store','tests/product/space-auth','tests/product/auth-store']:sys.path.insert(0,str(ROOT/path))
from auth_store_support import provider,Scenario,epoch_bundle,h,control_id
from par_auth_store import AuthorityStore,AuthenticatedWriter
from par_auth.errors import AuthError
root=Path(sys.argv[1]);action=sys.argv[2];stage=sys.argv[3]
p=provider();s=Scenario(p);b=epoch_bundle(s)
def crash(here):
    if here==stage:
        print('REACHED:'+here,flush=True);os.kill(os.getpid(),signal.SIGKILL)
if action=='migration':
    AuthorityStore.migrate_empty(root,provider=p,allow_unpatched_sqlite=True,observer=crash).close()
else:
    db=AuthorityStore.open(root,provider=p,allow_unpatched_sqlite=True)
    if action in ('write','crypto'):db.reactivate(s.space,s.devices[0]['secret'])
    db.observer=crash
    if action=='control':
        nb=epoch_bundle(s,s.next(b['raw'],3),h('next'),entries=s.entries[1:]);db.observe(s.space,nb['raw'])
    elif action=='membership':db.provide_membership(s.space,b['pages'])
    elif action=='activate':
        d=s.devices[0];db.activate(s.space,d['cert'],d['secret'],b['packages'][d['id']],b['ids'],b['manifest'],b['seeds'])
    elif action=='fork':
        body=dict(b['body']);body[9]=h('alternate')
        try:db.observe(s.space,s.raw(body))
        except AuthError as e:
            if e.code!='CONTROL_FORK':raise
    else:
        plain=b'opaque inner change - not an Automerge document';cache=b'candidate materialization not semantically checked';d=s.devices[0]
        header={0:s.app,1:s.space,2:1,3:h('doc'),4:1,5:d['id'],6:h('actor-generation')[:16],7:1,8:None,9:h('schema'),10:[],11:len(plain),12:h('inner-hash'),13:control_id(b['raw']),14:1,15:0}
        writer=AuthenticatedWriter(db,d['cert'],s.secret,d['seed'],h('local-secret'),observer=crash)
        writer.write((1).to_bytes(16,'big'),header,plain,cache)
    db.close()
raise RuntimeError('requested crash stage was never reached')
