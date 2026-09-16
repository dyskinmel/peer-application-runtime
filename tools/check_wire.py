#!/usr/bin/env python3
"""Run actual wire experiment tests; no test inventory is used to manufacture PASS."""
from __future__ import annotations
import argparse,os,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests/product/g0-wire'))
from harness.common import atomic_json
from tools.test_runner import RecordedResult
INTEROP={'test_wire_interop','test_wire_properties','test_wire_fixtures'}

def modules(group='all'):
    names=[p.stem for p in sorted((ROOT/'tests/product/g0-wire').glob('test_wire_*.py'))]
    return [n for n in names if group=='all' or ((n in INTEROP)==(group=='interop'))]

def suite(group='all'):
    return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in modules(group))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',choices=('all','python','interop'),default='all');a=p.parse_args()
    result=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(suite(a.suite))
    obj={'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':result.cases}
    if 'HARNESS_RESULT_PATH' in os.environ:atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),obj)
    return 0 if result.wasSuccessful() and result.cases and all(c['status']=='PASS' for c in result.cases) else 1
if __name__=='__main__':raise SystemExit(main())
