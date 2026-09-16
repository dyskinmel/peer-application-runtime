#!/usr/bin/env python3
"""Disposable synthetic window-close/compaction demo. No user files or network."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT/'tools'))
import check_upload_window
from window_support import WindowTest

def main():
    t=WindowTest();t.setUp()
    try:
        t.terminal();old=t.beginwrapped
        before=t.window.diagnostics();keeper_before=list(t.keeper.connection.iterdump())
        archive,approval=t.proposed();t.window.close_window(approval,archive)
        t.reopen_window();closed=t.window.diagnostics();receipt=t.window.compact();clean=t.window.diagnostics()
        t.next_window(receipt)
        rejected=False
        try:t.window.execute(old)
        except Exception as exc:rejected=getattr(exc,'code',None)=='WINDOW_SCOPE'
        t.terminal();current=t.window.diagnostics()
        unchanged=keeper_before==list(t.keeper.connection.iterdump())
        result={'result':'PASS' if rejected and unchanged else 'FAIL','scope':'SYNTHETIC_LOCAL_CANDIDATE',
                'before':before,'after_reopen_closed':closed,'after_compaction':clean,'new_window':current,
                'old_request_rejected':rejected,'keeper_unchanged':unchanged,'archive_bytes':len(archive),
                'product_qualified':False,'physical_space_reclaimed':False}
        print(json.dumps(result,indent=2));return 0 if result['result']=='PASS' else 1
    finally:t.tearDown()
if __name__=='__main__':raise SystemExit(main())
