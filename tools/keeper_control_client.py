#!/usr/bin/env python3
"""Explicit local owner commands. Mutation IDs are supplied by the operator; no retry loop."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools import keeper_control_host

def main():
    import argparse,json
    from harness.common import read_json
    from par_crypto.provider import SodiumProvider
    from par_window_host.host import read_secret
    from par_job_control import Client
    from par_job_control.protocol import ACTIONS,E,fixed
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--socket',type=Path,required=True);ap.add_argument('--keeper',required=True);ap.add_argument('--store',required=True)
    ap.add_argument('--key-fd',type=int,required=True);ap.add_argument('--revision',type=int,required=True)
    ap.add_argument('--action',choices=ACTIONS,required=True);ap.add_argument('--job');ap.add_argument('--operation-id')
    ap.add_argument('--timeout',type=float,default=5);ap.add_argument('--allow-legacy-sodium',action='store_true')
    a=ap.parse_args();secret=None
    try:
        def ident(s):
            if s is None:return None
            b=bytes.fromhex(s);fixed(b);return b
        kp,store,jid,oid=ident(a.keeper),ident(a.store),ident(a.job),ident(a.operation_id)
        secret=read_secret(a.key_fd);p=SodiumProvider(read_json(ROOT/'policy/crypto-provider.json'),allow_legacy_experiment=a.allow_legacy_sodium)
        client=Client(a.socket,p,kp,store,bytes(secret),a.revision,timeout=a.timeout)
        result=client.call(a.action,jid,oid)
        print(json.dumps(result,sort_keys=True),flush=True)
        return 2 if result['outcome']=='OUTCOME_UNKNOWN' else 0
    except Exception as exc:
        print(json.dumps({'state':'FAILED','code':getattr(exc,'code','CONTROL_INPUT'),'product_qualified':False}),file=sys.stderr,flush=True);return 1
    finally:
        if secret is not None:secret[:]=bytes(len(secret))
if __name__=='__main__':raise SystemExit(main())
