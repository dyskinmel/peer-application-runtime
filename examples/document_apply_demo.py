#!/usr/bin/env python3
"""Public synthetic semantic port + real signatures/AEAD/SQLite, not CRDT demo."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/document-apply',ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+[p for p in (ROOT/'experiments').iterdir() if p.is_dir()]:sys.path.insert(0,str(p))
from apply_support import ApplyTest

def main():
 f=ApplyTest();f.setUp()
 try:
  a,h=f.saved();b,_=f.saved(2,sequence=2,previous=a,deps=[h]);result=f.call([b]);pin=f.a.pin();counts=f.nums()
  assert f.call([b])==result and f.nums()==counts
  f.reopen();f.db.reactivate(f.s.space,f.s.devices[0]['secret']);f.a=f.make(expected_pin=pin);view=f.a.read()
  assert not view['applied'] and not view['innerValidated'] and view['revision']==1
  print(json.dumps({'result':'PASS','scope':'EXPLICIT_SYNTHETIC_SEMANTICS_REAL_STORE','candidate':result,'reopened':True,'retry_did_not_reencrypt':True,'envelope_states':[r[0] for r in f.db._storage.connection.execute('SELECT state FROM envelopes')],'real_core_executed':False,'ui_connected':False},ensure_ascii=False,indent=2))
 finally:f.doCleanups()
if __name__=='__main__':main()
