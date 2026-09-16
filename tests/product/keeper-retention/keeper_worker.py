"""Owned disposable subprocess fault probe. No listening sockets or user paths."""
from pathlib import Path
import json,os,signal,sys
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_keeper import GROUPS
from auth_support import provider
from par_keeper import Keeper,Authority,Tick
from par_recovery.contract import Pin
j=json.loads(Path(sys.argv[1]).read_text());p=provider()
def hx(k):return bytes.fromhex(j[k])
a=Authority(j['app'],hx('space'),hx('head'),j['seq'],j['epoch'],hx('issuer'))
class Clock:
    def sample(self):return Tick(hx('boot'),j['ns'])
def observe(event):
    if event==j['kill']:
        Path(j['marker']).write_text(event);os.kill(os.getpid(),signal.SIGKILL)
k=Keeper(Path(j['root']),p,hx('seed'),a,quota_bytes=j['quota'],clock=Clock(),allow_unpatched_sqlite=True,observer=observe if j['action']=='initialize' else None)
k.observer=observe;act=j['action']
if act=='reserve':
    from par_keeper.contract import pin_from
    from par_wire.codec import decode
    k.reserve(hx('index'),pin_from(decode(hx('pin'))),30,hx('cap'),hx('call'))
elif act=='put':k.put(hx('lease'),hx('oid'),hx('raw'),hx('cap'),hx('call'))
elif act=='seal':k.seal(hx('lease'),hx('cap'),hx('call'))
elif act=='renew':k.renew(hx('lease'),30,hx('cap'),hx('call'))
elif act=='release':k.release(hx('lease'),hx('cap'),hx('call'))
elif act=='authority':
    from dataclasses import replace
    k.update_authority(replace(a,head=hx('new_head'),sequence=a.sequence+1))
elif act!='initialize':raise ValueError(act)
k.close();raise SystemExit('target fault boundary not reached')
