"""Real core + real signed Store. Uses PUBLIC test keys and old-library opt-in.
Not imported into contract-test PASS counts. Executed only by explicit real probe.
"""
from pathlib import Path
import argparse,base64,json,sys
ROOT=Path(__file__).resolve().parents[2];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+[p for p in (ROOT/'experiments').iterdir() if p.is_dir()]:sys.path.insert(0,str(p))
from product.wp04.core_port import NodeCorePort
from product.wp04.writer import SharedWriter
from product.wp04.contracts import ChangeInput,core_request,Dependency,SharedChangeError
from par_crypto.primitives import hashed
from auth_store_support import AuthStoreTest,h

def run(manifest):
 core=NodeCorePort(manifest,timeout=30);f=AuthStoreTest();f.setUp()
 try:
  f.start();writer=SharedWriter(f.writer(),core,app_id=f.s.app,space_id=f.s.space,document_id=h('doc'),schema_id=h('schema'))
  op,hdr,_,_=f.request();actor=hashed('actor-id',[hdr[i] for i in (1,2,3,5,6)]).hex()
  first=core.make(kind='create',actor=actor,closure=[],expectedHeads=[],title='共有',body='あ😀Z')
  def bind(base,d):
   b=base64.b64decode(d['change'],validate=True);v=dict(base);v[7]=int(d['sequence']);v[10]=[bytes.fromhex(x) for x in d['dependencies']];v[11]=len(b);v[12]=bytes.fromhex(d['hash']);return v,b
  h1,b1=bind(hdr,first);r1=writer.write(op,h1,b1);assert r1['innerValidated'] and not r1['applied']
  count=f.count('issued_nonces');assert writer.write(op,h1,b1)==r1;assert f.count('issued_nonces')==count
  second=core.make(kind='splice',actor=actor,closure=[first],expectedHeads=[first['hash']],index=1,deleteCount=1,text='🌸')
  op2,h2,_,_=f.request(op=2,sequence=2,previous=bytes.fromhex(r1['commitId']));h2,b2=bind(h2,second)
  r2=writer.write(op2,h2,b2);assert r2['innerValidated'] and not r2['applied'];f.db.audit()
  # Reopen actual encrypted Store; no parent core document or cache is reused.
  f.reopen();f.db.provide_membership(f.s.space,f.b['pages']);f.activate()
  fresh=NodeCorePort(manifest,timeout=30)
  newwriter=SharedWriter(f.writer(),fresh,app_id=f.s.app,space_id=f.s.space,document_id=h('doc'),schema_id=h('schema'))
  assert newwriter.write(op2,h2,b2)==r2
  dep=Dependency(bytes.fromhex(r1['commitId']),ChangeInput.create(h1,b1,schema_id=h('schema')))
  report=fresh.validate(core_request(ChangeInput.create(h2,b2,schema_id=h('schema')),(dep,)));assert report['note']['body']=='あ🌸Z'
  assert all(row[0]=='pending' for row in f.db._storage.connection.execute('SELECT state FROM envelopes'))
  return {'result':'PASS','scope':'REAL_CORE_AUTH_STORE_CANDIDATE_PUBLIC_KEYS_ONLY','engine':fresh.identity,'commits':2,'reopened':True,'persistedApplied':False}
 finally:f.doCleanups()
if __name__=='__main__':
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('--manifest',type=Path,required=True);a.add_argument('--allow-legacy-test-libraries',action='store_true');ns=a.parse_args()
 try:
  if not ns.allow_legacy_test_libraries:raise SharedChangeError('TEST_LIBRARY_OPT_IN_REQUIRED')
  print(json.dumps(run(ns.manifest),ensure_ascii=False,indent=2))
 except Exception as e:
  blocked=getattr(e,'code','') in ('CORE_UNAVAILABLE','TEST_LIBRARY_OPT_IN_REQUIRED');print(json.dumps({'result':'BLOCKED' if blocked else 'FAIL','code':getattr(e,'code',type(e).__name__),'realCoreQualified':False}));sys.exit(78 if blocked else 1)
