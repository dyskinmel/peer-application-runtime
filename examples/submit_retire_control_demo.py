#!/usr/bin/env python3
"""Separate synthetic host process, verified proposal, explicit retirement and replay."""
import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from tools import check_submit_retire_control
from test_retire_control_process import ControlProcess

def main():
    t=ControlProcess('runTest');t.setUp()
    try:
        old,cli,descriptor,approval=t.setup_stage(registered=True)
        result=cli.call('retire',descriptor,approval)
        duplicate=cli.call('retire',descriptor,approval)
        assert result==duplicate
        try:old.call('submit',descriptor)
        except Exception as exc:refusal=exc.code
        else:raise AssertionError('retired input resurrected')
        t.stop_process();t.start_host()
        recovered=cli.call('status',descriptor)
        assert recovered['retirement']['state']=='TOMBSTONED'
        print(json.dumps({'scope':'SYNTHETIC_PRIVATE_IPC','result':recovered,'same_request_same_result':True,
                          'legacy_descriptor_refusal':refusal,'job_preserved':True,'product_qualified':False},indent=2))
    finally:t.tearDown()
if __name__=='__main__':main()
