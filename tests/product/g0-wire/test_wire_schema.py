import copy, json
from wire_support import WireCase,ROOT,sample,BODIES,ID
class SchemaTests(WireCase):
 def test_all_schema_rules_parsed(self):
  s=self.mod('schema').default_schema();self.assertGreater(len(s.rules),80);self.assertIn('recovery-descriptor',s.rules)
 def test_registry_exact_26(self):
  r=json.loads((ROOT/'baseline/spec-00.02.00/protocol/registry.json').read_text());self.assertEqual(set(BODIES),{x['code'] for x in r['messages']})
 def test_identifier_NUL_rejected(self):
  f=sample(1);f[4][0]='a\0b';self.reject('IDENTIFIER',self.mod('schema').validate_frame,f)
 def test_size_measured_in_utf8_bytes(self):
  s=self.mod('schema').default_schema();s.validate('short-text','é'*2048);self.reject('SCHEMA',s.validate,'short-text','é'*2049)
 def test_appid_requires_reverse_domain_ASCII(self):
  for name in ['é.example','single','a..b','a.-b','a.b-','a/b.example']:
   f=sample(1);f[4][0]=name;self.reject('IDENTIFIER',self.mod('schema').validate_frame,f)
 def test_integer_boolean_not_equal(self):
  f=sample(1);f[0]=True;self.reject('SCHEMA',self.mod('schema').validate_frame,f)
 def test_unknown_code(self):
  f=sample(1);f[1]=99;self.reject('MESSAGE_TYPE',self.mod('schema').validate_frame,f)
 def test_unknown_flags(self):
  f=sample(1);f[5]=1;self.reject('SCHEMA',self.mod('schema').validate_frame,f)
 def test_unknown_major(self):
  f=sample(1);f[0]=2;self.reject('SCHEMA',self.mod('schema').validate_frame,f)
 def test_missing_required_field(self):
  f=sample(1);del f[4][6];self.reject('SCHEMA',self.mod('schema').validate_frame,f)
 def test_closed_nested_catalog(self):
  f=sample(20);f[4][2][0][6]=None;self.reject('SCHEMA',self.mod('schema').validate_frame,f)
 def test_control_page_cursor_done_invariant(self):
  f=sample(13);f[4][2]=ID;self.reject('PAGE_STATE',self.mod('schema').validate_frame,f)
 def test_nonfinal_empty_page_rejected(self):
  f=sample(20);f[4][3]=False;f[4][1]=ID;f[4][2]=[];self.reject('PAGE_STATE',self.mod('schema').validate_frame,f)
 def test_duplicate_hello_lists_rejected(self):
  f=sample(1);f[4][4]=[1,1];self.reject('NEGOTIATION',self.mod('schema').validate_frame,f)
 def test_space_open_genesis_matches_scope(self):
  f=sample(10);f[4][0]=b'z'*32;self.reject('SPACE_BINDING',self.mod('schema').validate_frame,f)
 def test_dependencies_bounded(self):
  s=self.mod('schema');f=sample(21);f[4][1]=[i.to_bytes(32,'big') for i in range(128)];s.validate_frame(f);f[4][1].append(ID);self.reject('SCHEMA',s.validate_frame,f)
 def test_schema_no_partial_parse(self):self.reject('CDDL_UNSUPPORTED',self.mod('schema').parse_cddl,'x = uint .foo 12')
 def test_schema_duplicate_rule(self):self.reject('CDDL_SYNTAX',self.mod('schema').parse_cddl,'x = uint\nx = bstr')
 def test_signed_wrapper_structure_not_authentication(self):
  self.mod('schema').default_schema().validate('signed-object',{0:b'x',1:ID,2:b'x'*64})
for code in BODIES:
 def accept(self,code=code):
  c=self.mod('framing'); f=sample(code);wire=c.encode_frame(f);self.assertEqual(c.decode_frame(wire),f)
 def unknown(self,code=code):
  f=sample(code);f[4][99]=0;self.reject('SCHEMA',self.mod('schema').validate_frame,f)
 def id_length(self,code=code):
  f=sample(code);f[2]=b'x'*15;self.reject('SCHEMA',self.mod('schema').validate_frame,f)
 setattr(SchemaTests,'test_message_%03d_roundtrip'%code,accept)
 setattr(SchemaTests,'test_message_%03d_unknown_field'%code,unknown)
 setattr(SchemaTests,'test_message_%03d_request_id'%code,id_length)
