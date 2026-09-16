"""Private-FD public-fixture receiver: persist plan before receive; restart safely."""
from pathlib import Path
import asyncio,hashlib,json,os,signal,socket,ssl,sys
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/causal-exchange',ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+[p for p in (ROOT/'experiments').iterdir()if p.is_dir()]:sys.path.insert(0,str(p))
from process_fixture import Peer
from product.wp04.exchange import Source
from product.wp09.par_secure_transport import TLSConfig,TLSStream,ReadSession,PeerBinding,Limits
from product.wp09.par_secure_fetch import FetchPlan,FetchClient

def fingerprint(path):return hashlib.sha256(ssl.PEM_cert_to_DER_cert(path.read_text())).hexdigest()
async def main():
    fds=json.loads(sys.argv[1]);root=Path(sys.argv[2]);pki=Path(sys.argv[3]);mode=sys.argv[4]
    root.mkdir(mode=0o700,exist_ok=True);sockets=[socket.socket(fileno=fd)for fd in fds];peer=None;streams=[];used=0
    try:
        peer=Peer(root/'peer');d=peer.s.devices[1];peer.source=Source(peer.box,d['cert'],d['seed'])
        cfg=TLSConfig(False,pki/'ca.pem',pki/'client.pem',pki/'client.key',fingerprint(pki/'server.pem'),'server.test')
        binding=PeerBinding('provider',peer.s.devices[0]['cert'],tuple(peer.source.scope),cfg.peer_sha256,9)
        async def session(i=0):
            nonlocal used
            raw=sockets[used];used+=1
            stream=await TLSStream.open(raw,cfg,limits=Limits(timeout=4));streams.append(stream)
            return ReadSession(stream,peer.source,binding,lambda:9)
        before=peer.db._storage.connection.total_changes
        if mode in('resume','continue','replan-continue'):
            plan=FetchPlan.load(root/'plan.cbor',expected_sha256=sys.argv[5]);client=FetchClient(plan,peer.source,lambda:9)
            progress=client.restore_checkpoint(root/'initial-checkpoint.json',expected_sha256=sys.argv[6])
        else:
            read=await session();page=await read.request('have',{0:None,1:0,2:16})
            if page[3]is not None:raise RuntimeError('TEST_PAGE_TRUNCATED')
            plan=FetchPlan(peer.source.scope,page[0],page[2],binding,peer.box.pin()['generation'])
            plan_sha=plan.save(root/'plan.cbor');client=FetchClient(plan,peer.source,lambda:9)
            cp_sha=client.save_checkpoint(root/'initial-checkpoint.json')
            print(json.dumps({'event':'plan_saved','planSha':plan_sha,'checkpointSha':cp_sha}),flush=True)
        if mode=='replan-continue':
            # Explicit new plan: provider restart changes its authority revision.
            # Never silently relabel the old snapshot or replay a saved object.
            read=await session();page=await read.request('have',{0:None,1:0,2:16})
            if page[3]is not None or not all(list(d)in page[2]for d in plan.descriptors):raise RuntimeError('REPLAN_DESCRIPTOR_CHANGED')
            plan=FetchPlan(plan.scope,page[0],plan.descriptors,plan.binding,plan.inbox_generation)
            new_sha=plan.save(root/'replanned.cbor');client=FetchClient(plan,peer.source,lambda:9)
            new_cp=client.save_checkpoint(root/'replanned-checkpoint.json')
            print(json.dumps({'event':'explicit_replan','planSha':new_sha,'checkpointSha':new_cp}),flush=True)
        if mode.startswith('kill:'):
            stage=mode.split(':',1)[1]
            def observe(name):
                if name==stage:os.kill(os.getpid(),signal.SIGKILL)
            peer.box.observer=observe
        if mode!='resume':progress=await client.execute(session)
        print(json.dumps({'result':'PASS','progress':progress,'network_calls':used,'inbox_records':peer.box.usage()['records'],
                          'db_unchanged':before==peer.db._storage.connection.total_changes,'process_group':os.getpgrp(),
                          'closed':all(s.closed for s in streams)}),flush=True)
    finally:
        for s in streams:await s.close()
        for s in sockets:s.close()
        if peer is not None:peer.close()
if __name__=='__main__':asyncio.run(main())
