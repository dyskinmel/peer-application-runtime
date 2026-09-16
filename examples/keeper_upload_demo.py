#!/usr/bin/env python3
"""Disposable separate donor, dual Keeper host and recipient; synthetic public keys."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_keeper_upload import GROUPS
from test_upload_service import UploadService

def main():
    f=UploadService(methodName='runTest');f.setUp()
    try:
        f.test_separate_donor_and_recipient_processes()
        print(json.dumps({'scope':'SYNTHETIC_PRIVATE_UPLOAD_DEMO','separate_donor_process':True,
          'separate_keeper_process':True,'separate_recipient_process':True,'donor_removed_before_recovery':True,
          'verified_matching_file':True,'private_upload_profile':'keeper-upload-local-v1',
          'read_profile_unchanged':True,'writable':False,'crdt_applied':False,'product_qualified':False},indent=2))
        return 0
    finally:f.tearDown()
if __name__=='__main__':raise SystemExit(main())
