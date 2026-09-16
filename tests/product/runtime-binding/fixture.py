"""Public synthetic fixture ONLY, not a production DB opening or IPC service."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+[p for p in (ROOT/'experiments').iterdir() if p.is_dir()]:sys.path.insert(0,str(p))
from auth_store_support import AuthStoreTest,h
from product.runtime_read.observer import StoreObserver

def fixture():
 t=AuthStoreTest();t.setUp()
 try:
  t.start();req=t.request();reader=StoreObserver(t.db,app_id=t.s.app,space_id=t.s.space,document_id=h('doc'),device_id=t.s.devices[0]['id'],local_secret=h('local-secret'))
  unknown=reader.observe(req[0]);t.writer().write(*req);committed=reader.observe(req[0]);t.same_epoch();changed=reader.observe(req[0]);reader.close()
  t.reopen();reader=StoreObserver(t.db,app_id=t.s.app,space_id=t.s.space,document_id=h('doc'),device_id=t.s.devices[0]['id'],local_secret=h('local-secret'));reopened=reader.observe(req[0]);reader.close()
  return {'scope':'REAL_LOCAL_SQLITE_SYNTHETIC_DATA_NOT_CRDT','unknown':unknown,'committed':committed,'changed':changed,'reopened':reopened}
 finally:t.doCleanups()
if __name__=='__main__':print(json.dumps(fixture(),ensure_ascii=False))
