#!/usr/bin/env python3
"""Explicit same-endpoint payload retirement; offline dual approval is separate."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.dont_write_bytecode=True
from tools.keeper_retire_control_host import arguments

def main():
    import argparse,json,os
    from harness.common import read_json
    from par_crypto.provider import SodiumProvider
    from par_window_host.host import read_secret
    from par_recovery.transfer import read_file
    from par_keeper_upload.spool import private
    from par_store.fs import safe,sync_dir
    from par_submit_retire_control import protocol as c
    from par_submit_retire_control.client import Client
    from par_job_submit import protocol as s
    from par_submit_retire import contract as r
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--socket',type=Path,required=True);ap.add_argument('--keeper',required=True);ap.add_argument('--store',required=True)
    ap.add_argument('--revision',type=int,required=True);ap.add_argument('--key-fd',type=int,required=True)
    ap.add_argument('--origin-key-fd',type=int);ap.add_argument('--action',choices=list(c.METHODS)+['approve'],required=True)
    ap.add_argument('--descriptor',type=Path,required=True);ap.add_argument('--authorization',type=Path)
    ap.add_argument('--proposal',type=Path);ap.add_argument('--output',type=Path);ap.add_argument('--nonce')
    ap.add_argument('--allow-legacy-sodium',action='store_true')
    a=ap.parse_args();secret=None;origin=None
    try:
        if a.output is not None and a.action not in ('proposal','approve'):raise c.E('OUTPUT_NOT_SUPPORTED')
        p=SodiumProvider(read_json(ROOT/'policy/crypto-provider.json'),allow_legacy_experiment=a.allow_legacy_sodium)
        secret=read_secret(a.key_fd);kp=bytes.fromhex(a.keeper);store=bytes.fromhex(a.store)
        cli=Client(a.socket,p,kp,store,bytes(secret),a.revision)
        def read(path,limit):
            if path is None:raise c.E('RETIRE_CONTROL_INPUT')
            private(path);return read_file(path,limit)
        desc=read(a.descriptor,s.MAX_DESCRIPTOR);d=s.check_descriptor(p,desc)
        if (d[2],d[3])!=(kp,store):raise c.E('RETIRE_CONTROL_TARGET')
        def output(raw):
            if a.output is None:raise c.E('OUTPUT_REQUIRED')
            dest=safe(a.output);private(dest.parent,True)
            fd=os.open(dest,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            try:
                with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
                sync_dir(dest.parent)
            except Exception:raise c.E('OUTPUT_UNCERTAIN') from None
        if a.action=='approve':
            if a.origin_key_fd is None or a.origin_key_fd==a.key_fd:raise c.E('ORIGIN_KEY_REQUIRED')
            # Proposal files retain the complete signed exchange, not an
            # unauthenticated JSON summary from a third party.
            proof=s.load(read(a.proposal,65536),65536);s.keys(proof,(0,1,2))
            s.check_hello(p,kp,store,p.sign_public(bytes(secret)),a.revision,proof[0])
            req=c.check_request(p,kp,store,p.sign_public(bytes(secret)),a.revision,proof[0],proof[1])
            if req[3]!='proposal' or req[4]!=desc:raise c.E('RETIRE_CONTROL_TARGET')
            view=c.check_response(p,kp,proof[0],proof[1],proof[2]);origin=read_secret(a.origin_key_fd)
            if p.sign_public(bytes(origin))!=d[4]:raise c.E('RETIRE_ORIGIN')
            nonce=bytes.fromhex(a.nonce) if a.nonce else os.urandom(32)
            raw=r.make_request(p,bytes(secret),bytes(origin),revision=a.revision,nonce=nonce,**view['proposal'])
            output(raw);result={'approval_written':True,'sha256':s.sha(raw).hex(),'deletion_executed':False,'product_qualified':False}
        else:
            auth=read(a.authorization,r.MAX_REQUEST) if a.action in c.MUTATIONS else None
            result=cli.call(a.action,desc,auth)
            if a.output is not None:output(s.dump(cli.last_exchange,65536))
            # Convert only the already validated proposal bytes for JSON display.
            result=json.loads(c.encode_view(result))
        print(json.dumps(result,sort_keys=True));return 0
    except Exception as exc:
        print(json.dumps({'result':'FAILED','code':getattr(exc,'code','RETIRE_CONTROL_INPUT'),'product_qualified':False}),file=sys.stderr)
        return 1
    finally:
        if secret is not None:secret[:]=bytes(len(secret))
        if origin is not None:origin[:]=bytes(len(origin))
if __name__=='__main__':raise SystemExit(main())
