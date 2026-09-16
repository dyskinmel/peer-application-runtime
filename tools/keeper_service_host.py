#!/usr/bin/env python3
"""Run an existing schema3 Keeper on a private Linux socket; no public mutations."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
for name in ('g0-wire','g0-store','g0-crypto','space-auth','auth-store','blob-store','blob-manifest','recovery-closure','keeper-retention','keeper-gc','keeper-repair','keeper-service'):
    sys.path.insert(0,str(ROOT/'experiments'/name))

def main():
    import argparse,json,os,signal
    from harness.common import read_json
    from par_crypto.provider import SodiumProvider
    from par_keeper.contract import authority_from
    from par_keeper_repair import KeeperRepair
    from par_recovery.transfer import read_file
    from par_keeper_service import Server,ServiceError
    from par_keeper_service.protocol import load,keys,integer
    from par_store.fs import safe
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True);p.add_argument('--socket',type=Path,required=True);p.add_argument('--host-config',type=Path,required=True)
    p.add_argument('--key-fd',type=int,required=True);p.add_argument('--max-connections',type=int,default=8);p.add_argument('--deadline-ms',type=int,default=5000)
    p.add_argument('--allow-unpatched-sqlite',action='store_true');p.add_argument('--allow-legacy-sodium',action='store_true')
    a=p.parse_args()
    try:
        cfg=load(read_file(a.host_config,16384),16384);keys(cfg,range(5));integer(cfg[0],1,1);auth=authority_from(cfg[1])
        if not safe(a.root/'keeper.sqlite').is_file():raise ServiceError('EXISTING_KEEPER_REQUIRED')
        integer(a.key_fd,0,1048575)
        secret=bytearray()
        while len(secret)<33:
            b=os.read(a.key_fd,33-len(secret))
            if not b:break
            secret.extend(b)
        if len(secret)!=32:raise ServiceError('KEY_INPUT')
        provider=SodiumProvider(read_json(ROOT/'policy/crypto-provider.json'),allow_legacy_experiment=a.allow_legacy_sodium)
        running=True
        def stop(signum,frame):
            nonlocal running
            running=False
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        with KeeperRepair(a.root,provider,bytes(secret),auth,quota_bytes=cfg[2],max_leases=cfg[3],max_operations=cfg[4],allow_unpatched_sqlite=a.allow_unpatched_sqlite) as keeper:
            secret[:]=bytes(32) # Python/copies/native memory are not a hardware key store.
            with Server(keeper,a.socket,max_connections=a.max_connections,deadline_ms=a.deadline_ms) as server:
                print(json.dumps({'state':'READY','profile':'keeper-service-local-v1','keeper':keeper.public.hex(),'product_qualified':False}),flush=True)
                while running:server.poll(.05)
                print(json.dumps({'state':'STOPPING','counters':server.diagnostics()}),flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({'state':'FAILED','code':getattr(exc,'code','HOST_ERROR'),'product_qualified':False}),file=sys.stderr,flush=True)
        return 1
if __name__=='__main__':raise SystemExit(main())
