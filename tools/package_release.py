#!/usr/bin/env python3
"""Package reviewed source. Run current candidate checks BEFORE invoking this tool."""
import argparse,json,sys
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from harness.packaging import create_archive
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
print(json.dumps(create_archive(ROOT,a.output),indent=2))
