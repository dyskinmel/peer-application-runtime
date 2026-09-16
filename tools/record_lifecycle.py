#!/usr/bin/env python3
"""Inspect bounded metadata JSON. The JSON is NOT portable cryptographic proof."""
import argparse,json,sys
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'experiments/management-record-lifecycle'))
from par_record_lifecycle import decode_inventory,plan,present,LifecycleError
from par_record_lifecycle.contracts import MAX_BYTES

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('inventory',type=Path)
    a=ap.parse_args()
    try:
        with a.inventory.open('rb') as f:raw=f.read(MAX_BYTES+1)
        v=decode_inventory(raw)
        print(json.dumps({'warning':'Metadata only: re-collect from verified live ledgers before any operational decision.',
                          'view':present(v),'plan':plan(v)},indent=2))
        return 0
    except (OSError,LifecycleError) as exc:
        print(json.dumps({'result':'REJECTED','code':getattr(exc,'code','INPUT_IO'),'real_deletion_allowed':False}),file=sys.stderr)
        return 1
if __name__=='__main__':raise SystemExit(main())
