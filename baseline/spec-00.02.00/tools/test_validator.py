#!/usr/bin/env python3
"""Mutation controls for the SPECIFICATION validator; not PAR runtime tests."""
import json, shutil, tempfile, unittest
from pathlib import Path
from validate_spec import validate
ROOT=Path(__file__).resolve().parents[1]
class ValidatorControls(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'bundle'
        shutil.copytree(ROOT,self.root,ignore=shutil.ignore_patterns('__pycache__'))
    def tearDown(self):self.temp.cleanup()
    def mutate_json(self,rel,fn):
        p=self.root/rel;obj=json.loads(p.read_text());fn(obj);p.write_text(json.dumps(obj))
    def assert_rejects(self):self.assertEqual(validate(self.root)['result'],'FAIL')
    def test_valid_baseline(self):self.assertEqual(validate(self.root)['result'],'PASS')
    def test_missing_acceptance(self):
        self.mutate_json('catalog/requirements.json',lambda o:o[0].update(test_ids=[]));self.assert_rejects()
    def test_duplicate_requirement(self):
        self.mutate_json('catalog/requirements.json',lambda o:o.append(o[0]));self.assert_rejects()
    def test_false_test_pass(self):
        self.mutate_json('catalog/acceptance-tests.json',lambda o:o[0].update(execution_status='PASS'));self.assert_rejects()
    def test_false_production_claim(self):
        self.mutate_json('STATUS.json',lambda o:o.update(qualified_profiles=['native-stable']));self.assert_rejects()
    def test_gate_cycle(self):
        self.mutate_json('catalog/gates.json',lambda o:o[0].update(depends_on=['G11']));self.assert_rejects()
    def test_token_cycle(self):
        self.mutate_json('tokens/semantic.tokens.json',lambda o:o['semantic']['focus'].update({'$value':'{semantic.focus}'}));self.assert_rejects()
    def test_broken_link(self):
        with (self.root/'START_HERE.ja.md').open('a') as f:f.write('\n[broken](missing-file.md)\n')
        self.assert_rejects()
    def test_missing_cddl_rule(self):
        p=self.root/'protocol/par-v1.cddl';p.write_text(p.read_text().replace('hello-body =','deleted-body ='));self.assert_rejects()
    def test_corrupt_history(self):
        p=self.root/'history/peer-application-runtime-spec-00.01.00.zip';p.write_bytes(b'corrupt');self.assert_rejects()
    def test_unknown_story_action(self):
        self.mutate_json('ui/stories.json',lambda o:o[0]['allowed_actions'].append('execute-untrusted-code'));self.assert_rejects()
    def test_bad_primitive_vector(self):
        self.mutate_json('fixtures/primitive-kats.json',lambda o:o['ed25519'].update(signature_hex='0'*129));self.assert_rejects()
    def test_duplicate_json_key(self):
        (self.root/'STATUS.json').write_text('{"gates":{},"gates":{}}');self.assert_rejects()
if __name__=='__main__':unittest.main(verbosity=2)
