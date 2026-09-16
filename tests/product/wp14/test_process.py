import json,os,subprocess,sys,tempfile,textwrap,unittest
from pathlib import Path
R=Path(__file__).resolve().parents[3]
class ProcessTests(unittest.TestCase):
 def test_doctor_child_has_no_socket_egress(self):
  code="""import sys;sys.path.insert(0,sys.argv[1]);from product.wp14.par_native_provider import *;import socket;socket.socket=lambda *a,**k:(_ for _ in()).throw(RuntimeError('EGRESS'));d=experimental_posix_descriptor(epoch='11'*16);print(local_doctor(ProviderBundle(d))['result'])"""
  cp=subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(R)],capture_output=True,text=True,timeout=10)
  self.assertEqual(cp.returncode,0,cp.stderr);self.assertEqual(cp.stdout.strip(),'PASS')
 def test_epoch_change_while_factory_waits_closes_returned_connection(self):
  with tempfile.TemporaryDirectory() as td:
   ep=Path(td)/'epoch';ep.write_text('11'*16)
   code=textwrap.dedent("""
   import asyncio,sys,pathlib;sys.path.insert(0,sys.argv[1]);from product.wp14.par_native_provider import *
   ep=pathlib.Path(sys.argv[2]);closed=[]
   class C:
    peer='peer-a'
    async def close(self):closed.append(1)
   async def f(peer,cancel):print('FACTORY',flush=True);sys.stdin.readline();return C()
   async def main():
    d=experimental_posix_descriptor(epoch='11'*16);b=ProviderBundle(d,connection_factory=f,epoch_reader=lambda:ep.read_text())
    s=NativeProviderHandoff(b).open(d.epoch)
    try:await s.connect('peer-a',asyncio.Event())
    except Exception as e:print(type(e).__name__+':'+str(e),len(closed),flush=True);return
    print('UNEXPECTED',flush=True)
   asyncio.run(main())
   """)
   p=subprocess.Popen([sys.executable,'-I','-S','-B','-c',code,str(R),str(ep)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
   try:
    self.assertEqual(p.stdout.readline().strip(),'FACTORY');ep.write_text('22'*16);p.stdin.write('\n');p.stdin.flush();out=p.stdout.readline().strip();self.assertIn('PROVIDER_EPOCH_CHANGED 1',out);p.wait(timeout=5);self.assertEqual(p.returncode,0,p.stderr.read())
   finally:
    if p.poll()is None:p.kill()
    p.communicate()
    for stream in (p.stdin,p.stdout,p.stderr):
     if stream is not None: stream.close()
 def test_missing_provider_child_is_blocked(self):
  code="""import sys;sys.path.insert(0,sys.argv[1]);from product.wp14.par_native_provider import *;print(local_doctor(None)['result'])"""
  cp=subprocess.run([sys.executable,'-I','-S','-B','-c',code,str(R)],capture_output=True,text=True,timeout=10);self.assertEqual(cp.stdout.strip(),'BLOCKED')
