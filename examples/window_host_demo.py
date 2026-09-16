#!/usr/bin/env python3
"""Synthetic disposable Linux demo: retire/rollover, three processes, donor-free recovery."""
import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
import tools.check_window_host
from host_process_support import ProcessTest,h
from par_keeper.contract import pin_values
from par_window_host.protocol import dump
import hashlib,subprocess,os

def main():
    t=ProcessTest();t.setUp()
    try:
        t.start_host();raw=t.bundle.index
        q=t.uclient.command('begin',h('demo-unfinished'),['index',t.rpin.index_id,len(raw),hashlib.sha256(raw).digest()])
        t.beginraw=t.w.check_command(t.p,t.grant,q)[4];token=t.uclient.execute(q)[0];t.uclient.chunk(token,0,raw[:24]);t.stop_process()
        t.admin('retire',t.wrap(t.retirement_request(authority=t.authority),'retire'))
        cleaned=t.close_offline();t.open_next_offline(cleaned);t.start_host()
        job=Path(t.tmp.name)/'donor.json';job.write_text(json.dumps({'socket':str(t.upload_path),'keeper':t.kp.hex(),'seed':t.cs.hex(),'cap':t.cap.hex(),'store':t.store_id.hex(),'window':t.grant.hex(),'index':t.bundle.index.hex(),'pin':dump(pin_values(t.rpin),65536).hex(),'objects':{k.hex():v.hex() for k,v in t.bundle.objects.items()}}));job.chmod(0o600)
        cp=subprocess.run([sys.executable,'-I','-S',str(ROOT/'tests/product/upload-window-host/host_donor_worker.py'),str(job)],capture_output=True,timeout=45,env={'PATH':os.environ.get('PATH','')})
        if cp.returncode:raise RuntimeError(cp.stderr.decode())
        t.lid=bytes.fromhex(json.loads(cp.stdout)['lease']);job.unlink()
        expected=t.remove_donor();result=t.run_receiver(t.job())
        if result['sha256']!=expected:raise RuntimeError('restored file mismatch')
        print(json.dumps({'result':'PASS','synthetic_keys_only':True,'generation':2,'offline_retirement_and_rollover':True,'donor_removed':True,'separate_donor_host_recipient':True,'file_sha256':expected,'recovery_status':result['status'],'public_network':False,'product_qualified':False},indent=2))
    finally:t.tearDown()
if __name__=='__main__':main()
