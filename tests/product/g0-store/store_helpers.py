from __future__ import annotations
import hashlib, importlib, importlib.util, json, sqlite3, sys, tempfile, unittest
from dataclasses import replace
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
for p in ('experiments/g0-store','experiments/g0-wire'):
    sys.path.insert(0, str(ROOT/p))

def h(value): return hashlib.sha256(value.encode() if isinstance(value,str) else value).digest()
SPACE=h('space'); OBJECT=h('object'); ACTOR=h('actor'); GENERATION=b'a'*16; CONTROL=h('control'); KEY=h('key')

class StoreCase(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('par_store.store'), 'G0 store contract has no implementation yet')
        self.api=importlib.import_module('par_store.store')
        self.model=importlib.import_module('par_store.model')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'store'
        self.s=self.api.Store.create(self.root, allow_unpatched_sqlite=True)
        self.addCleanup(lambda:self.s.close())
        self.s.configure_space(SPACE,'org.example.notes',1,CONTROL)
    def prepare(self, n=1, *, sequence=1, previous=None, **overrides):
        op=n.to_bytes(16,'big');inp=h('input-'+str(n))
        reservation=self.s.reserve_nonce(op,inp,KEY,n.to_bytes(24,'big'))
        p=self.model.PreparedCommit(operation_id=op,input_digest=inp,space_id=SPACE,object_id=OBJECT,
            actor_id=ACTOR,actor_generation=GENERATION,epoch=1,sequence=sequence,previous_envelope=previous,
            change_hash=h('change-'+str(n)),reservation_id=reservation,envelope=b'opaque-envelope-'+str(n).encode(),
            encrypted_cache=b'opaque-cache-'+str(n).encode(),encrypted_receipt=b'opaque-receipt-'+str(n).encode(),
            dependencies=(),blocks=())
        return replace(p,**overrides)
    def commit(self,p):return self.s.commit(p,fencing_token=self.s.fencing_token)
    def err(self, code, fn, *a, **kw):
        with self.assertRaises(Exception) as cm:fn(*a,**kw)
        self.assertEqual(getattr(cm.exception,'code',None),code,repr(cm.exception));return cm.exception
    def scalar(self, sql, args=()):return self.s.connection.execute(sql,args).fetchone()[0]
    def query(self,sql,args=()):return self.s.connection.execute(sql,args).fetchall()
    def reopen(self):
        self.s.close();self.s=self.api.Store.open(self.root,allow_unpatched_sqlite=True)
        return self.s
