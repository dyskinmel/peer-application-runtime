"""Separate Node process: no Python codec is used to produce Node's encoded bytes."""
import json, shutil, subprocess
from pathlib import Path
from wire_support import WireCase, ROOT, sample, BODIES
from test_wire_codec import VECTORS, BAD

def diagnostic(v):
 if type(v) is bytes:return {'$bytes':v.hex()}
 if type(v) is dict:return {'$map':[[str(k),diagnostic(x)] for k,x in sorted(v.items())]}
 if type(v) is int:return {'$uint':str(v)}
 if type(v) is list:return [diagnostic(x) for x in v]
 return v

def query(rows):
 node=shutil.which('node')
 if not node:raise AssertionError('Node is required; missing tool is NOT a skipped success')
 oracle=ROOT/'experiments/g0-wire/oracle.mjs'
 if not oracle.is_file():raise AssertionError('separate JavaScript comparison codec not implemented')
 p=subprocess.run([node,str(oracle)],input=''.join(json.dumps(x,ensure_ascii=True)+'\n' for x in rows),text=True,capture_output=True,timeout=20)
 if p.returncode:raise AssertionError(p.stderr[:1000])
 answers=[json.loads(line) for line in p.stdout.splitlines()]
 if len(answers)!=len(rows):raise AssertionError('oracle result count mismatch')
 return answers

class InteropTests(WireCase):
 def test_reference_vectors_both_paths(self):
  rows=[{'kind':'cbor','op':'encode','value':diagnostic(v)} for _,v,_ in VECTORS]
  for a,(_,v,h) in zip(query(rows),VECTORS):self.assertTrue(a['ok']);self.assertEqual(a['hex'],h)
 def test_reject_bytes_both_paths(self):
  rows=[{'kind':'cbor','op':'decode','hex':h} for _,h,_ in BAD]
  for a,(_,h,code) in zip(query(rows),BAD):self.assertFalse(a['ok']);self.assertEqual(a['code'],code)
 def test_u64_not_rounded(self):
  rows=[{'kind':'cbor','op':'encode','value':diagnostic(x)} for x in [2**53-1,2**53,2**53+1,2**64-1]]
  c=self.mod('codec')
  for a,x in zip(query(rows),[2**53-1,2**53,2**53+1,2**64-1]):self.assertEqual(a['hex'],c.encode(x).hex())
 def test_UTF8_BOM_is_not_stripped(self):
  c=self.mod('codec');wire=c.encode('\ufeffhello');a=query([{'kind':'cbor','op':'decode','hex':wire.hex()}])[0]
  self.assertTrue(a['ok']);self.assertEqual(a['hex'],wire.hex());self.assertEqual(a['value'],'\ufeffhello')
 def test_surrogate_encoder_rejected(self):
  a=query([{'kind':'cbor','op':'encode','value':'\ud800'}])[0];self.assertFalse(a['ok']);self.assertEqual(a['code'],'UTF8')
 def test_oracle_does_not_import_python_or_shared_ast(self):
  p=ROOT/'experiments/g0-wire/oracle.mjs';self.assertTrue(p.is_file());s=p.read_text()
  self.assertNotIn('child_process',s);self.assertNotIn('schema.py',s);self.assertNotIn('par-v1.cddl',s)
for code in BODIES:
 def roundtrip(self,code=code):
  f=self.mod('framing');frame=sample(code);wire=f.encode_frame(frame)
  rows=[{'kind':'frame','op':'encode','value':diagnostic(frame)},{'kind':'frame','op':'decode','hex':wire.hex()}]
  for a in query(rows):self.assertTrue(a['ok'],str(a));self.assertEqual(a['hex'],wire.hex());self.assertEqual(a['value'],diagnostic(frame))
 def rejects(self,code=code):
  f=sample(code);f[4][99]=0;wire=self.mod('codec').encode(f);wire=len(wire).to_bytes(4,'big')+wire
  a=query([{'kind':'frame','op':'decode','hex':wire.hex()}])[0];self.assertFalse(a['ok']);self.assertEqual(a['code'],'SCHEMA')
 setattr(InteropTests,'test_message_%03d_two_way'%code,roundtrip)
 setattr(InteropTests,'test_message_%03d_unknown'%code,rejects)
