"""Synthetic child; terminates only itself at a declared persistence boundary."""
import os,sys,json,signal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT/'tools'))
import check_job_submit
from par_crypto.provider import SodiumProvider
from par_keeper_repair import KeeperRepair
from par_keeper.contract import authority_from
from par_wire.codec import decode
from par_upload_window import ReplaySpool
from par_job_control import ControlledHost
from par_job_submit.staging import Submissions
q=json.loads(Path(sys.argv[1]).read_text())
p=SodiumProvider(json.loads((ROOT/'policy/crypto-provider.json').read_text()),allow_legacy_experiment=True)
def hit(event):
    if event==q['event']:
        print(json.dumps({'hit':event,'pgid':os.getpgid(0)}),flush=True);os.kill(os.getpid(),signal.SIGKILL)
with KeeperRepair(q['keeper'],p,bytes.fromhex(q['seed']),authority_from(decode(bytes.fromhex(q['authority']))),quota_bytes=q['quota'],allow_unpatched_sqlite=True) as k:
    with ReplaySpool(k,q['spool'],bytes.fromhex(q['store'])) as g:
        with ControlledHost(k,g,q['read'],q['upload'],q['control'],q['jobs'],q['journal'],bytes.fromhex(q['operator']),1) as host:
            stage=Submissions(host.controller,q['stage'],observer=hit)
            try:
                d=bytes.fromhex(q['descriptor'])
                if q['operation']=='begin':stage.begin(d)
                elif q['operation']=='chunk':stage.chunk(d,0,bytes.fromhex(q['payload']))
                elif q['operation']=='submit':stage.submit(d)
                else:raise RuntimeError('unknown fixture operation')
            finally:stage.close()
raise RuntimeError('requested boundary was not reached')
