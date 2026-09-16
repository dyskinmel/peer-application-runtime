#!/usr/bin/env python3
"""Disposable opaque-byte storage demo. No real user data, keys, AEAD or networking."""
import hashlib,json,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
for rel in ('experiments/g0-store','experiments/g0-wire'):sys.path.insert(0,str(ROOT/rel))
from par_store.store import Store,restore_snapshot
from par_store.model import PreparedCommit

def h(value):return hashlib.sha256(value).digest()
def main():
    with tempfile.TemporaryDirectory(prefix='par-store-demo-') as directory:
        root=Path(directory);op=b'o'*16;inp=h(b'input');space=h(b'space')
        with Store.create(root/'original',allow_unpatched_sqlite=True) as s:
            s.configure_space(space,'org.example.notes',1,h(b'control'))
            reservation=s.reserve_nonce(op,inp,h(b'test-key-context'),b'n'*24)
            commit=PreparedCommit(op,inp,space,h(b'object'),h(b'actor'),b'a'*16,1,1,None,h(b'change'),reservation,
                b'TEST-OPAQUE-ENVELOPE-NOT-REAL-CIPHERTEXT',b'TEST-OPAQUE-CACHE',b'TEST-OPAQUE-RECEIPT',(),(b'TEST-OPAQUE-BLOCK',))
            receipt=s.commit(commit,fencing_token=s.fencing_token)
            assert receipt==s.commit(commit,fencing_token=s.fencing_token)
            snap=s.export_snapshot(root/'snapshot');before=s.audit();diagnostics=s.diagnostics()
        restore_snapshot(root/'snapshot',root/'restored',allow_unpatched_sqlite=True)
        with Store.open(root/'restored',allow_unpatched_sqlite=True) as restored:
            again=restored.lookup_operation(op,inp)
            assert again==receipt
            result={'scope':'DISPOSABLE_LOCAL_STORE_DEMO_ONLY','original_audit':before,'restored_audit':restored.audit(),
                'restored_read_only':restored.restore_read_only,'operation_lookup_matches':True,
                'snapshot_file_count':len(snap['files']),'sqlite_version':diagnostics['sqlite_version'],
                'warnings':diagnostics['warnings'],'cryptography_implemented':False,'production_qualified':False}
            print(json.dumps(result,indent=2))
    return 0
if __name__=='__main__':raise SystemExit(main())
