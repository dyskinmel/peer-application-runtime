"""Controlled local SIGKILL with public synthetic keys; inherits harness PGID."""
import sys,os,json,signal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT/'tools'))
import check_keeper_upload_retire
from par_crypto.provider import SodiumProvider
from par_keeper.contract import authority_from
from par_wire.codec import decode
from par_keeper_repair import KeeperRepair
from par_keeper_upload_retire import RetiringSpool

def main():
    job=json.loads(Path(sys.argv[1]).read_text())
    provider=SodiumProvider(json.loads((ROOT/'policy/crypto-provider.json').read_text()),allow_legacy_experiment=True)
    def observe(event):
        if event==job['event']:
            print(json.dumps({'hit':event,'pgid':os.getpgid(0)}),flush=True)
            os.kill(os.getpid(),signal.SIGKILL)
    with KeeperRepair(job['root'],provider,bytes.fromhex(job['seed']),authority_from(decode(bytes.fromhex(job['authority']))),quota_bytes=job['quota'],allow_unpatched_sqlite=True) as k:
        with RetiringSpool(k,job['stage_root'],allow_migrate=job['action']=='migrate',observer=observe) as s:
            if job['action']!='migrate':getattr(s,job['action'])(bytes.fromhex(job['request']))
    raise RuntimeError('requested SIGKILL boundary not reached')
if __name__=='__main__':main()
