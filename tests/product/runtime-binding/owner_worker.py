"""Test-only owned SQLite process. Writes ONLY synthetic fixture data in a temp dir.
Not shipped as a production runtime transport; never accepts DB paths or secrets.
"""
import json,sys
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True
for p in [R,R/'tests/product/auth-store',R/'tests/product/space-auth']+[p for p in (R/'experiments').iterdir() if p.is_dir()]:sys.path.insert(0,str(p))
from auth_store_support import AuthStoreTest,h
from product.runtime_read.observer import StoreObserver

t=AuthStoreTest();t.setUp()
try:
 t.start();req=t.request();obs=StoreObserver(t.db,app_id=t.s.app,space_id=t.s.space,document_id=h('doc'),device_id=t.s.devices[0]['id'],local_secret=h('local-secret'))
 for line in sys.stdin:
  try:
   r=json.loads(line)
   if type(r) is not dict or set(r)!={'action','operationId'}:raise ValueError('request')
   if r['action']=='commit-fixture':
    t.writer().write(*req);out={'syntheticWrite':True}
   elif r['action']=='inspect':
    op=req[0] if r['operationId'] is None else bytes.fromhex(r['operationId'])
    out=obs.observe(op)
   elif r['action']=='authority-update':t.same_epoch();out={'updated':True}
   elif r['action']=='stop':break
   else:raise ValueError('action')
  except Exception as e:out={'error':getattr(e,'code','TEST_WORKER_ERROR')}
  print(json.dumps(out),flush=True)
finally:t.doCleanups()
