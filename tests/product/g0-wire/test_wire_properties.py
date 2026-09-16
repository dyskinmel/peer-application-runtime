"""Deterministic differential samples; not an exhaustive fuzz or security audit."""
import hashlib,json,random
from wire_support import WireCase,ROOT,sample,BODIES
from test_wire_interop import query,diagnostic

class PropertyTests(WireCase):
 def test_fixed_seed_512_valid_values(self):
  c=self.mod('codec');rng=random.Random(2026090504)
  def gen(depth):
   choices=5 if depth>=4 else 7;kind=rng.randrange(choices)
   if kind==0:return rng.choice([0,23,24,255,256,65535,2**32,2**53+1,2**64-1,rng.getrandbits(64)])
   if kind==1:return rng.choice([True,False,None])
   if kind==2:return rng.randbytes(rng.randrange(64))
   if kind==3:return ''.join(rng.choice('ab水é\ufeff\0𝄞') for _ in range(rng.randrange(20)))
   if kind==4:return []
   if kind==5:return [gen(depth+1) for _ in range(rng.randrange(8))]
   return {k:gen(depth+1) for k in rng.sample(range(100),rng.randrange(8))}
  values=[gen(0) for _ in range(512)]
  answers=query([{'kind':'cbor','op':'encode','value':diagnostic(v)} for v in values])
  for value,answer in zip(values,answers):
   with self.subTest(digest=hashlib.sha256(c.encode(value)).hexdigest()):
    self.assertTrue(answer['ok'],str(answer));self.assertEqual(bytes.fromhex(answer['hex']),c.encode(value));self.assertEqual(c.decode(bytes.fromhex(answer['hex'])),value)
 def test_fixed_seed_2048_mutated_frames(self):
  f=self.mod('framing');rng=random.Random(2026090517);source=[f.encode_frame(sample(i)) for i in BODIES];cases=[]
  for i in range(2048):
   v=bytearray(source[rng.randrange(len(source))]);mode=i%4
   if mode==0:v[rng.randrange(len(v))]^=1<<rng.randrange(8)
   elif mode==1:v=v[:rng.randrange(len(v))]
   elif mode==2:v+=rng.randbytes(1+rng.randrange(5))
   else:
    p=rng.randrange(4,len(v));v[p:p+1]=rng.randbytes(1);v[:4]=(len(v)-4).to_bytes(4,'big')
   cases.append(bytes(v))
  answers=query([{'kind':'frame','op':'decode','hex':b.hex()} for b in cases]);accepted=0;rejected=0
  for i,(b,a) in enumerate(zip(cases,answers)):
   try:v=f.decode_frame(b);ok=True
   except ValueError:ok=False
   with self.subTest(sample=i):
    self.assertEqual(a['ok'],ok,str(a))
    if ok:self.assertEqual(f.encode_frame(v),b);self.assertEqual(a['hex'],b.hex());accepted+=1
    else:rejected+=1
  self.assertGreater(accepted,0);self.assertGreater(rejected,0)
 def test_every_truncation_of_each_frame(self):
  f=self.mod('framing')
  for code in BODIES:
   wire=f.encode_frame(sample(code))
   for end in range(len(wire)):
    with self.subTest(code=code,end=end):
     with self.assertRaises(ValueError):f.decode_frame(wire[:end])
 def test_public_baseline_wire_cases(self):
  f=self.mod('framing');c=self.mod('codec');data=json.loads((ROOT/'baseline/spec-00.02.00/fixtures/wire-samples.json').read_text())
  for row in data['cases']:
   fn=f.decode_frame if row['scope']=='frame' else c.decode;wire=bytes.fromhex(row['hex'])
   with self.subTest(case=row['id']):
    if row['expected']=='REJECT':
     with self.assertRaises(ValueError):fn(wire)
    else:self.assertEqual(f.encode_frame(fn(wire)),wire)
 def test_control_page_exact_1MiB_and_next_byte(self):
  f=self.mod('framing');c=self.mod('codec');v=sample(13);v[4][1]=[b'x'*65536 for _ in range(15)]+[b'x']
  gap=1048576-len(c.encode(v));v[4][1][-1]=b'x'*(gap-2+1)
  # Increasing byte-string length from 1 to >255 adds 2 header bytes.
  wire=f.encode_frame(v);self.assertEqual(len(wire),1048580);self.assertEqual(f.decode_frame(wire),v)
  v[4][1][-1]+=b'x';self.reject('LIMIT',f.encode_frame,v)
 def test_portable_schema_positive_witnesses(self):
  schema=self.mod('schema').default_schema()
  def witness(n):
   k=n[0]
   if k=='ref':
    if n[1]=='uint':return 0
    if n[1]=='bstr':return b''
    if n[1]=='tstr':return ''
    if n[1]=='bool':return False
    if n[1]=='null':return None
    return witness(schema.rules[n[1]])
   if k in ('literal','range'):return n[1]
   if k=='union':return witness(n[1][0])
   if k=='size':
    v=witness(n[1]);return b'x'*n[2] if type(v)is bytes else 'x'*n[2]
   if k=='array':return [witness(n[3]) for _ in range(n[1])]
   if k=='map':return {a:witness(t) for a,opt,t in n[1] if not opt}
   self.fail('unknown grammar')
  # Shape witnesses only. They are not correctly signed/authenticated objects.
  for name,node in schema.rules.items():
   with self.subTest(rule=name):schema.validate(name,witness(node))

 def test_each_body_field_type_mutation(self):
  c=self.mod('codec');s=self.mod('schema');cases=[]
  for code in BODIES:
   for field in BODIES[code]:
    v=sample(code);v[4][field]=0 if type(v[4][field]) is bool else False
    with self.subTest(code=code,field=field):self.reject('SCHEMA',s.validate_frame,v)
    b=c.encode(v);cases.append(len(b).to_bytes(4,'big')+b)
  for i,a in enumerate(query([{'kind':'frame','op':'decode','hex':b.hex()} for b in cases])):
   with self.subTest(case=i):self.assertFalse(a['ok']);self.assertEqual(a['code'],'SCHEMA')
 def test_both_paths_depth_boundary(self):
  cases=[b'\x81'*32+b'\x00',b'\x81'*33+b'\x00']
  answers=query([{'kind':'cbor','op':'decode','hex':b.hex()} for b in cases]);self.assertTrue(answers[0]['ok']);self.assertFalse(answers[1]['ok']);self.assertEqual(answers[1]['code'],'DEPTH')
 def test_unknown_outer_field_both_paths(self):
  c=self.mod('codec');f=self.mod('framing');v=sample(1);v[99]=0;b=c.encode(v);wire=len(b).to_bytes(4,'big')+b
  self.reject('SCHEMA',f.decode_frame,wire);self.assertFalse(query([{'kind':'frame','op':'decode','hex':wire.hex()}])[0]['ok'])
