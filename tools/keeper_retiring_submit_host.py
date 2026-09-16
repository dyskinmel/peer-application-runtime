#!/usr/bin/env python3
"""Private Linux registration host accepting retirement schema2. No remote deletion API."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.keeper_verified_host import arguments
for n in ('host-management-jobs','host-job-scheduler','host-job-control','host-job-submit','job-submission-retire'):sys.path.insert(0,str(ROOT/'experiments'/n))
def main():
    import argparse,json,signal
    from harness.common import read_json
    from par_crypto.provider import SodiumProvider
    from par_window_host.host import read_config,read_secret
    from par_verified_host.host import owned_verified
    from par_submit_retire.host import RetiringSubmissionHost
    from par_job_submit import protocol as c
    from par_recovery.transfer import read_file
    from par_keeper_upload.spool import private
    ap=argparse.ArgumentParser(description=__doc__);arguments(ap)
    for name in ('socket','upload-socket','control-socket','jobs','control-state','submit-socket','submissions'):ap.add_argument('--'+name,type=Path,required=True)
    ap.add_argument('--control-public',required=True);ap.add_argument('--control-revision',type=int,required=True)
    ap.add_argument('--migrate-submissions',action='store_true');ap.add_argument('--submission-pin-file',type=Path)
    ap.add_argument('--jobs-pin-file',type=Path);ap.add_argument('--control-pin-file',type=Path)
    ap.add_argument('--deadline-ms',type=int,default=5000);ap.add_argument('--max-connections',type=int,default=8)
    ap.add_argument('--control-deadline-ms',type=int,default=5000);ap.add_argument('--control-max-connections',type=int,default=4)
    ap.add_argument('--drain-timeout',type=float,default=10);ap.add_argument('--verification-mode',choices=['full','signatures'],default='full')
    a=ap.parse_args();secret=None
    try:
        public=bytes.fromhex(a.control_public);c.fixed(public);c.integer(a.control_revision,1,2**53-1)
        def pin(path):
            if path is None:return None
            private(path);return c.load(read_file(path,32768),32768)
        jp,cp=pin(a.jobs_pin_file),pin(a.control_pin_file);sp=pin(a.submission_pin_file)
        cfg=read_config(a.host_config);secret=read_secret(a.key_fd)
        p=SodiumProvider(read_json(ROOT/'policy/crypto-provider.json'),allow_legacy_experiment=a.allow_legacy_sodium)
        running=True
        def stop(*_):
            nonlocal running
            running=False
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        with owned_verified(a.root,a.spool,cfg,p,bytes(secret),mode=a.verification_mode,allow_unpatched_sqlite=a.allow_unpatched_sqlite) as (k,g,cache,startup):
            secret[:]=bytes(len(secret))
            with RetiringSubmissionHost(k,g,a.socket,a.upload_socket,a.control_socket,a.submit_socket,a.jobs,a.control_state,a.submissions,public,a.control_revision,expected_jobs_pin=jp,expected_control_pin=cp,migrate_submissions=a.migrate_submissions,expected_submission_pin=sp,
                    deadline_ms=a.deadline_ms,max_connections=a.max_connections,drain_timeout=a.drain_timeout,control_deadline_ms=a.control_deadline_ms,control_max_connections=a.control_max_connections) as host:
                print(json.dumps({'state':'READY','profile':c.PROFILE,'keeper':k.public.hex(),'store':g.store_id.hex(),'control_policy_revision':a.control_revision,
                                  'diagnostics':host.diagnostics(),'startup_verification':startup,'product_qualified':False}),flush=True)
                while running:host.tick(.01)
                print(json.dumps({'state':'STOPPING','diagnostics':host.diagnostics(),'product_qualified':False}),flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({'state':'FAILED','code':getattr(exc,'code','CONTROL_HOST_ERROR'),'product_qualified':False}),file=sys.stderr,flush=True);return 1
    finally:
        if secret is not None:secret[:]=bytes(len(secret))
if __name__=='__main__':raise SystemExit(main())
