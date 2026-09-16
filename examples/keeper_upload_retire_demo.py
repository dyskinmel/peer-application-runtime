#!/usr/bin/env python3
"""Disposable local retirement demo; public fixture keys only, no networking."""
import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_keeper_upload_retire import GROUPS
from retire_support import RetireTest

def main():
    f=RetireTest();f.setUp()
    try:
        lid=f.upload_all();original={oid:f.keeper.object_path(lid,oid).read_bytes() for oid in f.bundle.objects}
        token=f.begin_index();begin=f.beginraw
        f.spool.execute(f.cmd('chunk',[token,0,f.bundle.index[:16]]));request=f.retirement_request()
        charged=f.spool.diagnostics()['reserved_bytes']
        def interrupt(event):
            if event=='retirement.intent.after_meta':raise OSError('synthetic lost acknowledgement')
        f.spool.observer=interrupt
        try:f.spool.retire(request)
        except Exception as exc:
            if getattr(exc,'code',None)!='OUTCOME_UNKNOWN':raise
        f.reopen();assert f.part(token).exists()
        f.change_authority();fresh=f.retirement_request();f.spool.rebind(fresh)
        result=f.spool.retire(fresh);assert f.spool.retire(fresh)==result
        for oid,raw in original.items():assert f.keeper.object_path(lid,oid).read_bytes()==raw
        assert f.spool.diagnostics()['reserved_bytes']==0
        try:f.spool.execute(begin)
        except Exception as exc:assert exc.code=='STAGE_RETIRED'
        else:raise AssertionError('old begin resurrected')
        print(json.dumps({'scope':'DISPOSABLE_LOCAL_FIXTURE','result':'PASS','state':result['state'],
            'staging_reserved_before':charged,'staging_reserved_after':0,
            'unlinked_payload_bytes':result['unlinked_payload_bytes'],'record_slots_reused':False,
            'keeper_payload_unchanged':True,'authority_rebound':True,'product_qualified':False},indent=2))
    finally:f.tearDown()
if __name__=='__main__':main()
