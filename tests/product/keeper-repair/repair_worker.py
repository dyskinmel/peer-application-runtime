"""Owned synthetic child with deterministic fault boundary markers."""
import json,os,signal,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_keeper_repair import GROUPS
from auth_support import provider
from par_keeper import Authority,Tick
from par_keeper_repair import KeeperRepair
j=json.loads(Path(sys.argv[1]).read_text())
def hx(k):return bytes.fromhex(j[k])
a=Authority(j['app'],hx('space'),hx('head'),j['sequence'],j['epoch'],hx('issuer'))
class Clock:
    def sample(self):return Tick(hx('boot'),j['ns'])
seen=0

def observe(event):
    global seen
    if event==j['kill']:
        seen+=1
        if seen==j.get('occurrence',1):
            Path(j['marker']).write_text(event);os.kill(os.getpid(),signal.SIGKILL)
k=KeeperRepair(Path(j['root']),provider(),hx('seed'),a,quota_bytes=j['quota'],clock=Clock(),allow_unpatched_sqlite=True,migrate_v2=j['action']=='migration',observer=observe if j['action']=='migration' else None)
if j['action']!='migration':
    k.observer=observe
    if j['action']=='repair':k.repair(hx('lease'),{bytes.fromhex(i):bytes.fromhex(v) for i,v in j['objects'].items()},hx('cap'),hx('request'))
    else:k.cancel_repair(hx('lease'),hx('cap'),hx('cancel'))
k.close();raise SystemExit('fault boundary not reached')
