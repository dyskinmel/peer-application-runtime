"""Exact versioned same-DB overlay and structural audits (not core evidence)."""
from pathlib import Path
from functools import lru_cache
import hashlib,json,sqlite3
from par_blob_store.backend import BlobStorage
from par_store.schema import objects
from par_wire.codec import decode
from .contracts import canonical,hex32,ids,require
PROFILE='par-document-apply-local-0035'
DDL=Path(__file__).with_name('application-schema.sql')
def sha(raw):return hashlib.sha256(raw).digest()
def sql():return BlobStorage.schema_sql()+'\n'+DDL.read_text()
def digest():return sha(BlobStorage.schema_profile()+b'\0document-apply-0035\0'+DDL.read_bytes())
@lru_cache(maxsize=1)
def expected():
 c=sqlite3.connect(':memory:')
 try:c.executescript(sql());return objects(c)
 finally:c.close()
def statements():
 buffer=''
 for line in DDL.read_text().splitlines(True):
  buffer+=line
  if sqlite3.complete_statement(buffer):yield buffer;buffer=''
 if buffer.strip():raise ValueError('incomplete SQL')
class ApplicationStorage(BlobStorage):
 USER_VERSION=4
 @classmethod
 def schema_sql(cls):return sql()
 @classmethod
 def schema_profile(cls):return digest()
 @classmethod
 def schema_matches(cls,c):return objects(c)==expected()

META_KEYS={'profile','storeGeneration','scope','scopeDigest','operationId','requestDigest','expectedRevision','revision','previousDigest','engine','evidenceClass','inputs','heads','authority','certificateDigest','reservationId','keyContext','coreRequestDigest','targets'}
def parse_record(raw):
 out=decode(raw);require(type(out) is dict and set(out)=={0,1,2},'APPLICATION_CORRUPT')
 require(type(out[0]) is bytes and type(out[1]) is bytes and len(out[1])==24 and type(out[2]) is bytes and len(out[2])>=16,'APPLICATION_CORRUPT')
 m=json.loads(out[0]);require(type(m) is dict and set(m)==META_KEYS and canonical(m)==out[0],'APPLICATION_CORRUPT')
 require(m['profile']==PROFILE and type(m['revision']) is int and 1<=m['revision']<=64 and type(m['expectedRevision']) is int and m['expectedRevision']==m['revision']-1,'APPLICATION_CORRUPT')
 require(m['evidenceClass'] in ('candidate','core-validated'),'APPLICATION_CORRUPT')
 for key in ('scopeDigest','requestDigest','previousDigest','certificateDigest','keyContext','coreRequestDigest'):require(hex32(m[key]),'APPLICATION_CORRUPT')
 for key in ('storeGeneration','operationId','reservationId'):require(type(m[key]) is str and len(m[key])==32 and bytes.fromhex(m[key]).hex()==m[key],'APPLICATION_CORRUPT')
 require(type(m['scope']) is dict and set(m['scope'])=={'app','space','document','epoch','schema'},'APPLICATION_CORRUPT')
 require(type(m['scope']['app']) is str and type(m['scope']['epoch']) is int and 1<=m['scope']['epoch']<2**64,'APPLICATION_CORRUPT')
 for k in ('space','document','schema'):require(hex32(m['scope'][k]),'APPLICATION_CORRUPT')
 require(sha(canonical(m['scope'])).hex()==m['scopeDigest'],'APPLICATION_CORRUPT')
 require(ids(m['heads'],128) and m['heads']==sorted(m['heads']) and ids(m['targets'],128) and m['targets']==sorted(m['targets']),'APPLICATION_CORRUPT')
 require(type(m['inputs']) is list and 1<=len(m['inputs'])<=128,'APPLICATION_CORRUPT')
 for r in m['inputs']:require(type(r) is dict and set(r)=={'envelopeId','innerId','digest'} and all(hex32(v) for v in r.values()),'APPLICATION_CORRUPT')
 require(m['inputs']==sorted(m['inputs'],key=lambda x:x['envelopeId']) and len({r['envelopeId'] for r in m['inputs']})==len(m['inputs']) and len({r['innerId'] for r in m['inputs']})==len(m['inputs']),'APPLICATION_CORRUPT')
 require(set(m['heads'])<={r['innerId'] for r in m['inputs']} and set(m['targets'])<={r['envelopeId'] for r in m['inputs']},'APPLICATION_CORRUPT')
 return m,out

