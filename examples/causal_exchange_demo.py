#!/usr/bin/env python3
"""Public synthetic data, actual separate processes. Does not touch user stores."""
import json,os,signal,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.dont_write_bytecode=True
W=ROOT/'tests/product/causal-exchange/worker.py'
def wait(p,path):
 end=time.monotonic()+8
 while not path.exists() and time.monotonic()<end:
  if p.poll() is not None:raise RuntimeError('fixture stopped: '+p.stderr.read().decode())
  time.sleep(.01)
 if not path.exists():raise RuntimeError('fixture readiness timeout')
def main():
 with tempfile.TemporaryDirectory(prefix='par-causal-demo-') as tmp:
  t=Path(tmp);sock=t/'exchange.sock';ready=t/'source.json';pin=t/'recipient.json';children=[]
  try:
   def spawn(mode,root,marker):
    p=subprocess.Popen([sys.executable,'-I','-S','-B',str(W),mode,str(root),str(sock),str(marker)],stdout=subprocess.PIPE,stderr=subprocess.PIPE);children.append(p);return p
   source=spawn('serve',t/'source',ready);wait(source,ready)
   receiver=spawn('partial',t/'recipient',pin);wait(receiver,pin)
   first=json.loads(pin.read_text());os.kill(receiver.pid,signal.SIGKILL);receiver.wait(timeout=3)
   resumed=spawn('finish',t/'recipient',pin);out,err=resumed.communicate(timeout=15)
   if resumed.returncode:raise RuntimeError(err.decode())
   result=json.loads(out)
   print(json.dumps({'scope':'LOCAL_PRIVATE_IPC_PUBLIC_OPAQUE_FIXTURES','source_pid':source.pid,'receiver_first_pid':receiver.pid,'receiver_resumed_pid':resumed.pid,'first_ack':first['receipt'],'final':result,'real_core_executed':False,'application_applied':False},indent=2))
  finally:
   for p in children:
    if p.poll() is None:p.terminate()
    try:p.wait(timeout=3)
    except subprocess.TimeoutExpired:p.kill();p.wait(timeout=3)
    if p.stdout:p.stdout.close()
    if p.stderr:p.stderr.close()
 return 0
if __name__=='__main__':raise SystemExit(main())
