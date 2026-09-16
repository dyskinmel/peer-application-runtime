#!/usr/bin/env python3
"""Public synthetic data with real SQLite/crypto. NEVER an actual CRDT demo."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
for p in [ROOT,ROOT/'tests/product/application-observation']:
 sys.path.insert(0,str(p))
from fixture import scenario
if __name__=='__main__':
 sample=scenario()
 if '--fixture' in sys.argv: print(json.dumps(sample));sys.exit(0)
 print(json.dumps({'scope':'CANDIDATE_OBSERVATION_REAL_STORE_NOT_CRDT',
  'state':sample['recorded']['application']['state'],
  'note':sample['recorded']['application']['note'],
  'operation':sample['recorded']['operation'],
  'shared_write':sample['recorded']['capabilities']['sharedCommit'],
  'real_core_executed':False},ensure_ascii=False,indent=2))
