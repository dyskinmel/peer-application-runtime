"""Owned synthetic process; real endpoints and scheduler, no detached worker."""
import os,sys,json,signal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT/'tools'))
import check_job_scheduler
from par_crypto.provider import SodiumProvider
from par_keeper_repair import KeeperRepair
from par_keeper.contract import authority_from
from par_wire.codec import decode
from par_upload_window import ReplaySpool
from par_job_scheduler import ScheduledHost
j=json.loads(Path(sys.argv[1]).read_text())
p=SodiumProvider(json.loads((ROOT/'policy/crypto-provider.json').read_text()),allow_legacy_experiment=True)
def observe(event):
    if event==j['event']:
        print(json.dumps({'hit':event,'pgid':os.getpgid(0)}),flush=True);os.kill(os.getpid(),signal.SIGKILL)
with KeeperRepair(j['keeper_root'],p,bytes.fromhex(j['seed']),authority_from(decode(bytes.fromhex(j['authority']))),quota_bytes=j['quota'],allow_unpatched_sqlite=True) as k:
    with ReplaySpool(k,j['root'],bytes.fromhex(j['store_id']),observer=observe) as g:
        with ScheduledHost(k,g,j['read_socket'],j['upload_socket'],j['jobs'],job_observer=observe) as host:
            host.schedule(bytes.fromhex(j['jid']))
            for _ in range(6):host.tick(0)
raise RuntimeError('SIGKILL boundary not reached')
