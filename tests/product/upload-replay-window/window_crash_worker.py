"""Owned child; public synthetic test keys only. Never detach process group."""
import os,sys,json,signal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT/'tools'))
import check_upload_window
from par_crypto.provider import SodiumProvider
from par_keeper_repair import KeeperRepair
from par_keeper.contract import authority_from
from par_wire.codec import decode
from par_upload_window import ReplaySpool
j=json.loads(Path(sys.argv[1]).read_text());hit=0
p=SodiumProvider(json.loads((ROOT/'policy/crypto-provider.json').read_text()),allow_legacy_experiment=True)
def observe(event):
    global hit
    if event==j['event']:
        hit+=1
        if hit==j.get('occurrence',1):
            print(json.dumps({'hit':event,'occurrence':hit,'pgid':os.getpgid(0)}),flush=True);os.kill(os.getpid(),signal.SIGKILL)
with KeeperRepair(j['keeper_root'],p,bytes.fromhex(j['seed']),authority_from(decode(bytes.fromhex(j['authority']))),quota_bytes=j['quota'],allow_unpatched_sqlite=True) as k:
    with ReplaySpool(k,j['root'],bytes.fromhex(j['store_id']),observer=observe) as s:
        args=[bytes.fromhex(x) for x in j['args']]
        getattr(s,j['action'])(*args)
raise RuntimeError('SIGKILL boundary not reached')
