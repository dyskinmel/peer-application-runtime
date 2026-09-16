import importlib,importlib.util,tempfile,unittest
from pathlib import Path
class MatrixLedgerTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(importlib.util.find_spec('product.wp13.par_matrix.campaign'),'matrix campaign missing')
  self.M=importlib.import_module('product.wp13.par_matrix.campaign').MatrixCampaign
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'campaign'
  self.binding={'source':'1'*64,'environment':'2'*64};self.config={'seed':55,'cells':[{'participants':2,'max_active':1,'rounds_per_peer':1},{'participants':8,'max_active':4,'rounds_per_peer':2}]}
 def create(self):
  c=self.M.create(self.root,self.binding,self.config);self.addCleanup(c.close);return c
 def row(self,i):return {'round':i,'status':'PASS',**self.config['cells'][i],'child_exit_codes':[0]*self.config['cells'][i]['participants'],'readonly_unchanged':True,'violations':[]}
 def test_correct_child_exit_cardinality_and_resume(self):
  c=self.create();c.begin(0);c.finish(0,self.row(0));c.seal([[0,0]]);pin=c.pin();c.close()
  c=self.M.open(self.root,self.binding,self.config,pin=pin);self.addCleanup(c.close);self.assertEqual(c.state()['next_round'],1);c.begin(1);c.finish(1,self.row(1));c.seal([[0]*8]);self.assertEqual(c.state()['result'],'PASS')
 def test_no_seal_no_pass(self):
  c=self.create();c.begin(0);c.finish(0,self.row(0));self.assertEqual(c.state()['result'],'UNSEALED')
 def test_wrong_exit_count_refused(self):
  c=self.create();c.begin(0);c.finish(0,self.row(0))
  with self.assertRaisesRegex(ValueError,'FINALIZATION'):c.seal([[0]])
 def test_nonzero_exit_cannot_be_pass(self):
  c=self.create();c.begin(0);r=self.row(0);r['child_exit_codes']=[0,1]
  with self.assertRaisesRegex(ValueError,'FINALIZATION'):c.finish(0,r)
 def test_wrong_participant_result_refused(self):
  c=self.create();c.begin(0);r=self.row(0);r['participants']=8
  with self.assertRaisesRegex(ValueError,'MATRIX_CELL'):c.finish(0,r)
 def test_missing_preservation_not_pass(self):
  c=self.create();c.begin(0);r=self.row(0);r.pop('readonly_unchanged')
  with self.assertRaisesRegex(ValueError,'READONLY'):c.finish(0,r)
 def test_different_config_cannot_resume(self):
  c=self.create();c.close();self.config['cells'][0]['max_active']=2
  with self.assertRaisesRegex(ValueError,'BINDING'):self.M.open(self.root,self.binding,self.config)
 def test_changed_source_cannot_resume(self):
  c=self.create();c.close();self.binding['source']='3'*64
  with self.assertRaisesRegex(ValueError,'BINDING'):self.M.open(self.root,self.binding,self.config)
 def test_interrupted_begin_not_replayed(self):
  c=self.create();c.begin(0);c.close();c=self.M.open(self.root,self.binding,self.config);self.addCleanup(c.close)
  self.assertEqual(c.state()['result'],'INTERRUPTED')
  with self.assertRaisesRegex(ValueError,'ACTIVE'):c.begin(0)
 def test_failure_terminal(self):
  c=self.create();c.begin(0);r=self.row(0);r.update(status='FAIL',violations=['injected']);c.finish(0,r)
  with self.assertRaisesRegex(ValueError,'FAILED'):c.begin(1)
 def test_bad_existing_prefix_pin_refused(self):
  c=self.create();c.close()
  with self.assertRaisesRegex(ValueError,'PIN'):self.M.open(self.root,self.binding,self.config,pin={'sequence':0,'digest':'0'*64})
 def test_old_single_channel_manifest_not_matrix(self):
  from product.wp13.par_soak import Campaign
  c=Campaign.create(self.root,self.binding,{'rounds':2,'seed':55});c.close()
  with self.assertRaisesRegex(ValueError,'BINDING'):self.M.open(self.root,self.binding,self.config)
 def test_boolean_exit_cannot_replace_zero(self):
  c=self.create();c.begin(0);c.finish(0,self.row(0))
  with self.assertRaisesRegex(ValueError,'FINALIZATION'):c.seal([[False,False]])
 def test_boolean_sequence_is_not_integer_identity(self):
  import json
  c=self.create();c.begin(0);c.close();p=self.root/'000001.json'
  row=json.loads(p.read_text());row['sequence']=True
  from product.wp13.par_soak.campaign import pack
  p.write_bytes(pack(row))
  with self.assertRaisesRegex(ValueError,'CORRUPT'):self.M.open(self.root,self.binding,self.config)
