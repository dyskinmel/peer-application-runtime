#!/usr/bin/env python3
"""Disposable donor/server/recipient demonstration; public synthetic test keys only."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_keeper_service import GROUPS
from test_service_recovery import ServiceRecovery
from par_recovery import Inbox

def main():
    f=ServiceRecovery(methodName='runTest');f.setUp()
    try:
        f.start_process();job=f.job();expected=f.remove_donor()
        jobdata=json.loads(job.read_text())
        with Inbox(Path(jobdata['inbox']),f.bundle.index,f.rpin) as rx:
            rx.pull(f.remote(),limit=2);missing=len(rx.missing())
        f.stop_process();f.start_process(existing=True)
        result=f.run_receiver(job)
        if result['sha256']!=expected:raise RuntimeError('recovery mismatch')
        print(json.dumps({'scope':'SYNTHETIC_PRIVATE_IPC_DEMO','donor_removed':True,'keeper_restarted':True,
            'resume_missing':missing,'fetched_after_resume':len(result['fetched']),'file_sha256':expected,
            'status':result['status'],'public_listener':False,'product_qualified':False},indent=2));return 0
    finally:f.tearDown()
if __name__=='__main__':raise SystemExit(main())
