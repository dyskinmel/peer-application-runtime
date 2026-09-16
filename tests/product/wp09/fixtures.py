"""Trusted local fixture ports. Never claim cryptographic peer authentication."""
import asyncio
from product.wp09 import par_connectivity as api

async def settled(predicate, limit=0.5):
    async with asyncio.timeout(limit):
        while not predicate():await asyncio.sleep(0.001)

class FixtureConnection:
    observed_path='local-fixture'
    def __init__(self,target):self.target=target;self.closed=0;self.close_wait=None;self.close_error=False;self.peer_override=None
    def peername(self):return self.peer_override or (self.target.ip,self.target.port)
    async def close(self):
        self.closed+=1
        if self.close_wait is not None:await self.close_wait.wait()
        if self.close_error:raise OSError('PRIVATE_ERROR_SENTINEL')

class Resolver:
    def __init__(self):self.calls=[];self.handler=None
    async def resolve(self,host,resolver_id,cancel):
        self.calls.append((host,resolver_id))
        if self.handler:return await self.handler(host,resolver_id,cancel)
        return api.Resolution(host,resolver_id,('8.8.8.8',))

class Dialer:
    supported_schemes=frozenset({'tcp'})
    def __init__(self):self.calls=[];self.connections=[];self.handler=None
    async def dial(self,target,cancel):
        self.calls.append(target)
        if self.handler:return await self.handler(target,cancel)
        c=FixtureConnection(target);self.connections.append(c);return c

class Authenticator:
    def __init__(self):self.calls=[];self.handler=None
    async def authenticate(self,connection,peer,scope,cancel):
        self.calls.append((peer,scope))
        if self.handler:return await self.handler(connection,peer,scope,cancel)
        return api.PeerProof(peer,scope)
