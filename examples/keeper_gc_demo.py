#!/usr/bin/env python3
"""Disposable public-fixture recovery then explicit GC and quota reuse."""
import hashlib,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_keeper_gc import GROUPS
from gc_support import GCTest
from par_keeper import AuthorizedProvider
from par_recovery import Inbox,open_recovery

def main():
    f=GCTest(methodName='runTest');f.setUp()
    try:
        lid,retained=f.ready();old=f.keeper.diagnostics();expected=f.source.read_bytes()
        donor=f.db._storage.root;f.db.close();shutil.rmtree(donor);f.source.unlink()
        remote=AuthorizedProvider(f.keeper,lid,f.cap,f.p,f.cs);destination=Path(f.tmp.name)/'recipient'
        with Inbox(Path(f.tmp.name)/'inbox',f.bundle.index,f.rpin) as rx:
            while rx.missing():rx.pull(remote,limit=32)
            rx.finalize(destination,f.p,f.reader['secret'])
        view=open_recovery(destination,f.rpin,f.p,f.reader['secret']);output=Path(f.tmp.name)/'export.bin'
        view.export_file(f.receipt.envelope_id,output)
        if output.read_bytes()!=expected:raise RuntimeError('recovery mismatch')
        oid=next(iter(f.bundle.objects))
        with f.keeper.reader(lid,oid,f.cap,f.call('get',lid,oid)):
            f.release(lid);request=f.gc_request(lid)
            try:f.gc(lid,request)
            except f.k.KeeperError as e:
                if e.code!='PINNED':raise
            else:raise RuntimeError('pin did not block GC')
        marked=f.keeper.mark(lid,f.cap,request);f.reopen();receipt=f.gc(lid,request)
        result=f.g.verify_result(f.p,receipt,f.kp,request);f.reopen()
        if receipt!=f.gc(lid,request):raise RuntimeError('retry changed result')
        after=f.keeper.diagnostics();other=f.reserve()
        print(json.dumps({'scope':'PUBLIC_SYNTHETIC_LOCAL_GC_DEMO','donor_db_removed':not donor.exists(),
            'recipient_export_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'before':old,'marked':{k:(v.hex() if isinstance(v,bytes) else v) for k,v in marked.items()},
            'result':result,'after':after,'new_reservation_succeeded':other!=lid,'replayed_receipt_identical':True,
            'network_verified':False,'product_qualified':False},indent=2));return 0
    finally:f.tearDown()
if __name__=='__main__':raise SystemExit(main())
