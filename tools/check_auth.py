#!/usr/bin/env python3
"""Finite local Space authority candidate tests; not product qualification."""
from __future__ import annotations
import argparse,os,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/space-auth',ROOT/'experiments/space-auth',ROOT/'experiments/g0-crypto',ROOT/'experiments/g0-wire',ROOT/'experiments/g0-store']:sys.path.insert(0,str(p))
from harness.common import atomic_json
from tools.test_runner import RecordedResult
GROUPS=['membership','chain','activation','admission','receiver','replay','vectors']
def suite(group='all'):
    names=[p.stem for p in sorted((ROOT/'tests/product/space-auth').glob('test_auth_*.py'))]
    selected=[n for n in names if group=='all' or n=='test_auth_'+group]
    return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in selected)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',choices=['all']+GROUPS,default='all');a=p.parse_args()
    result=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(suite(a.suite))
    report={'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':result.cases}
    if 'HARNESS_RESULT_PATH' in os.environ:atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),report)
    return 0 if result.wasSuccessful() and result.cases and all(c['status']=='PASS' for c in result.cases) else 1
if __name__=='__main__':raise SystemExit(main())