def audit_records(c,generation):
 """May run inside the owner's transaction. Does not decrypt previews."""
 errors=[]
 try:
  inputs={(r['scope'],r['envelope_id']):dict(r) for r in c.execute('SELECT * FROM document_inputs')}
  frontiers={r['scope']:dict(r) for r in c.execute('SELECT * FROM document_frontiers')}
  events=list(c.execute('SELECT * FROM document_apply_events ORDER BY scope,revision'));last={};consumed=set();seen_inputs=set();first={};modes={}
  for e in events:
   require(sha(e['record'])==e['record_digest'],'APPLICATION_CORRUPT');m,o=parse_record(e['record']);scope=e['scope'];previous=last.get(scope)
   require(m['storeGeneration']==generation.hex() and m['scopeDigest']==scope.hex() and m['operationId']==e['operation_id'].hex() and m['revision']==e['revision'] and m['requestDigest']==e['request_digest'].hex() and m['previousDigest']==e['previous_digest'].hex(),'APPLICATION_CORRUPT')
   require(e['revision']==(previous[0]['revision']+1 if previous else 1) and e['previous_digest']==(previous[0]['record_digest'] if previous else b'\0'*32),'APPLICATION_CORRUPT')
   if scope in modes:require(modes[scope]==m['evidenceClass'],'APPLICATION_CORRUPT')
   modes[scope]=m['evidenceClass'];current=set()
   for x in m['inputs']:
    key=(scope,bytes.fromhex(x['envelopeId']));require(key in inputs,'APPLICATION_CORRUPT');r=inputs[key]
    require(r['inner_id'].hex()==x['innerId'] and sha(r['record'])==r['record_digest']==bytes.fromhex(x['digest']) and r['evidence_class']==m['evidenceClass'],'APPLICATION_CORRUPT')
    if key not in first:first[key]=e['operation_id'];require(r['first_event']==e['operation_id'],'APPLICATION_CORRUPT')
    current.add(key);seen_inputs.add(key)
   if previous:
    require({(scope,bytes.fromhex(x['envelopeId'])) for x in previous[1]['inputs']} < current,'APPLICATION_CORRUPT')
   nr=c.execute('SELECT * FROM document_apply_nonces WHERE reservation_id=?',(bytes.fromhex(m['reservationId']),)).fetchone()
   require(nr is not None and nr['scope']==scope and nr['nonce']==o[1] and nr['key_context']==bytes.fromhex(m['keyContext']) and nr['request_digest']==e['request_digest'] and nr['used_by']==e['operation_id'],'APPLICATION_CORRUPT')
   consumed.add(e['operation_id']);last[scope]=(dict(e),m)
  require(seen_inputs==set(inputs) and set(last)==set(frontiers),'APPLICATION_CORRUPT')
  for scope,(e,m) in last.items():
   f=frontiers[scope];require((f['revision'],f['operation_id'],f['record_digest'],f['heads'],f['evidence_class'])==(e['revision'],e['operation_id'],e['record_digest'],canonical(m['heads']),m['evidenceClass']),'APPLICATION_CORRUPT')
  require({r[0] for r in c.execute('SELECT used_by FROM document_apply_nonces WHERE used_by IS NOT NULL')}==consumed,'APPLICATION_CORRUPT')
 except Exception:errors.append('APPLICATION_CORRUPT')
 return errors
