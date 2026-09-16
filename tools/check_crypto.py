#!/usr/bin/env python3
"""Real local crypto checks; no product/security/independent-review qualification."""
from __future__ import annotations
import argparse,os,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/g0-crypto',ROOT/'experiments/g0-crypto',ROOT/'experiments/g0-wire',ROOT/'experiments/g0-store']:sys.path.insert(0,str(p))
from harness.common import atomic_json
from tools.test_runner import RecordedResult
def suite(group='all'):
    names=[p.stem for p in sorted((ROOT/'tests/product/g0-crypto').glob('test_crypto_*.py'))]
    selected=[n for n in names if group=='all' or n=='test_crypto_'+group]
    return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in selected)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',choices=['all','primitives','hpke','objects','store','interop'],default='all');args=p.parse_args()
    result=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(suite(args.suite))
    report={'schema_version':1,'nonce':os.environ.get('HARNESS_NONCE','standalone'),'cases':result.cases}
    if 'HARNESS_RESULT_PATH' in os.environ:atomic_json(Path(os.environ['HARNESS_RESULT_PATH']),report)
    return 0 if result.wasSuccessful() and result.cases and all(c['status']=='PASS' for c in result.cases) else 1
if __name__=='__main__':raise SystemExit(main())
