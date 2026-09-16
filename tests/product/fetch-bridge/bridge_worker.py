"""Public opaque fixture only; private inherited fds, never public listeners."""
from pathlib import Path
import asyncio,hashlib,json,os,secrets,signal,socket,ssl,sys
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True
for p in[ROOT,ROOT/'tests/product/causal-exchange',ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+[p for p in(ROOT/'experiments').iterdir()if p.is_dir()]:sys.path.insert(0,str(p))
from process_fixture import Peer,h
from par_crypto import objects
from product.wp04.exchange import Source
from product.wp09.par_secure_transport import TLSConfig,TLSStream,ReadSession,PeerBinding,Limits
from product.wp09.par_secure_fetch import FetchPlan,FetchClient
from product.wp09.par_secure_fetch.dependencies import DependencyPlanner
from product.runtime_read.fetch import FetchApplicationController

def fingerprint(p):return hashlib.sha256(ssl.PEM_cert_to_DER_cert(p.read_text())).hexdigest()
async def main():
    role=sys.argv[1];fds=json.loads(sys.argv[2]);root=Path(sys.argv[3]);pki=Path(sys.argv[4]);mode=sys.argv[5];old=json.loads(sys.argv[6])
    root.mkdir(mode=0o700,exist_ok=True);sockets=[socket.socket(fileno=n)for n in fds];streams=[];peer=None;used=0
    try:
        peer=Peer(root/'peer');a,b=peer.chain();c=peer.change('c',3,[h('inner:b')],objects.envelope_id(b[0]));chain=(a,b,c)
        server=role=='provider';name='server'if server else'client';other='client'if server else'server'
        if server:
            for row in chain:peer.box.receive(*row)
            other_device=peer.s.devices[1]
        else:
            d=peer.s.devices[1];peer.source=Source(peer.box,d['cert'],d['seed']);other_device=peer.s.devices[0]
        cfg=TLSConfig(server,pki/'ca.pem',pki/(name+'.pem'),pki/(name+'.key'),fingerprint(pki/(other+'.pem')),None if server else'server.test')
        binding=PeerBinding(other,other_device['cert'],peer.source.scope,cfg.peer_sha256,9)
        before=peer.db._storage.connection.total_changes
        async def session(*unused):
            nonlocal used
            raw=sockets[used];used+=1
            stream=await TLSStream.open(raw,cfg,limits=Limits(timeout=4));streams.append(stream)
            return ReadSession(stream,peer.source,binding,lambda:9)
        if server:
            requests=[];answer=peer.source.answer
            def recorded(cert,action,args):
                value=answer(cert,action,args);requests.append({'method':action,'innerId':args[1].hex()if action=='get'else None});return value
            peer.source.answer=recorded
            for raw in sockets:
                read=await session();await read.serve()
            print(json.dumps({'result':'PASS','requests':requests,'db_unchanged':before==peer.db._storage.connection.total_changes,'closed':all(s.closed for s in streams)}),flush=True)
            return
        if mode=='seed':
            read=await session();page=await read.request('have',{0:None,1:0,2:16})
            descriptor=next(d for d in page[2]if d[0]==h('inner:c'))
            root_plan=FetchPlan(peer.source.scope,page[0],[descriptor],binding,peer.box.pin()['generation'])
            plan_sha=root_plan.save(root/'root-plan.cbor');initial=FetchClient(root_plan,peer.source,lambda:9)
            await initial.execute(session)
        else:
            plan_sha=old['planSha'];root_plan=FetchPlan.load(root/'root-plan.cbor',expected_sha256=plan_sha)
            initial=FetchClient(root_plan,peer.source,lambda:9)
            initial.restore_checkpoint(root/old['checkpointPath'],expected_sha256=old['checkpointSha'])
        targets=(root_plan.descriptors[0][1],)
        def checkpoint():
            dest=root/('checkpoint-'+secrets.token_hex(8)+'.json')
            proof={'planSha':plan_sha,'checkpointPath':dest.name,'checkpointSha':initial.save_checkpoint(dest)}
            return proof
        proof=checkpoint()
        print(json.dumps({'event':'before_explicit_action','proof':proof}),flush=True)
        if mode=='round'or mode.startswith('kill:'):
            proposal=await DependencyPlanner(peer.source,binding,lambda:9).build(targets,session)
            plan=proposal.accept(peer.source,lambda:9)
            if plan is not None:
                plan.save(root/('frontier-'+secrets.token_hex(8)+'.cbor'))
                if mode.startswith('kill:'):
                    stage=mode.split(':',1)[1]
                    def stop(at):
                        if at==stage:os.kill(os.getpid(),signal.SIGKILL)
                    peer.box.observer=stop
                await FetchClient(plan,peer.source,lambda:9).execute(session)
        controller=FetchApplicationController(root_plan,peer.source,targets,lambda:9)
        observation=controller.observe()
        if mode=='validate':observation=controller.validate(expected_revision=observation['revision'])
        proof=checkpoint()
        print(json.dumps({'result':'PASS','proof':proof,'observation':observation,'inbox_records':peer.box.usage()['records'],
                          'network_calls':used,'db_unchanged':before==peer.db._storage.connection.total_changes,
                          'process_group':os.getpgrp(),'closed':all(s.closed for s in streams),'inner_a':h('inner:a').hex()}),flush=True)
    finally:
        for s in streams:await s.close()
        for s in sockets:s.close()
        if peer is not None:peer.close()
if __name__=='__main__':asyncio.run(main())
