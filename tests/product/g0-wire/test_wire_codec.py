import math
from wire_support import WireCase

VECTORS=[('zero',0,'00'),('23',23,'17'),('24',24,'1818'),('255',255,'18ff'),('256',256,'190100'),('u16',65535,'19ffff'),('u32',2**32-1,'1affffffff'),('u64',2**64-1,'1bffffffffffffffff'),('false',False,'f4'),('true',True,'f5'),('null',None,'f6'),('empty_bytes',b'','40'),('bytes',b'\x00\xff','4200ff'),('text','IETF','6449455446'),('unicode','水','63e6b0b4'),('array',[1,2,3],'83010203'),('map',{1:'a',10:False},'a20161610af4')]
BAD=[('empty','','TRUNCATED'),('truncated_uint','1b00','TRUNCATED'),('nonminimal_uint','1817','NON_MINIMAL'),('nonminimal_size','5800','NON_MINIMAL'),('utf8','61ff','UTF8'),('surrogate','63eda080','UTF8'),('overlong','62c080','UTF8'),('trailing','0000','TRAILING'),('duplicate','a200010002','MAP_ORDER'),('unsorted','a201000001','MAP_ORDER'),('bool_key','a1f400','MAP_KEY'),('text_key','a1616100','MAP_KEY'),('indefinite_array','9f00ff','INDEFINITE'),('indefinite_map','bfff','INDEFINITE'),('indefinite_bytes','5fff','INDEFINITE'),('tag','c001','FORBIDDEN_TYPE'),('float','fa3f800000','FORBIDDEN_TYPE'),('undefined','f7','FORBIDDEN_TYPE'),('negative','20','FORBIDDEN_TYPE'),('simple','e0','FORBIDDEN_TYPE'),('reserved','1c','RESERVED')]
class CodecTests(WireCase):
 def test_bool_cannot_alias_integer_map_key(self):self.reject('MAP_KEY',self.mod('codec').encode,{True:1})
 def test_encoder_forbids_negative(self):self.reject('FORBIDDEN_TYPE',self.mod('codec').encode,-1)
 def test_encoder_forbids_over_u64(self):self.reject('UINT_RANGE',self.mod('codec').encode,2**64)
 def test_encoder_forbids_float(self):self.reject('FORBIDDEN_TYPE',self.mod('codec').encode,1.0)
 def test_encoder_forbids_surrogate(self):self.reject('UTF8',self.mod('codec').encode,'\ud800')
 def test_map_order_is_canonical(self):self.assertEqual(self.mod('codec').encode({24:0,1:0}),bytes.fromhex('a20100181800'))
 def test_map_decoder_does_not_coerce_types(self):
  c=self.mod('codec');self.assertIs(type(c.decode(b'\x01')),int);self.assertIs(type(c.decode(b'\xf5')),bool)
 def test_depth_limit(self):
  c=self.mod('codec');self.assertEqual(c.decode(b'\x81'*32+b'\x00'),self._nest(32));self.reject('DEPTH',c.decode,b'\x81'*33+b'\x00')
 def _nest(self,n):
  v=0
  for _ in range(n):v=[v]
  return v
 def test_encoder_detects_cycle(self):
  a=[];a.append(a);self.reject('CYCLE',self.mod('codec').encode,a)
 def test_declared_huge_byte_string(self):self.reject('LIMIT',self.mod('codec').decode,b'\x5b'+b'\xff'*8)
 def test_declared_huge_array(self):self.reject('LIMIT',self.mod('codec').decode,b'\x9b'+b'\xff'*8)
 def test_node_budget_distinct_from_invalid(self):self.reject('RESOURCE_LIMIT',self.mod('codec').decode,bytes.fromhex('8400000000'),max_nodes=3)
 def test_encoder_aggregate_limit(self):self.reject('LIMIT',self.mod('codec').encode,[b'a'*10,b'b'*10],max_bytes=20)
 def test_no_decode_of_arbitrary_python_types(self):
  with self.assertRaises(TypeError):self.mod('codec').decode('00')
for name,value,h in VECTORS:
 def test(self,v=value,h=h):
  c=self.mod('codec');self.assertEqual(c.encode(v).hex(),h);self.assertEqual(c.decode(bytes.fromhex(h)),v)
 setattr(CodecTests,'test_vector_'+name,test)
for name,h,code in BAD:
 def test(self,h=h,code=code):self.reject(code,self.mod('codec').decode,bytes.fromhex(h))
 setattr(CodecTests,'test_reject_'+name,test)
