"""UNEXECUTED candidate until a reviewed real package is provided. Public keys only.
Actual create/concurrent edit -> signed Store -> applied frontier -> fresh reopen.
The fixture provides two explicitly authorized editors; never invokes its double.
"""
import argparse,base64,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/document-apply',ROOT/'tests/product/auth-store',ROOT/'tests/product/space-auth']+[p for p in (ROOT/'experiments').iterdir() if p.is_dir()]:sys.path.insert(0,str(p))
from apply_support import ApplyTest,h
from product.wp04.application import DocumentApplier
from product.wp04.application_core import NodeMaterializationPort
from product.wp04.writer import SharedWriter
from product.wp04.contracts import SharedChangeError
from par_crypto.primitives import hashed

def run(manifest):
 core=NodeMaterializationPort(manifest);f=ApplyTest();f.setUp()
 try:
  def save(op,index,desc,previous=None):
   seq=int(desc['sequence']);oid,hdr,_,_=f.request(op=op,index=index,sequence=seq,previous=previous)
   raw=base64.b64decode(desc['change'],validate=True);hdr[7]=seq;hdr[10]=[bytes.fromhex(x) for x in desc['dependencies']];hdr[11]=len(raw);hdr[12]=bytes.fromhex(desc['hash'])
   writer=SharedWriter(f.writer(index=index),core,app_id=f.s.app,space_id=f.s.space,document_id=h('doc'),schema_id=h('schema'))
   r=writer.write(oid,hdr,raw);assert r['innerValidated'] and not r['applied'];return bytes.fromhex(r['commitId'])
  actors=[]
  for idx in (0,1):
   _,hdr,_,_=f.request(index=idx);actors.append(hashed('actor-id',[hdr[i] for i in (1,2,3,5,6)]).hex())
  first=core.make(kind='create',actor=actors[0],closure=[],expectedHeads=[],title='実core',body='共同文書')
  eid=save(1,0,first)
  left=core.make(kind='splice',actor=actors[0],closure=[first],expectedHeads=[first['hash']],index=0,deleteCount=0,text='A')
  right=core.make(kind='splice',actor=actors[1],closure=[first],expectedHeads=[first['hash']],index=0,deleteCount=0,text='B')
  le=save(2,0,left,eid);re=save(3,1,right)
  def applier():return DocumentApplier(f.db,core,f.s.devices[0]['cert'],h('real-apply-local-key'),app_id=f.s.app,space_id=f.s.space,document_id=h('doc'),epoch=1,schema_id=h('schema'))
  a=applier();r1=a.apply(b'A'*16,(le,),expected_revision=0);r2=a.apply(b'B'*16,(re,),expected_revision=1)
  assert r1['applied'] and r2['applied'];assert set(r2['heads'])=={left['hash'],right['hash']}
  note=a.read()['note'];pin=a.pin();n=f.db._storage.connection.execute('SELECT count(*) FROM document_apply_nonces').fetchone()[0]
  assert a.apply(b'B'*16,(re,),expected_revision=1)==r2
  assert f.db._storage.connection.execute('SELECT count(*) FROM document_apply_nonces').fetchone()[0]==n
  assert note['title']=='実core' and 'A' in note['body'] and 'B' in note['body']
  f.reopen();f.db.reactivate(f.s.space,f.s.devices[0]['secret']);a=applier();assert a.pin()==pin and a.read()['note']==note
  assert all(r[0]=='pending' for r in f.db._storage.connection.execute('SELECT state FROM envelopes'))
  assert f.db.audit()['valid']
  return {'result':'PASS','scope':'REAL_CORE_SAME_DATABASE_LOCAL_APPLICATION_PUBLIC_KEYS_ONLY','real_tests_executed':1,'engine':core.identity,'frontier_revision':2,'reopened':True,'ui_connected':False,'product_qualified':False}
 finally:f.doCleanups()
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--allow-legacy-test-libraries',action='store_true');a=p.parse_args()
 try:
  if not a.allow_legacy_test_libraries:raise SharedChangeError('TEST_LIBRARY_OPT_IN_REQUIRED')
  print(json.dumps(run(a.manifest),ensure_ascii=False))
 except Exception as e:
  code=getattr(e,'code',type(e).__name__);blocked=code in ('CORE_UNAVAILABLE','TEST_LIBRARY_OPT_IN_REQUIRED')
  print(json.dumps({'result':'BLOCKED' if blocked else 'FAIL','reason':code,'real_tests_executed':0 if blocked else 'INCOMPLETE','product_qualified':False}));sys.exit(78 if blocked else 1)
