#!/usr/bin/env python3
"""Disposable Node/owner private IPC, real SQLite, explicit SYNTHETIC materializer."""
import asyncio,json,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(R))
from tools import check_application_owner
from test_application_process import ApplicationProcessTests
async def run():
 t=ApplicationProcessTests();await t.asyncSetUp()
 try:
  await t.phase('kill-commit')
  n,o=await t.phase('recover')
  t.assertEqual(o['state'],'OBSERVED');t.assertEqual(o['core_calls'],0)
  t.assertEqual(o['counts']['document_apply_events'],1);t.assertEqual(o['counts']['document_apply_nonces'],1)
  t.assertTrue(n['stored']['dispatchAttempted']);t.assertEqual(n['channel']['inflight'],0)
  return {'result':'PASS','scope':'NODE_PRIVATE_OWNER_SQLITE_SYNTHETIC_CONTRACT',
          'recovered_state':o['state'],'application_events':1,'nonces':1,'recovery_materializations':0,
          'caller_dispatch_marker_retained':True,'cleanup_complete':o['cleanup'],
          'synthetic_materializer':True,'real_core_executed':False,'browser_executed':False,
          'production_apply_exposed':False,'product_qualified':False}
 finally:await t.asyncTearDown();t.doCleanups()
def main():print(json.dumps(asyncio.run(run()),indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
