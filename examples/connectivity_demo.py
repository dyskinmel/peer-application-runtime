#!/usr/bin/env python3
"""Private socketpair demo. Public fixed transcript is NOT cryptographic peer auth."""
from __future__ import annotations
import asyncio, json, os, socket, subprocess, sys
from dataclasses import asdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from product.wp09.par_connectivity import (Candidate,RouteGrant,Policy,Connector,PeerProof,SocketConnection,ConnectivityError)

def fixture_peer(fd):
    with socket.socket(fileno=fd) as s:
        s.settimeout(2)
        if s.recv(1)!=b'P':return 1
        s.sendall(b'OK')
        while s.recv(1):pass
    return 0

async def demo():
    endpoint='tcp://127.0.0.1:43123' # A label for a synthetic route; never TCP-dialed.
    children=[];streams=[];calls=[]
    class FixtureConnection:
        observed_path='local-fixture'
        def __init__(self,target,stream):self.target=target;self.stream=stream
        def peername(self):return (self.target.ip,self.target.port) # Fixture assertion, not OS IP evidence.
        async def close(self):await self.stream.close()
    class Dialer:
        supported_schemes=frozenset({'tcp'})
        async def dial(self,target,cancel):
            calls.append(target)
            a,b=socket.socketpair()
            try:
                child=subprocess.Popen([sys.executable,'-I','-S','-B',str(Path(__file__).resolve()),'--fixture-peer',str(b.fileno())],
                    pass_fds=(b.fileno(),),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            except BaseException:
                a.close();raise
            finally:b.close()
            children.append(child);stream=SocketConnection(a,io_timeout=1);streams.append(stream)
            return FixtureConnection(target,stream)
    class FixtureAuthenticator:
        async def authenticate(self,connection,expected_peer,scope_id,cancel):
            await connection.stream.write(b'P')
            if await connection.stream.read_exact(2)!=b'OK':raise ConnectivityError('FIXTURE_REFUSED')
            return PeerProof(expected_peer,scope_id)
    grant=RouteGrant(endpoint,'synthetic-peer','manual',('127.0.0.1/32',),allow_local=True)
    c=Connector(Policy(grants=(grant,),allow_egress=True),None,Dialer(),FixtureAuthenticator(),'synthetic-scope')
    try:
        connected=await c.connect((Candidate(endpoint,'synthetic-peer'),))
        assert connected.state=='CONNECTED' and connected.observed_path=='local-fixture'
        changed=await c.change_network(metered=True)
        assert len(calls)==1 # network notification alone does not reconnect.
        denied=await c.connect((Candidate(endpoint,'synthetic-peer'),))
        assert denied.reason=='METERED_DENIED'
        await c.close();cleanup=await c.wait_for_cleanup()
        assert cleanup['cleanup_complete']
        for child in children:
            child.wait(timeout=2);assert child.returncode==0
        print(json.dumps({'result':'PASS','scope':'LOCAL_SOCKETPAIR_FIXTURE_ONLY','observed_path':connected.observed_path,
             'real_peer_auth_executed':False,'public_network_executed':False,'real_dns_executed':False,
             'dial_calls':len(calls),'network_change_generation':changed['generation'],
             'metered_reason':denied.reason,'cleanup':cleanup},indent=2))
    finally:
        await c.close();await c.wait_for_cleanup()
        for stream in streams:await stream.close()
        for child in children:
            if child.poll() is None:
                child.terminate();child.wait(timeout=2)

if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--fixture-peer':raise SystemExit(fixture_peer(int(sys.argv[2])))
    if len(sys.argv)!=1:raise SystemExit('Usage: connectivity_demo.py')
    asyncio.run(demo())
