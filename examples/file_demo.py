#!/usr/bin/env python3
"""Disposable public fixtures: file create, store, export and read-only recovery."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_file import GROUPS  # Establish repo-local import paths, not run tests.
from file_support import FileTest

def main():
    case=FileTest();case.setUp()
    try:
        case.start();w=case.fw();staged=case.stage(w);receipt=w.commit(staged,*case.request()[1:]);n=case.count('issued_nonces')
        assert w.commit(staged,*case.request()[1:])==receipt and case.count('issued_nonces')==n
        info=case.export(receipt.envelope_id);assert case.output.read_bytes()==case.data
        snap=Path(case.tmp.name)/'snapshot';case.db.export_snapshot(snap);dest=Path(case.tmp.name)/'restored'
        case.blob.BlobStore.restore_snapshot(snap,dest,provider=case.p,allow_unpatched_sqlite=True)
        case.close();case.db=case.blob.BlobStore.open(dest,provider=case.p,allow_unpatched_sqlite=True)
        out=Path(case.tmp.name)/'restored-file';case.file.export_file(case.db,receipt.envelope_id,case.s.secret,out)
        assert out.read_bytes()==case.data and case.db._storage.restore_read_only
        print(json.dumps({'result':'PASS','scope':'PUBLIC_SYNTHETIC_LOCAL_EXPERIMENT','file_size':info.size,'chunks':info.chunks,'sha256':info.sha256.hex(),'staging_state':staged.state,'commit_state':'LOCAL_COMMITTED','file_complete':True,'restored_writer_read_only':True,'repeat_nonce_issuance':False,'automerge_applied':False,'network_verified':False,'production_qualified':False},indent=2))
    finally:case.doCleanups()
if __name__=='__main__':main()
