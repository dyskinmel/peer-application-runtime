#!/usr/bin/env python3
"""Exclusive offline administration; caller supplies already-signed approvals.

Stop the owning host first. No authority seed, network endpoint or arbitrary
operation dispatch. Output paths are explicit and never overwritten.
"""
import sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import keeper_window_host
ROOT=keeper_window_host.ROOT

def main():
    import argparse,json,hashlib,os,tempfile
    from harness.common import read_json
    from par_crypto.provider import SodiumProvider
    from par_recovery.transfer import read_file
    from par_store.fs import safe,sync_dir
    from par_keeper_upload.spool import private
    from par_window_host.host import owned,read_config,read_secret,administer
    from par_window_host.protocol import E
    from par_upload_window.contract import MAX_ARCHIVE,MAX_CONTROL
    ap=argparse.ArgumentParser(description=__doc__);keeper_window_host.arguments(ap)
    ap.add_argument('--action',choices=['inspect','export','retire','rebind','close','compact','open'],required=True)
    ap.add_argument('--command',type=Path);ap.add_argument('--archive',type=Path);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();secret=None;tmp=None;executed=False
    try:
        cfg=read_config(a.host_config);dest=safe(a.output);private(dest.parent,True)
        if dest.exists():raise E('OUTPUT_EXISTS')
        def data(path,limit):
            if path is None:return None
            private(path);return read_file(path,limit)
        command=data(a.command,MAX_CONTROL);archive=data(a.archive,MAX_ARCHIVE)
        secret=read_secret(a.key_fd)
        provider=SodiumProvider(read_json(ROOT/'policy/crypto-provider.json'),allow_legacy_experiment=a.allow_legacy_sodium)
        with owned(a.root,a.spool,cfg,provider,bytes(secret),allow_unpatched_sqlite=a.allow_unpatched_sqlite) as (_,gateway):
            executed=True;result=administer(gateway,a.action,command=command,archive=archive)
            fd,name=tempfile.mkstemp(prefix='.window-admin-',dir=dest.parent);tmp=Path(name)
            with os.fdopen(fd,'wb') as f:f.write(result);f.flush();os.fsync(f.fileno())
            os.link(tmp,dest,follow_symlinks=False);tmp.unlink();tmp=None;sync_dir(dest.parent)
        print(json.dumps({'state':'RECORDED','action':a.action,'bytes':len(result),'sha256':hashlib.sha256(result).hexdigest(),'product_qualified':False}),flush=True);return 0
    except Exception as exc:
        print(json.dumps({'state':'FAILED','code':getattr(exc,'code','ADMIN_OUTCOME_UNKNOWN' if executed else 'ADMIN_ERROR'),'may_have_executed':executed,'product_qualified':False}),file=sys.stderr,flush=True);return 1
    finally:
        if secret is not None:secret[:]=bytes(len(secret))
        if tmp is not None:
            try:tmp.unlink()
            except OSError:pass
if __name__=='__main__':raise SystemExit(main())
