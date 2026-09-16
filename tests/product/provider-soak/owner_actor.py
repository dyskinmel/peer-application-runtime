"""Persistent read-only owner actor. Setup is synthetic; wire/files/SQLite are real.

All sockets are private preconnected socketpairs; no server/listener is created.
Gate injection happens in this test adapter, never in production classes.
"""
from pathlib import Path
import sys,os,json,socket,asyncio,time,gc,hashlib
R=Path(__file__).resolve().parents[3];sys.dont_write_bytecode=True;sys.path.insert(0,str(R))
from tools import check_application_intent
from anchored_process_support import open_anchored_runtime
from product.wp09.par_application_owner import ApplicationOwner,serve_application_connected
from product.wp13.par_soak.metrics import sample_python

def send(v):print(json.dumps(v,separators=(',',':')),flush=True)

async def main():
    spec=json.loads(Path(sys.argv[1]).read_text());fds=json.loads(sys.argv[2]);f=open_anchored_runtime(spec)
    owner=None;leaks=[];tasks=[]
    try:
        f.app._core=None  # No real or simulated materializer is called by the campaign.
        f.d.prepare(b'o'*16,expected_revision=0,expected_observation=f.c.observe()['revision'])
        owner=ApplicationOwner(f.d);ch=owner.attach();context=owner.context(ch);owner.detach(ch)
        initial_pin=f.j.pin();initial_counts=f.nums()
        def data_digest():
            sql='\n'.join(f.db._storage.connection.iterdump()).encode()
            h=hashlib.sha256(sql)
            for path in sorted(f.box.root.rglob('*')):
                if path.is_file():h.update(str(path.relative_to(f.box.root)).encode());h.update(path.read_bytes())
            return h.hexdigest()
        initial_digest=data_digest()
        original_run=owner._run;scenario=None;round_id=None
        async def gated(channel,op,args,future,cancel,deadline):
            if scenario in ('cancel','timeout','disconnect')and op=='observe':
                send({'kind':'entered','round':round_id});await cancel.wait()
            return await original_run(channel,op,args,future,cancel,deadline)
        owner._run=gated
        reader=asyncio.StreamReader();protocol=asyncio.StreamReaderProtocol(reader)
        pipe,_=await asyncio.get_running_loop().connect_read_pipe(lambda:protocol,sys.stdin)
        try:
            send({'kind':'ready','context':context,'targets':[f.target.hex()],'pgid':os.getpgrp(),'pid':os.getpid()})
            used=0
            while line:=await reader.readline():
                command=json.loads(line)
                if command['cmd']=='exit':break
                assert command['cmd']=='round'and used<len(fds)
                scenario=command['scenario'];round_id=command['round'];fd=fds[used];used+=1
                sock=socket.socket(fileno=fd);send({'kind':'serving','round':round_id})
                started=time.monotonic_ns()
                await serve_application_connected(owner,sock,read_timeout=30,write_timeout=30)
                await asyncio.sleep(0);await asyncio.sleep(0)
                if command.get('leak_fd'):leaks.append(os.open('/dev/null',os.O_RDONLY))
                if command.get('leak_task'):tasks.append(asyncio.create_task(asyncio.Event().wait()))
                stats=owner.stats();m=sample_python(fds[used:]);m.update(channels=stats['channels'],inflight=stats['inflight'])
                digest=data_digest();unchanged=f.j.pin()==initial_pin and f.nums()==initial_counts and f.port.calls==0 and digest==initial_digest
                send({'kind':'done','round':round_id,'python':m,'readonly_unchanged':unchanged,'initial_data_digest':initial_digest,'data_digest':digest,
                      'duration_us':(time.monotonic_ns()-started)//1000,'real_core_executed':False})
        finally:pipe.close()
    finally:
        for t in tasks:t.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)
        for fd in leaks:os.close(fd)
        if owner:await owner.close()
        f.doCleanups()
        for fd in fds:
            try:os.close(fd)
            except OSError:pass

if __name__=='__main__':asyncio.run(main())
