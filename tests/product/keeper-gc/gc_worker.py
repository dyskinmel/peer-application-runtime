"""Owned disposable child process; no network and no user data."""
import json,os,signal,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_keeper_gc import GROUPS
from auth_support import provider
from par_keeper import Authority,Tick
from par_keeper_gc import KeeperGC
j=json.loads(Path(sys.argv[1]).read_text());p=provider()
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
k=KeeperGC(Path(j['root']),p,hx('seed'),a,quota_bytes=j['quota'],clock=Clock(),allow_unpatched_sqlite=True,
    migrate_v1=j['action']=='migration',observer=observe if j['action']=='migration' else None)
if j['action']=='collect':
    k.observer=observe;k.collect(hx('lease'),hx('cap'),hx('request'))
k.close();raise SystemExit('fault boundary not reached')
