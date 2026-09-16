#!/usr/bin/env python3
import json,sys
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from harness.packaging import verify_tree
x=verify_tree(ROOT);print(json.dumps(x,indent=2));raise SystemExit(0 if x['valid'] else 1)
