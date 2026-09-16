"""Private-FD test worker; ephemeral TLS PKI and public existing Store fixtures."""
from pathlib import Path
import asyncio,hashlib,json,os,signal,socket,ssl,sys
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True
for p in [ROOT,Path(__file__).parent,ROOT/'tests/product/causal-exchange',ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+[p for p in (ROOT/'experiments').iterdir() if p.is_dir()]:sys.path.insert(0,str(p))
from process_fixture import Peer
from product.wp09.par_secure_transport import TLSConfig,TLSStream,ReadSession,PeerBinding,Limits

def fingerprint(path):return hashlib.sha256(ssl.PEM_cert_to_DER_cert(path.read_text())).hexdigest()

async def main():
    fds=json.loads(sys.argv[1]);root=Path(sys.argv[2]);pki=Path(sys.argv[3]);mode=sys.argv[4]
    if type(fds) is not list or not 1<=len(fds)<=8:raise ValueError('fixture fd count')
    sockets=[socket.socket(fileno=fd) for fd in fds];peer=None;streams=[]
    try:
        if mode=='stall':await asyncio.sleep(5);return
        peer=Peer(root)
        for pair in peer.chain():peer.box.receive(*pair)
        before=peer.db._storage.connection.total_changes
        cfg=TLSConfig(True,pki/'ca.pem',pki/'server.pem',pki/'server.key',fingerprint(pki/'client.pem'))
        binding=PeerBinding('reader',peer.s.devices[1]['cert'],tuple(peer.source.scope),cfg.peer_sha256,9)
        if mode=='kill-before-response':
            original=peer.source.answer
            def killed(*args):
                value=original(*args);os.kill(os.getpid(),signal.SIGKILL);return value
            peer.source.answer=killed
        results=[]
        for raw in sockets:
            stream=await TLSStream.open(raw,cfg,limits=Limits(timeout=3))
            streams.append(stream)
            if mode=='kill-after-handshake':os.kill(os.getpid(),signal.SIGKILL)
            session=ReadSession(stream,peer.source,binding,lambda:9)
            result=await session.serve()
            results.append({'result':result,'version':stream.tls_version,'cipher':stream.cipher,
                            'client_pin_verified':stream.peer_certificate_sha256==cfg.peer_sha256})
        print(json.dumps({'result':'PASS','pid':os.getpid(),'process_group':os.getpgrp(),
                          'exchanges':results,'db_unchanged':before==peer.db._storage.connection.total_changes,
                          'records':peer.box.usage()['records'],'closed':all(s.closed for s in streams)}),flush=True)
    finally:
        for s in streams:await s.close()
        for s in sockets:s.close()
        if peer is not None:peer.close()
if __name__=='__main__':asyncio.run(main())
