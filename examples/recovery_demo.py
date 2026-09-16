#!/usr/bin/env python3
"""Public synthetic keys only; isolated sender -> opaque directory -> recipient."""
from pathlib import Path
import json,sys,shutil
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_recovery import suite  # Establish the exact local dependency paths.
from recovery_support import RecoveryTest
from par_recovery import collect,verify,Inbox,DirectoryProvider,publish_bundle,open_recovery

def main():
    fixture=RecoveryTest(methodName='runTest');fixture.setUp()
    try:
        bundle=fixture.collect();pin=fixture.pin(bundle)
        root=Path(fixture.tmp.name);source=root/'opaque-provider';publish_bundle(bundle,source)
        provider=DirectoryProvider(source,bundle.index,pin)
        # The separate pin and synthetic reader key model already-authorized recovery.
        # NEVER derive this trust pin from an index received from an untrusted Keeper.
        expected=fixture.source.read_bytes();fixture.source.unlink()
        donor_root=fixture.db._storage.root;fixture.db.close();shutil.rmtree(donor_root)
        with Inbox(root/'inbox',bundle.index,pin) as rx:
            first=rx.pull(provider,limit=2)
        with Inbox(root/'inbox',bundle.index,pin) as rx:
            while rx.missing():rx.pull(provider,limit=32)
            opaque_state=rx.status()
            view=rx.finalize(root/'recovered',fixture.p,fixture.reader['secret'])
        view=open_recovery(root/'recovered',pin,fixture.p,fixture.reader['secret'])
        output=root/'recovered-file.bin';view.export_file(fixture.receipt.envelope_id,output)
        if output.read_bytes()!=expected:raise RuntimeError('recovered bytes do not match the public fixture')
        import hashlib
        print(json.dumps({'scope':'PUBLIC_SYNTHETIC_LOCAL_DEMO','donor_db_removed':not donor_root.exists(),
            'first_partial_pull':first,'before_recipient_validation':opaque_state,'after_validation':view.status(),
            'export_size':output.stat().st_size,'export_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
            'no_writable_database_import':True,'external_trust_pin_supplied':True},indent=2))
        return 0
    finally:fixture.tearDown()
if __name__=='__main__':raise SystemExit(main())
