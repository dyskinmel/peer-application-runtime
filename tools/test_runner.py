#!/usr/bin/env python3
"""Actual unittest identities/outcomes, not counts or parsing a green log line."""
import json
import os
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT))
from harness.common import atomic_json

PUBLIC_ALPHA_TEST_MODULES = (
    'tests.test_oss_prerelease',
    'tests.test_public_alpha_release',
    'tests.test_public_alpha_smoke',
)

class RecordedResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.cases=[];self.index={};self.fixture_diagnostics=[]
    def startTest(self,test):
        super().startTest(test);self.cases.append({'id':test.id(),'status':'RUNNING'});self.index[id(test)]=len(self.cases)-1
    def mark(self,test,state):
        index=self.index.get(id(test))
        if index is None:
            # unittest's class/module fixture holder never called startTest.
            # Retain the diagnostic, not a fabricated executed test case.
            self.fixture_diagnostics.append({'id':test.id(),'status':state})
        else:self.cases[index]['status']=state
    def wasSuccessful(self):
        # In particular, a tearDownClass SkipTest must not become PASS merely
        # because the individual cases had already passed.
        return super().wasSuccessful() and not self.fixture_diagnostics
    def addSuccess(self,test):
        super().addSuccess(test)
        if self.cases[self.index[id(test)]]['status']=='RUNNING':self.mark(test,'PASS')
    def addFailure(self,test,err):super().addFailure(test,err);self.mark(test,'FAIL')
    def addError(self,test,err):super().addError(test,err);self.mark(test,'ERROR')
    def addSkip(self,test,reason):super().addSkip(test,reason);self.mark(test,'SKIP')
    def addExpectedFailure(self,test,err):super().addExpectedFailure(test,err);self.mark(test,'EXPECTED_FAILURE')
    def addUnexpectedSuccess(self,test):super().addUnexpectedSuccess(test);self.mark(test,'UNEXPECTED_SUCCESS')
    def addSubTest(self,test,subtest,err):
        super().addSubTest(test,subtest,err)
        if err:self.mark(test,'FAIL')
def test_modules(root: Path) -> list[str]:
    # Product RED tests belong to separately registered checks, not the H0 bootstrap prerequisite.
    modules = ['tests.'+p.stem for p in sorted((root/'tests').glob('test_*.py'))]
    if (root/'oss/PUBLIC_ALPHA_RELEASE.json').is_file():
        return [module for module in PUBLIC_ALPHA_TEST_MODULES if module in modules]
    return modules

def main():
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in test_modules(ROOT))
    result=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(suite)
    obj={'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':result.cases}
    if result.fixture_diagnostics:print(json.dumps({'fixture_diagnostics':result.fixture_diagnostics}),file=sys.stderr)
    dest=os.environ.get('HARNESS_RESULT_PATH')
    if dest:atomic_json(Path(dest),obj)
    return 0 if result.wasSuccessful() and result.cases and all(c['status']=='PASS' for c in result.cases) else 1
if __name__=='__main__':raise SystemExit(main())
