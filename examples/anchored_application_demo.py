#!/usr/bin/env python3
"""Disposable real pin/SQLite recovery with SYNTHETIC core, no owner apply RPC."""
import json,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(R))
from tools import check_intent_anchor
from test_anchor_process import AnchorProcessTests

def main():
    t=AnchorProcessTests();t.setUp()
    try:
        t.child('commit-response-loss');f=t.reopen();f.app._core=None
        digest=f.j.current.digest;before=f.nums();value=f.d.inquire(digest)
        t.assertEqual(value['state'],'OBSERVED');t.assertEqual(f.port.calls,0)
        t.assertEqual(f.anchor.load(),f.j.pin());final=f.d.retire(digest)
        t.assertEqual(final['state'],'RETIRED');t.assertEqual(f.nums(),before)
        print(json.dumps({'result':'PASS','final_state':final['state'],'application_events':before['document_apply_events'],
             'recovery_materializations':f.port.calls,'anchor_matches':f.anchor.load()==f.j.pin(),
             'synthetic_materializer':True,'real_core_executed':False,'apply_wire_exposed':False,
             'hardware_rollback_protected':False,'replicated':False,'product_qualified':False},indent=2))
    finally:t.doCleanups()
    return 0
if __name__=='__main__':raise SystemExit(main())
