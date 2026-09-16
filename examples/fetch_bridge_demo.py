#!/usr/bin/env python3
"""Disposable three-level candidate fetch, explicit validation and offline view.

Private socketpairs, real TLS/SQLite, separate provider/receiver. Opaque public
fixture payloads are NOT Automerge. No public listener or automatic application.
"""
from pathlib import Path
import asyncio,json,os,socket,sys,tempfile
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'tests/product/secure-transport'))
from secure_support import TestPKI
WORKER=ROOT/'tests/product/fetch-bridge/bridge_worker.py'

async def run():
    pki=TestPKI();children=[];sockets=[]
    try:
        with tempfile.TemporaryDirectory(prefix='par-fetch-bridge-demo-')as tmp:
            root=Path(tmp)
            async def spawn(argv,fds=()):
                p=await asyncio.create_subprocess_exec(sys.executable,'-I','-S','-B',str(WORKER),*map(str,argv),pass_fds=fds,stdin=asyncio.subprocess.DEVNULL,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
                children.append(p);return p
            async def finish(p):
                out,err=await asyncio.wait_for(p.communicate(),18)
                if p.returncode:raise RuntimeError('fixture failed: '+err.decode())
                return [json.loads(line)for line in out.splitlines()]
            async def phase(mode,count,proof=None):
                pairs=[socket.socketpair()for _ in range(count)];sockets.extend(s for pair in pairs for s in pair)
                a=[s[0].fileno()for s in pairs];b=[s[1].fileno()for s in pairs]
                provider=await spawn(['provider',json.dumps(b),root/'provider',pki.path,'serve','{}'],b)if count else None
                receiver=await spawn(['receiver',json.dumps(a),root/'receiver',pki.path,mode,json.dumps(proof or{})],a)
                for s in sockets:s.close()
                result=(await finish(receiver))[-1]
                remote=(await finish(provider))[-1]if provider else None
                return result,remote
            seed,s=await phase('seed',2);one,p=await phase('round',3,seed['proof']);two,q=await phase('round',3,one['proof']);offline,_=await phase('validate',0,two['proof'])
            rows=[seed,one,two,offline];remote=[s,p,q];obs=offline['observation']
            good=([r['inbox_records']for r in rows]==[1,2,3,3]and offline['network_calls']==0
                  and obs['records'][0]['validation']['reason']=='CORE_UNAVAILABLE'
                  and all(r['db_unchanged']and r['closed']for r in rows+remote)
                  and all(r['process_group']==os.getpgrp()for r in rows))
            print(json.dumps({'result':'PASS'if good else'FAIL','candidate_counts':[r['inbox_records']for r in rows],
                'explicit_frontier_rounds':2,'methods':[[x['method']for x in r['requests']]for r in remote],
                'offline_network_calls':offline['network_calls'],'validation':obs['records'][0]['validation'],
                'stores_unchanged':all(r['db_unchanged']for r in rows+remote),'resources_closed':all(r['closed']for r in rows+remote),
                'applied':False,'acknowledged':False,'real_core_executed':False,'public_network_executed':False,'product_qualified':False},indent=2))
            return 0 if good else 1
    finally:
        for p in children:
            if p.returncode is None:p.terminate()
            await p.communicate()
        for s in sockets:s.close()
        pki.close()
if __name__=='__main__':raise SystemExit(asyncio.run(run()))
