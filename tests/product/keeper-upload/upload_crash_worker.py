"""Controlled SIGKILL at a named local publication boundary; synthetic data only."""
import json,sys,os,signal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools'));sys.dont_write_bytecode=True
import keeper_upload_host
from par_keeper.contract import authority_from
from par_wire.codec import decode
from par_crypto.provider import SodiumProvider
from par_keeper_repair import KeeperRepair
from par_keeper_upload.spool import Spool

def main():
    j=json.loads(Path(sys.argv[1]).read_text());p=SodiumProvider(json.loads((ROOT/'policy/crypto-provider.json').read_text()),allow_legacy_experiment=True)
    def observe(event):
        if event==j['event']:
            print(json.dumps({'hit':event}),flush=True);os.kill(os.getpid(),signal.SIGKILL)
    with KeeperRepair(j['root'],p,bytes.fromhex(j['seed']),authority_from(decode(bytes.fromhex(j['authority']))),quota_bytes=j['quota'],allow_unpatched_sqlite=True) as k:
        with Spool(k,k.root/'incoming-upload') as s:
            k.observer=observe;s.observer=observe;s.execute(bytes.fromhex(j['command']))
    raise RuntimeError('requested kill boundary was not reached')
if __name__=='__main__':main()
