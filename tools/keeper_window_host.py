#!/usr/bin/env python3
"""Serve an existing replay-window spool on private Linux Unix sockets only."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
for name in ('g0-wire','g0-store','g0-crypto','space-auth','auth-store','blob-store','blob-manifest','recovery-closure','keeper-retention','keeper-gc','keeper-repair','keeper-service','keeper-upload','keeper-upload-retire','upload-replay-window','upload-window-host'):
    sys.path.insert(0,str(ROOT/'experiments'/name))

def arguments(parser):
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--spool',type=Path,required=True)
    parser.add_argument('--host-config',type=Path,required=True);parser.add_argument('--key-fd',type=int,required=True)
    parser.add_argument('--allow-unpatched-sqlite',action='store_true');parser.add_argument('--allow-legacy-sodium',action='store_true')

def main():
    import argparse,json,signal
    from harness.common import read_json
    from par_crypto.provider import SodiumProvider
    from par_keeper_service import Server as ReadServer
    from par_keeper_service.transport import private_path
    from par_window_host.server import Server
    from par_window_host.host import owned,read_config,read_secret
    from par_window_host.protocol import E,PROFILE
    ap=argparse.ArgumentParser(description=__doc__);arguments(ap)
    ap.add_argument('--socket',type=Path,required=True);ap.add_argument('--upload-socket',type=Path,required=True)
    ap.add_argument('--max-connections',type=int,default=8);ap.add_argument('--deadline-ms',type=int,default=5000)
    a=ap.parse_args();secret=None
    try:
        cfg=read_config(a.host_config)
        if private_path(a.socket)==private_path(a.upload_socket):raise E('SOCKET_ALIAS')
        secret=read_secret(a.key_fd)
        provider=SodiumProvider(read_json(ROOT/'policy/crypto-provider.json'),allow_legacy_experiment=a.allow_legacy_sodium)
        running=True
        def stop(signum,frame):
            nonlocal running
            running=False
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        with owned(a.root,a.spool,cfg,provider,bytes(secret),allow_unpatched_sqlite=a.allow_unpatched_sqlite) as (keeper,gateway):
            secret[:]=bytes(32)
            with ReadServer(keeper,a.socket,max_connections=a.max_connections,deadline_ms=a.deadline_ms) as read,Server(keeper,gateway,a.upload_socket,max_connections=a.max_connections,deadline_ms=a.deadline_ms) as upload:
                print(json.dumps({'state':'READY','profile':PROFILE,'keeper':keeper.public.hex(),'store':gateway.store_id.hex(),'sequence':gateway.pin()[1],'phase':gateway.phase,'product_qualified':False}),flush=True)
                while running:read.poll(.005);upload.poll(.005)
                print(json.dumps({'state':'STOPPING','read':read.diagnostics(),'upload':upload.diagnostics()}),flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({'state':'FAILED','code':getattr(exc,'code','HOST_ERROR'),'product_qualified':False}),file=sys.stderr,flush=True);return 1
    finally:
        if secret is not None:secret[:]=bytes(len(secret))
if __name__=='__main__':raise SystemExit(main())
