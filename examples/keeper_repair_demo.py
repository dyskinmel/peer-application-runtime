#!/usr/bin/env python3
"""Repair synthetic Keeper bytes, then recover after removing the donor DB."""
import hashlib,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_keeper_repair import GROUPS
from repair_support import RepairTest
from par_keeper import AuthorizedProvider
from par_recovery import Inbox,open_recovery

def main():
    f=RepairTest(methodName='runTest');f.setUp()
    try:
        lid,old_receipt=f.ready();before=f.keeper.diagnostics();expected=f.source.read_bytes()
        targets=sorted(f.bundle.objects)[:2]
        f.damage(lid,'missing',targets[0]);f.damage(lid,'corrupt',targets[1]);damaged=f.status(lid)
        donor=f.db._storage.root;f.db.close();shutil.rmtree(donor);f.source.unlink()
        request=f.repair_request(lid,targets);marked=f.keeper.mark_repair(lid,f.cap,request)
        f.reopen();signed_result=f.repair(lid,request);observation=f.r.verify_result(f.p,signed_result,f.kp,expected_request=request)
        f.reopen()
        if f.repair(lid,request)!=signed_result:raise RuntimeError('replay changed observation')
        if f.keeper._lease(lid)['receipt']!=old_receipt:raise RuntimeError('repair changed retention')
        remote=AuthorizedProvider(f.keeper,lid,f.cap,f.p,f.cs);destination=Path(f.tmp.name)/'recipient'
        with Inbox(Path(f.tmp.name)/'inbox',f.bundle.index,f.rpin) as rx:
            while rx.missing():rx.pull(remote,limit=32)
            rx.finalize(destination,f.p,f.reader['secret'])
        view=open_recovery(destination,f.rpin,f.p,f.reader['secret']);out=Path(f.tmp.name)/'export'
        view.export_file(f.receipt.envelope_id,out)
        if out.read_bytes()!=expected:raise RuntimeError('restored file mismatch')
        def enc(v):
            if isinstance(v,bytes):return v.hex()
            raise TypeError(type(v).__name__)
        print(json.dumps({'scope':'PUBLIC_SYNTHETIC_LOCAL_REPAIR_DEMO','donor_db_removed':not donor.exists(),
            'before':before,'damaged':damaged,'marked':marked,'observation':observation,'after':f.status(lid),
            'payload_quota_unchanged':f.keeper.diagnostics()['reserved_bytes']==before['reserved_bytes'],
            'retention_receipt_unchanged':True,'replayed_observation_identical':True,
            'restored_file_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'writable':False,'applied':False,
            'network_verified':False,'product_qualified':False},default=enc,indent=2));return 0
    finally:f.tearDown()
if __name__=='__main__':raise SystemExit(main())
