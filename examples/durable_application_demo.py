#!/usr/bin/env python3
"""Public synthetic fixture: SIGKILL after real SQLite COMMIT, inquire without core."""
import json,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
sys.path[:0]=[str(R),str(R/'tools')]
import check_application_intent
import test_intent_process as process

def main():
    f=process.IntentProcessTests();f.setUp()
    try:
        f.run_child('apply.after_commit');r=f.reopen();r.app._core=None
        before=r.nums();result=r.d.inquire(r.j.current.digest)
        assert result['state']=='OBSERVED' and result['operationId']==(b'o'*16).hex()
        after=r.nums();assert before==after and after['document_apply_events']==1
        assert r.port.calls==0
        retired=r.d.retire(r.j.current.digest);assert retired['state']=='RETIRED'
        print(json.dumps({'result':'PASS','restart_state':result['state'],'final_state':retired['state'],
            'original_operation_id':result['operationId'],'application_events':after['document_apply_events'],
            'reserved_nonces':after['document_apply_nonces'],'recovery_materializations':r.port.calls,
            'ledger_unchanged_by_inquiry':before==after,'actual_sigkill':True,
            'synthetic_materializer':True,'real_core_executed':False,'apply_wire_exposed':False,
            'replicated':False,'acknowledged':False,'product_qualified':False},indent=2))
    finally:f.doCleanups()
    return 0
if __name__=='__main__':raise SystemExit(main())
