#!/usr/bin/env python3
"""Exact local route-policy and private-socket evidence; no public qualification."""
from __future__ import annotations
import argparse, json, os, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests/product/wp09'))
from harness.common import atomic_json
from tools.test_runner import RecordedResult
GROUPS={name:'test_'+name for name in ('policy','controller','tcp','integration','hardening')}
def suite(group='all'):
    return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(GROUPS[g]) for g in (GROUPS if group=='all' else (group,)))
def identities(s):
    result=[]
    for item in s:
        result.extend(identities(item) if isinstance(item,unittest.TestSuite) else [item.id()])
    return sorted(result)
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--suite',choices=['all',*GROUPS],default='all');ap.add_argument('--list',action='store_true');args=ap.parse_args()
    tests=suite(args.suite);expected=identities(tests)
    if args.list:
        print(json.dumps(expected,indent=2));return 0
    result=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(tests)
    if 'HARNESS_RESULT_PATH' in os.environ:
        atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),{'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':result.cases})
    actual=[c['id'] for c in result.cases]
    good=(result.wasSuccessful() and bool(actual) and sorted(actual)==expected and len(set(actual))==len(actual)
          and all(c['status']=='PASS' for c in result.cases))
    return 0 if good else 1
if __name__=='__main__':raise SystemExit(main())
