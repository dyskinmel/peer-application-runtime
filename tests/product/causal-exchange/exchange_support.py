"""Public synthetic fixtures; real signatures, encryption, Store and sockets."""
import importlib.util, threading, time
from inbox_support import InboxTest, h
from par_wire.codec import decode

class ExchangeTest(InboxTest):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec('product.wp04.exchange'), 'causal exchange is not implemented')
        from product.wp04 import exchange as m
        self.x=m; self.create(); self.source=m.Source(self.box,self.s.devices[0]['cert'],self.s.devices[0]['seed'])
        self.reader=self.s.devices[1]; self.server=None
        self.socket_path=self.root.parent/'causal.sock'
        self.addCleanup(self.close_server)
    def close_server(self):
        if self.server:self.server.close();self.server=None
    def start_server(self,**kw):
        self.server=self.x.Server(self.source,self.socket_path,**kw);return self.server
    def client(self,device=None,**kw):
        d=device or self.reader
        return self.x.Client(self.socket_path,self.p,self.source.public,self.source.scope,d['cert'],d['seed'],**kw)
    def rpc(self,fn,*,timeout=6):
        result=[];errors=[]
        def run():
            try:result.append(fn())
            except BaseException as e:errors.append(e)
        t=threading.Thread(target=run);t.start();end=time.monotonic()+timeout
        while t.is_alive() and time.monotonic()<end:self.server.poll(.005)
        t.join(.1);self.assertFalse(t.is_alive(),'client did not complete within test bound')
        if errors:raise errors[0]
        return result[0]
    def reject_exchange(self,code,fn):
        with self.assertRaises(self.x.ExchangeError) as cm:fn()
        if code:self.assertEqual(cm.exception.code,code)
    def fill(self):
        a=self.change('a');b=self.change('b',parents=[self.cid(a[0])],previous=self.eid(a[0]),seq=2)
        self.receive(a);self.receive(b);return a,b
