#!/usr/bin/env python3
"""Actual local store experiments; does not qualify native/power-loss/crypto behavior."""
from __future__ import annotations
import argparse, os, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tests/product/g0-store'))
sys.path.insert(0, str(ROOT/'experiments/g0-store'))
sys.path.insert(0, str(ROOT/'experiments/g0-wire'))
from harness.common import atomic_json
from tools.test_runner import RecordedResult

def suite(group='all'):
    names = [p.stem for p in sorted((ROOT/'tests/product/g0-store').glob('test_store_*.py'))]
    selected = [n for n in names if group == 'all' or n == 'test_store_'+group]
    return unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in selected)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('all','core','faults','blocks','recovery'), default='all')
    args = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordedResult).run(suite(args.suite))
    report = {'schema_version':1, 'nonce':os.environ.get('HARNESS_NONCE','standalone'), 'cases':result.cases}
    if 'HARNESS_RESULT_PATH' in os.environ:
        atomic_json(Path(os.environ['HARNESS_RESULT_PATH']), report)
    return 0 if result.wasSuccessful() and result.cases and all(c['status']=='PASS' for c in result.cases) else 1
if __name__ == '__main__': raise SystemExit(main())
