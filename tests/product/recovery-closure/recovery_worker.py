"""Owned subprocess fault/independent-process replay of public synthetic fixtures."""
from pathlib import Path
import sys,os,signal,json
ROOT=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True;sys.path.insert(0,str(ROOT))
from tools.check_recovery import GROUPS
from par_recovery import Inbox,DirectoryProvider,Pin,open_recovery
from par_wire.codec import decode
from auth_support import provider,h

def main():
    mode,source,inbox,dest,pinfile,event=sys.argv[1:]
    pp=decode(Path(pinfile).read_bytes());pp[7]=tuple(pp[7]);pin=Pin(*pp);p=provider()
    def stop(name):
        if name==event:os.kill(os.getpid(),signal.SIGKILL)
    if mode=='open':
        v=open_recovery(Path(source),pin,p,h('recipient-1'));v.export_file(pin.roots[0],Path(dest))
        print(json.dumps(v.status()));return
    index=(Path(source)/'index.cbor').read_bytes();remote=DirectoryProvider(Path(source),index,pin)
    with Inbox(Path(inbox),index,pin,observer=stop) as rx:
        while rx.missing():
            result=rx.pull(remote,limit=32)
            if result['received']==0:raise RuntimeError('fixture missing')
        rx.finalize(Path(dest),p,h('recipient-1'))
    if event!='none':raise RuntimeError('fault hook not reached')
if __name__=='__main__':main()
