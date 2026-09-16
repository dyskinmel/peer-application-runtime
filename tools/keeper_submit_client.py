#!/usr/bin/env python3
"""Pinned private submit client. Prepare/stage/submit/select are separate operations."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.keeper_verified_host import arguments
for n in ('host-management-jobs','host-job-scheduler','host-job-control','host-job-submit'):sys.path.insert(0,str(ROOT/'experiments'/n))
def main():
    import argparse,json,os
    from harness.common import read_json
    from par_crypto.provider import SodiumProvider
    from par_window_host.host import read_secret
    from par_keeper_upload.spool import private
    from par_recovery.transfer import read_file
    from par_store.fs import safe,sync_dir
    from par_job_submit import protocol as c
    from par_job_submit.client import Client
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--socket',type=Path,required=True);ap.add_argument('--keeper',required=True);ap.add_argument('--store',required=True)
    ap.add_argument('--revision',type=int,required=True);ap.add_argument('--key-fd',type=int,required=True)
    ap.add_argument('--allow-legacy-sodium',action='store_true');ap.add_argument('--action',choices=['context','prepare','stage','progress','submit','reconcile','retry'],required=True)
    ap.add_argument('--payload',type=Path);ap.add_argument('--descriptor',type=Path);ap.add_argument('--job-id');ap.add_argument('--target');ap.add_argument('--output',type=Path)
    a=ap.parse_args();secret=None
    try:
        p=SodiumProvider(read_json(ROOT/'policy/crypto-provider.json'),allow_legacy_experiment=a.allow_legacy_sodium);secret=read_secret(a.key_fd)
        client=Client(a.socket,p,bytes.fromhex(a.keeper),bytes.fromhex(a.store),bytes(secret),a.revision)
        def read(path,limit):
            if path is None:raise c.E('SUBMIT_INPUT')
            private(path);return read_file(path,limit)
        if a.action=='prepare':
            if a.output is None or a.job_id is None or a.target is None:raise c.E('SUBMIT_INPUT')
            raw=client.descriptor(read(a.payload,c.MAX_PAYLOAD),bytes.fromhex(a.job_id),bytes.fromhex(a.target))
            dest=safe(a.output);private(dest.parent,True)
            fd=os.open(dest,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            try:
                with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
                sync_dir(dest.parent)
            except Exception:raise c.E('OUTPUT_UNCERTAIN') from None
            result={'descriptor_written':True,'sha256':c.sha(raw).hex(),'registered':False,'product_qualified':False}
        elif a.action=='context':result=client.call('context')
        else:
            descriptor=read(a.descriptor,c.MAX_DESCRIPTOR)
            result=client.stage(read(a.payload,c.MAX_PAYLOAD),descriptor) if a.action=='stage' else client.call(a.action,descriptor)
        print(json.dumps(result,sort_keys=True));return 0
    except Exception as exc:
        print(json.dumps({'result':'FAILED','code':getattr(exc,'code','SUBMIT_INPUT'),'product_qualified':False}),file=sys.stderr);return 1
    finally:
        if secret is not None:secret[:]=bytes(len(secret))
if __name__=='__main__':raise SystemExit(main())
