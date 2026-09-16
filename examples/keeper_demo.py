#!/usr/bin/env python3
"""Disposable public fixtures only. Keeper receives no recipient/content decryption key."""
from pathlib import Path
import hashlib,json,shutil,sys
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_keeper import suite  # Exact local experiment dependency paths.
from keeper_support import KeeperTest,h
from par_recovery import Inbox,open_recovery
from par_keeper import AuthorizedProvider

def main():
    fixture=KeeperTest(methodName='runTest');fixture.setUp()
    try:
        f=fixture;lid,receipt=f.ready()
        before=f.status(lid)
        # Issuer-created, separately trusted pin and fixture-only recipient secret.
        expected=f.source.read_bytes();donor=f.db._storage.root
        f.db.close();shutil.rmtree(donor);f.source.unlink()
        f.keeper.close();f.clock.boot=h('demo-next-boot');f.clock.ns=0;f.open_keeper()
        after=f.status(lid)
        remote=AuthorizedProvider(f.keeper,lid,f.cap,f.p,f.cs)
        inbox=Path(f.tmp.name)/'recipient-inbox'
        with Inbox(inbox,f.bundle.index,f.rpin) as rx:first=rx.pull(remote,limit=2)
        with Inbox(inbox,f.bundle.index,f.rpin) as rx:
            while rx.missing():rx.pull(remote,limit=32)
            byte_state=rx.status();rx.finalize(Path(f.tmp.name)/'recipient-view',f.p,f.reader['secret'])
        view=open_recovery(Path(f.tmp.name)/'recipient-view',f.rpin,f.p,f.reader['secret'])
        output=Path(f.tmp.name)/'export.bin';view.export_file(f.receipt.envelope_id,output)
        if output.read_bytes()!=expected:raise RuntimeError('recipient export mismatch')
        f.release(lid)
        print(json.dumps({'scope':'PUBLIC_SYNTHETIC_LOCAL_KEEPER_DEMO','donor_db_removed':not donor.exists(),
          'receipt_size':len(receipt),'before_reboot':before,'after_reboot':after,
          'first_partial_pull':first,'bytes_complete':byte_state,'recipient':view.status(),
          'after_release':f.status(lid),'capacity':f.keeper.diagnostics(),
          'export_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
          'keeper_received_content_key':False,'real_network':False,'product_qualified':False},indent=2))
        return 0
    finally:fixture.tearDown()
if __name__=='__main__':raise SystemExit(main())
