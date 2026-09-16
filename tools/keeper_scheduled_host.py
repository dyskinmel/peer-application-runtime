#!/usr/bin/env python3
"""Private Linux host with explicit owner job selection and measured draining.

No management socket, auto-reconciliation, auto-retry or arbitrary job submission.
Pre-register jobs through the owner API. Select at most one via an explicit flag.
"""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.keeper_verified_host import arguments
for name in ('host-management-jobs','host-job-scheduler'):sys.path.insert(0,str(ROOT/'experiments'/name))

def main():
    import argparse,json,signal
    from harness.common import read_json
    from par_crypto.provider import SodiumProvider
    from par_keeper_service.transport import private_path
    from par_window_host.host import read_config,read_secret
    from par_verified_host.host import owned_verified
    from par_window_host.protocol import E,PROFILE
    from par_job_scheduler import ScheduledHost
    ap=argparse.ArgumentParser(description=__doc__);arguments(ap)
    ap.add_argument('--socket',type=Path,required=True);ap.add_argument('--upload-socket',type=Path,required=True)
    ap.add_argument('--jobs',type=Path,required=True)
    ap.add_argument('--max-connections',type=int,default=8);ap.add_argument('--deadline-ms',type=int,default=5000)
    ap.add_argument('--drain-timeout',type=float,default=10)
    ap.add_argument('--verification-mode',choices=['full','signatures'],default='full')
    group=ap.add_mutually_exclusive_group()
    group.add_argument('--run-job',help='hex job ID, explicitly select one previously queued/prepared job')
    group.add_argument('--reconcile-job',help='hex job ID, explicitly reconcile; never retry automatically')
    group.add_argument('--retry-job',help='hex job ID already reconciled to RETRY_READY')
    a=ap.parse_args();secret=None
    try:
        selected=None
        for mode in ('run_job','reconcile_job','retry_job'):
            raw=getattr(a,mode)
            if raw is not None:
                if len(raw)!=64:raise E('JOB_SCHEMA')
                selected=bytes.fromhex(raw)
                if len(selected)!=32:raise E('JOB_SCHEMA')
        cfg=read_config(a.host_config)
        if private_path(a.socket)==private_path(a.upload_socket):raise E('SOCKET_ALIAS')
        secret=read_secret(a.key_fd)
        provider=SodiumProvider(read_json(ROOT/'policy/crypto-provider.json'),allow_legacy_experiment=a.allow_legacy_sodium)
        running=True
        def stop(signum,frame):
            nonlocal running
            running=False
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        with owned_verified(a.root,a.spool,cfg,provider,bytes(secret),mode=a.verification_mode,allow_unpatched_sqlite=a.allow_unpatched_sqlite) as (keeper,gateway,cached,startup):
            secret[:]=bytes(32)
            with ScheduledHost(keeper,gateway,a.socket,a.upload_socket,a.jobs,max_connections=a.max_connections,deadline_ms=a.deadline_ms,drain_timeout=a.drain_timeout) as host:
                if a.reconcile_job:host.reconcile(selected)
                elif a.retry_job:host.arm_retry(selected)
                elif a.run_job:host.schedule(selected)
                print(json.dumps({'state':'READY','profile':PROFILE,'keeper':keeper.public.hex(),'store':gateway.store_id.hex(),
                    'sequence':gateway.pin()[1],'phase':gateway.phase,'scheduler':host.diagnostics(),'startup_verification':startup,'product_qualified':False}),flush=True)
                while running:host.tick(.01)
                print(json.dumps({'state':'STOPPING','scheduler':host.diagnostics(),'read':host.read.diagnostics(),'upload':host.upload.diagnostics(),
                    'verification':cached.statistics(),'product_qualified':False}),flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({'state':'FAILED','code':getattr(exc,'code','HOST_ERROR'),'product_qualified':False}),file=sys.stderr,flush=True);return 1
    finally:
        if secret is not None:secret[:]=bytes(len(secret))
if __name__=='__main__':raise SystemExit(main())
