#!/usr/bin/env python3
"""Disposable local demonstration: fresh test mTLS + signed HAVE/NEED/GET.

No listener, DNS/IP dial, user secrets, enrollment, recipient write or CRDT.
Temporary test certificate private keys are removed when the demo exits.
"""
from pathlib import Path
import asyncio,json,os,socket,sys,tempfile
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/secure-transport',ROOT/'tests/product/causal-exchange',ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+[p for p in (ROOT/'experiments').iterdir() if p.is_dir()]:sys.path.insert(0,str(p))
from secure_support import TestPKI
from process_fixture import Peer,h
from product.wp04.exchange import Source
from product.wp09 import par_secure_transport as tls

async def run():
    pki=TestPKI();raw=[];streams=[];child=None;reader=None
    with tempfile.TemporaryDirectory(prefix='par-tls-demo-') as temp:
        try:
            root=Path(temp);reader=Peer(root/'reader');d=reader.s.devices[1]
            reader.source=Source(reader.box,d['cert'],d['seed'])
            pairs=[socket.socketpair() for _ in range(3)];raw=[s for pair in pairs for s in pair]
            fds=[b.fileno() for a,b in pairs]
            child=await asyncio.create_subprocess_exec(sys.executable,'-I','-S','-B',str(ROOT/'tests/product/secure-transport/secure_worker.py'),json.dumps(fds),str(root/'provider'),str(pki.path),'normal',pass_fds=fds,stdin=asyncio.subprocess.DEVNULL,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            for a,b in pairs:b.close()
            before=reader.db._storage.connection.total_changes;answers={}
            binding=tls.PeerBinding('provider',reader.s.devices[0]['cert'],tuple(reader.source.scope),pki.pin('server'),9)
            for i,method in enumerate(('have','need','get')):
                stream=await tls.TLSStream.open(pairs[i][0],pki.config(tls,False));streams.append(stream)
                session=tls.ReadSession(stream,reader.source,binding,lambda:9)
                if method=='have':args={0:None,1:0,2:16}
                elif method=='need':args=[h('inner:a')]
                else:
                    desc=answers['need'][1][0][1];args={0:answers['need'][0],1:desc[0],2:desc[1]}
                answers[method]=await session.request(method,args)
            out,err=await asyncio.wait_for(child.communicate(),3)
            if child.returncode:raise RuntimeError('DEMO_PROVIDER_FAILED')
            provider=json.loads(out)
            result={'result':'PASS','methods':['have','need','get'],
                'tls_versions':[s.tls_version for s in streams], 'mutual_tls':True,
                'ciphertext_equal':answers['get'][3]==reader.chain()[0][0],
                'recipient_unchanged':reader.db._storage.connection.total_changes==before and reader.box.usage()['records']==0,
                'provider_unchanged':provider['db_unchanged'],
                'provider_pid':provider['pid'],'process_group_preserved':provider['process_group']==os.getpgrp(),
                'streams_closed':all(s.closed for s in streams) and provider['closed'],
                'public_network_executed':False,'crdt_applied':False,'production_ready':False,
                'test_pki':'EPHEMERAL_SYNTHETIC_KEYS_NOT_PRODUCT_ENROLLMENT'}
            if not all(result[k] for k in ('ciphertext_equal','recipient_unchanged','provider_unchanged','streams_closed','process_group_preserved')):raise RuntimeError('DEMO_INVARIANT_FAILED')
            return result
        finally:
            await asyncio.gather(*(s.close() for s in streams),return_exceptions=True)
            for s in raw:s.close()
            if child is not None and child.returncode is None:
                child.terminate()
                try:await asyncio.wait_for(child.communicate(),2)
                except TimeoutError:child.kill();await child.communicate()
            if reader is not None:reader.close()
            pki.close()
if __name__=='__main__':
    print(json.dumps(asyncio.run(run()),ensure_ascii=False,indent=2))
