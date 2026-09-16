from pathlib import Path
import importlib,importlib.util,tempfile
from process_fixture import Peer,h
from product.wp04.exchange import Source
from product.wp09.par_secure_transport import PeerBinding

class LocalFixture:
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('product.wp09.par_secure_fetch'), 'secure fetch module missing')
        self.m=importlib.import_module('product.wp09.par_secure_fetch')
        self.temp=tempfile.TemporaryDirectory(prefix='par-fetch-');self.root=Path(self.temp.name)
        self.remote=Peer(self.root/'remote');self.local=Peer(self.root/'local')
        d=self.local.s.devices[1];self.local.source=Source(self.local.box,d['cert'],d['seed'])
        for row in self.remote.chain():self.remote.box.receive(*row)
        self.token,self.descriptors,_=self.remote.source.catalog(d['cert'])
        self.gen=[9]
        self.binding=PeerBinding('remote',self.remote.s.devices[0]['cert'],tuple(self.local.source.scope),'a'*64,9)
    def tearDown(self):
        self.local.close();self.remote.close();self.temp.cleanup()
    def make_plan(self,**kw):
        args=dict(scope=self.local.source.scope,snapshot=self.token,descriptors=self.descriptors,binding=self.binding,
                  inbox_generation=self.local.box.pin()['generation'],max_records=64,max_bytes=8*1024*1024)
        args.update(kw);return self.m.FetchPlan(**args)
    def client(self,plan=None):return self.m.FetchClient(plan or self.make_plan(),self.local.source,lambda:self.gen[0])

import asyncio,socket
from secure_support import TestPKI
from product.wp09 import par_secure_transport as tls
class AsyncFixture(LocalFixture):
    @classmethod
    def setUpClass(cls):cls.pki=TestPKI()
    @classmethod
    def tearDownClass(cls):cls.pki.close()
    async def asyncSetUp(self):
        self.raw=[];self.streams=[];self.servers=[]
        self.binding=PeerBinding('remote',self.remote.s.devices[0]['cert'],tuple(self.local.source.scope),self.pki.pin('server'),9)
    async def session(self):
        a,b=socket.socketpair();self.raw.extend((a,b))
        server,client=await asyncio.gather(tls.TLSStream.open(a,self.pki.config(tls,True)),tls.TLSStream.open(b,self.pki.config(tls,False)))
        self.streams.extend((server,client))
        sb=PeerBinding('local',self.local.s.devices[1]['cert'],tuple(self.remote.source.scope),self.pki.pin('client'),9)
        s=tls.ReadSession(server,self.remote.source,sb,lambda:self.gen[0]);self.servers.append(asyncio.create_task(s.serve()))
        return tls.ReadSession(client,self.local.source,self.binding,lambda:self.gen[0])
    async def asyncTearDown(self):
        for t in self.servers:
            if not t.done():t.cancel()
        await asyncio.gather(*self.servers,return_exceptions=True)
        await asyncio.gather(*(s.close()for s in self.streams),return_exceptions=True)
        for s in self.raw:s.close()
