#!/usr/bin/env python3
"""Demonstrates real Store boundaries with an explicitly synthetic semantic port.
Never presents this fixture as Automerge data or a successful merge.
"""
import json,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for p in [R,R/'tests/product/shared-document',R/'tests/product/auth-store',R/'tests/product/space-auth']+[p for p in (R/'experiments').iterdir() if p.is_dir()]:sys.path.insert(0,str(p))
from auth_store_support import AuthStoreTest,h
from test_writer import ContractPort
from product.wp04.writer import SharedWriter
from product.wp04.contracts import SharedChangeError
f=AuthStoreTest();f.setUp()
try:
 f.start();op,header,payload,_=f.request();core=ContractPort()
 def new(allow=False):return SharedWriter(f.writer(),core,app_id=f.s.app,space_id=f.s.space,document_id=h('doc'),schema_id=h('schema'),allow_contract_double=allow)
 try:new().write(op,header,payload);raise AssertionError('default accepted fake core')
 except SharedChangeError as e:assert e.code=='CORE_NOT_REAL'
 assert f.count('issued_nonces')==0
 w=new(True);a=w.write(op,header,payload);n=f.count('issued_nonces');b=w.write(op,header,payload);assert a==b and f.count('issued_nonces')==n
 print(json.dumps({'scope':'SYNTHETIC_SEMANTIC_PORT_REAL_ENCRYPTED_STORE','default_test_port_rejected':True,'receipt':a,'retry_same':a==b,'real_automerge_executed':False},indent=2))
finally:f.doCleanups()
