"""Synthetic local reader/editor fixtures, no user keys or outbound traffic."""
import importlib,hashlib
from pathlib import Path
from dataclasses import replace
from file_support import FileTest
from auth_support import h,control_id,epoch_bundle
from par_wire.codec import encode,decode
from par_crypto.primitives import domain,hashed
from par_crypto import objects
class RecoveryTest(FileTest):
    def setUp(self):
        super().setUp()
        try:self.rc=importlib.import_module('par_recovery')
        except ModuleNotFoundError:self.rc=None
        self.assertTrue(self.rc is not None and hasattr(self.rc,'collect'), 'recipient recovery closure is not implemented')
        self.start();self.receipt=self.write();self.reader=self.s.devices[1]
        self.grant=self.rc.Grant(self.reader['cert'],self.b['packages'][self.reader['id']],tuple(self.b['ids']),self.b['manifest'],tuple(sorted(self.b['seeds'].items())))
    def collect(self,**kw):
        return self.rc.collect(self.db,self.s.space,kw.pop('roots',(self.receipt.envelope_id,)),kw.pop('grant',self.grant),kw.pop('certificate',self.s.devices[0]['cert']),kw.pop('seed',self.s.devices[0]['seed']),**kw)
    def pin(self,bundle):
        return self.rc.Pin(self.s.app,self.s.space,control_id(self.b['raw']),1,1,self.reader['id'],self.reader['cid'],(self.receipt.envelope_id,),self.rc.index_id(bundle.index))
    def verify(self,bundle,pin=None,secret=None):
        return self.rc.verify(bundle,pin or self.pin(bundle),self.p,secret or self.reader['secret'])
    def reject_rc(self,code,fn):
        with self.assertRaises(self.rc.RecoveryError) as cm:fn()
        if code:self.assertEqual(cm.exception.code,code)
    def rewrite(self,bundle,change):
        from par_recovery.contract import sign_index
        v=decode(decode(bundle.index,max_bytes=524288)[0],max_bytes=524288);change(v)
        return self.rc.Bundle(sign_index(self.p,self.s.devices[0]['seed'],v),dict(bundle.objects))
    def publish(self,bundle):
        root=Path(self.tmp.name)/'provider';self.rc.publish_bundle(bundle,root);return root
    def patch_object(self,bundle,kind,mutate):
        from par_recovery.contract import sign_index
        v=decode(decode(bundle.index,max_bytes=524288)[0],max_bytes=524288)
        d=next(d for d in v[15] if d[1]==kind);old=d[0];raw=mutate(bundle.objects[old]);new=self.rc.object_id(kind,raw)
        def rewrite_refs(x):
            if type(x) is bytes:return new if x==old else x
            if type(x) is list:return [rewrite_refs(y) for y in x]
            if type(x) is dict:return {k:rewrite_refs(y) for k,y in x.items()}
            return x
        v=rewrite_refs(v);d=next(d for d in v[15] if d[0]==new);d[2]=len(raw);v[15].sort()
        data=dict(bundle.objects);data.pop(old);data[new]=raw
        return self.rc.Bundle(sign_index(self.p,self.s.devices[0]['seed'],v),data)
    def trusted_file(self,bundle):
        p=self.pin(bundle)
        raw=encode([p.app,p.space,p.head,p.sequence,p.epoch,p.recipient_id,p.certificate_id,list(p.roots),p.index_id])
        f=Path(self.tmp.name)/'trusted-pin.cbor';f.write_bytes(raw);return f
