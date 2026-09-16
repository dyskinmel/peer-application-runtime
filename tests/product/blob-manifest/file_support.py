"""Synthetic fixture composition. Test keys must never be used for user data."""
import importlib,hashlib,os,tempfile,unittest
from pathlib import Path
from dataclasses import replace
from blob_support import BlobTest,h
from par_wire.codec import encode,decode
from par_crypto import objects
from par_store.errors import StoreError

class FileTest(BlobTest):
    def setUp(self):
        super().setUp()
        try:self.file=importlib.import_module('par_file')
        except ModuleNotFoundError:self.file=None
        self.assertTrue(self.file is not None and hasattr(self.file,'FileWriter'),'durable file writer not implemented')
        self.source=Path(self.tmp.name)/'source';self.output=Path(self.tmp.name)/'output'
        self.data=b'whole-file synthetic plaintext\n'*10000
        self.source.write_bytes(self.data)
    def fw(self,index=0,observer=None,random_source=None,**kw):
        d=self.s.devices[index]
        return self.file.FileWriter(self.db,d['cert'],self.s.secret,d['seed'],h('local-secret'),observer=observer,random_source=random_source,**kw)
    def stage(self,w=None,request=None,**kw):
        return (w or self.fw()).stage(*(request or self.request()),self.source,name=kw.pop('name','資料.txt'),media_type=kw.pop('media_type','text/plain'),**kw)
    def write(self,w=None,request=None):
        w=w or self.fw();req=request or self.request();return w.commit(self.stage(w,req),*req[1:])
    def export(self,eid,**kw):return self.file.export_file(self.db,eid,self.s.secret,self.output,**kw)
    def reject_file(self,code,fn):
        with self.assertRaises(Exception) as cm:fn()
        self.assertTrue(hasattr(cm.exception,'code'),repr(cm.exception))
        if code is not None:self.assertEqual(cm.exception.code,code)
