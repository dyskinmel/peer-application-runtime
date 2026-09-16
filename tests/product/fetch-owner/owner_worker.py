"""Synthetic data, real Store/Inbox/TLS and inherited private owner descriptor."""
from pathlib import Path
import sys,asyncio,json,os,signal,socket,ssl,hashlib
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True
for p in [ROOT]+[ROOT/'tests/product'/n for n in ('causal-exchange','auth-store','space-auth')]+list((ROOT/'experiments').iterdir()):sys.path.insert(0,str(p))
from process_fixture import Peer,h
from par_crypto import objects
from product.wp04.exchange import Source
from product.wp09.par_secure_transport import TLSStream,TLSConfig,ReadSession,PeerBinding,Limits
from product.wp09.par_secure_fetch import FetchPlan
from product.wp09.par_fetch_owner import FetchOwner,serve_fetch_connected

def fingerprint(p):return hashlib.sha256(ssl.PEM_cert_to_DER_cert(p.read_text())).hexdigest()
async def main():
    role=sys.argv[1];fds=json.loads(sys.argv[2]);root=Path(sys.argv[3]);pki=Path(sys.argv[4]);mode=sys.argv[5];ui_fd=int(sys.argv[6])
    sockets=[socket.socket(fileno=n)for n in fds];peer=None;owner=None;streams=[];used=0
    try:
        if role=='stall':
            for sock in sockets:
                sock.setblocking(False)
                while await asyncio.get_running_loop().sock_recv(sock,65536):pass
            print(json.dumps({'stalled_tls_fixture':True}));return
        root.mkdir(mode=0o700,exist_ok=True);peer=Peer(root/'peer');a,b=peer.chain();c=peer.change('c',3,[h('inner:b')],objects.envelope_id(b[0]));chain=(a,b,c)
        server=role=='provider';name='server'if server else'client';other='client'if server else'server'
        if server:
            for row in chain:peer.box.receive(*row)
            device=peer.s.devices[1]
        else:
            d=peer.s.devices[1];peer.source=Source(peer.box,d['cert'],d['seed']);device=peer.s.devices[0]
            peer.box.receive(*c)  # One pre-existing encrypted root candidate; not downloaded here.
        cfg=TLSConfig(server,pki/'ca.pem',pki/(name+'.pem'),pki/(name+'.key'),fingerprint(pki/(other+'.pem')),None if server else'server.test')
        binding=PeerBinding(other,device['cert'],peer.source.scope,cfg.peer_sha256,9)
        before=peer.db._storage.connection.total_changes
        async def session():
            nonlocal used
            raw=sockets[used];used+=1
            stream=await TLSStream.open(raw,cfg,limits=Limits(timeout=4));streams.append(stream)
            return ReadSession(stream,peer.source,binding,lambda:9)
        if server:
            requests=[];answer=peer.source.answer
            def recorded(cert,op,args):
                value=answer(cert,op,args);requests.append(op);return value
            peer.source.answer=recorded
            for _ in sockets:await(await session()).serve()
            print(json.dumps({'requests':requests,'db_unchanged':before==peer.db._storage.connection.total_changes}));return
        plan=FetchPlan(peer.source.scope,h('fixed local root plan'),[(h('inner:c'),objects.envelope_id(c[0]),len(c[0]))],binding,peer.box.pin()['generation'])
        directory=root/'plans';directory.mkdir(mode=0o700,exist_ok=True)
        owner=FetchOwner(plan,peer.source,[objects.envelope_id(c[0])],lambda:9,session,directory)
        if mode=='kill-accept':
            persist=owner._persist
            def kill(plan):persist(plan);os.kill(os.getpid(),signal.SIGKILL)
            owner._persist=kill
        elif mode=='kill-fetch':
            def kill(stage):
                if stage=='inbox.after_dirsync':os.kill(os.getpid(),signal.SIGKILL)
            peer.box.observer=kill
        print(json.dumps({'ready':True,'pin':owner._pin}),flush=True)
        await serve_fetch_connected(owner,socket.socket(fileno=ui_fd),allow_fetch=mode!='readonly',read_timeout=10)
        stats=await owner.close()
        print(json.dumps({'result':'PASS','owner':stats,'candidate_count':peer.box.usage()['records'],
                          'network_calls':used,'db_unchanged':before==peer.db._storage.connection.total_changes,'process_group':os.getpgrp()}),flush=True)
    finally:
        if owner is not None:await owner.close()
        for s in streams:await s.close()
        for s in sockets:s.close()
        if peer is not None:peer.close()
if __name__=='__main__':asyncio.run(main())
