import hashlib,json
from wire_support import WireCase,ROOT,BODIES
from test_wire_interop import query
class GoldenTests(WireCase):
 def corpus(self):
  p=ROOT/'experiments/g0-wire/fixtures/golden-frames.json';self.assertTrue(p.is_file(),'reviewable golden corpus not yet recorded');return json.loads(p.read_text())
 def test_exact_26_frozen_vectors(self):
  obj=self.corpus();self.assertEqual(len(obj['frames']),26);self.assertEqual({r['message_code'] for r in obj['frames']},set(BODIES))
  f=self.mod('framing')
  for row in obj['frames']:
   wire=bytes.fromhex(row['hex']);self.assertEqual(hashlib.sha256(wire).hexdigest(),row['sha256']);self.assertEqual(f.encode_frame(f.decode_frame(wire)),wire)
 def test_javascript_matches_frozen_vectors(self):
  rows=self.corpus()['frames'];answers=query([{'kind':'frame','op':'decode','hex':r['hex']} for r in rows])
  for row,answer in zip(rows,answers):self.assertTrue(answer['ok']);self.assertEqual(answer['hex'],row['hex'])
 def test_profile_digest_recomputes(self):
  p=ROOT/'experiments/g0-wire/profile.json';self.assertTrue(p.is_file(),'experiment profile not yet pinned')
  obj=json.loads(p.read_text());entries=[]
  for rel in obj['inputs']:
   entries.append([rel,hashlib.sha256((ROOT/rel).read_bytes()).digest()])
  value=['PAR-EXPERIMENT-PROFILE',1,entries]
  self.assertEqual(hashlib.sha256(self.mod('codec').encode(value)).hexdigest(),obj['sha256'])
  self.assertFalse(obj['frozen']);self.assertFalse(obj['production_qualified'])
