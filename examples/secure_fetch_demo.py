#!/usr/bin/env python3
"""Real private mTLS -> two encrypted Inbox candidates -> offline restart.

Only disposable public synthetic inputs. No listener, actual CRDT, ACK or user
keys. The receiver is a separate process from the TLS provider and this runner.
"""
from pathlib import Path
import asyncio,json,os,socket,sys,tempfile
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'tests/product/secure-transport'))
from secure_support import TestPKI
SERVER=ROOT/'tests/product/secure-transport/secure_worker.py'
READER=ROOT/'tests/product/secure-fetch/fetch_worker.py'
async def run():
    pki=TestPKI();children=[];pairs=[]
    try:
        with tempfile.TemporaryDirectory(prefix='par-secure-fetch-demo-')as tmp:
            root=Path(tmp);pairs=[socket.socketpair()for _ in range(3)]
            async def spawn(argv,fds=()):
                p=await asyncio.create_subprocess_exec(sys.executable,'-I','-S','-B',*map(str,argv),pass_fds=fds,stdin=asyncio.subprocess.DEVNULL,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE);children.append(p);return p
            async def finish(p):
                out,err=await asyncio.wait_for(p.communicate(),12)
                if p.returncode:raise RuntimeError('fixture process failed: '+err.decode())
                return [json.loads(l)for l in out.splitlines()]
            sfds=[b.fileno()for a,b in pairs];rfds=[a.fileno()for a,b in pairs]
            server=await spawn([SERVER,json.dumps(sfds),root/'provider',pki.path,'normal'],sfds)
            reader=await spawn([READER,json.dumps(rfds),root/'receiver',pki.path,'fresh'],rfds)
            for a,b in pairs:a.close();b.close()
            rows=await finish(reader);remote=(await finish(server))[0];proof=rows[0];first=rows[-1]
            again=await spawn([READER,'[]',root/'receiver',pki.path,'resume',proof['planSha'],proof['checkpointSha']]);resumed=(await finish(again))[-1]
            good=(first['progress']['stored']==resumed['progress']['stored']==2 and resumed['network_calls']==0
                  and first['db_unchanged']and remote['db_unchanged']and first['closed']and remote['closed']
                  and all(r['version']=='TLSv1.3'for r in remote['exchanges']))
            result={'result':'PASS'if good else'FAIL','stored':resumed['progress']['stored'],'resume_network_calls':resumed['network_calls'],
                    'methods':[r['result']['method']for r in remote['exchanges']], 'tls':'TLSv1.3',
                    'provider_and_application_store_unchanged':first['db_unchanged']and remote['db_unchanged'],
                    'applied':False,'acknowledged':False,'public_network_executed':False,'independent_review':'NOT_RUN'}
            print(json.dumps(result,indent=2));return 0 if good else 1
    finally:
        for p in children:
            if p.returncode is None:p.terminate()
            await p.communicate()
        for a,b in pairs:a.close();b.close()
        pki.close()
if __name__=='__main__':raise SystemExit(asyncio.run(run()))
