import json,os,signal,subprocess,sys,time
from pathlib import Path
from exchange_support import ExchangeTest,h
from par_keeper_service.transport import recover_stale,socket_identity
WORKER=Path(__file__).with_name('worker.py')

class ProcessTests(ExchangeTest):
    def spawn(self,mode,root,sock,marker):
        log=open(self.root.parent/(mode+'-child.log'),'ab');self.addCleanup(log.close)
        child=subprocess.Popen([sys.executable,'-I','-S','-B',str(WORKER),mode,str(root),str(sock),str(marker)],stdout=log,stderr=log)
        self.addCleanup(self.stop,child)
        return child
    def stop(self,child):
        if child.poll() is None:child.terminate()
        try:child.wait(timeout=3)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=3)
    def wait_file(self,child,path):
        end=time.monotonic()+8
        while not path.exists() and time.monotonic()<end:
            self.assertIsNone(child.poll(),'fixture child exited before ready');time.sleep(.01)
        self.assertTrue(path.exists(),'fixture did not signal readiness')
    def serve(self):
        marker=self.root.parent/'ready.json';child=self.spawn('serve',self.root.parent/'source',self.socket_path,marker);self.wait_file(child,marker);return child,marker
    def test_separate_process_reads(self):
        child,_=self.serve();cli=self.client();r=cli.need([h('inner:a')]);raw,cert=cli.fetch(r[0],r[1][0][1])
        self.assertEqual(self.cid(raw),h('inner:a'));self.assertNotEqual(child.pid,os.getpid());self.assertEqual(os.getpgid(child.pid),os.getpgrp())
    def test_receiver_sigkill_then_explicit_missing_only_resume(self):
        source,_=self.serve();marker=self.root.parent/'receiver-pin.json';root=self.root.parent/'recipient'
        receiver=self.spawn('partial',root,self.socket_path,marker);self.wait_file(receiver,marker)
        os.kill(receiver.pid,signal.SIGKILL);self.assertEqual(receiver.wait(timeout=3),-signal.SIGKILL)
        cp=subprocess.run([sys.executable,'-I','-S','-B',str(WORKER),'finish',str(root),str(self.socket_path),str(marker)],capture_output=True,text=True,timeout=12)
        self.assertEqual(cp.returncode,0,cp.stderr);out=json.loads(cp.stdout)
        self.assertEqual(out['usage']['records'],2);self.assertEqual(out['view']['state'],'READY_FOR_CORE');self.assertEqual(out['core']['state'],'CORE_BLOCKED');self.assertFalse(out['view']['applied'])
    def test_provider_sigkill_no_silent_stale_socket_removal(self):
        child,marker=self.serve();cli=self.client();r=cli.need([h('inner:a')]);identity=socket_identity(self.socket_path)
        os.kill(child.pid,signal.SIGKILL);self.assertEqual(child.wait(timeout=3),-signal.SIGKILL)
        self.assertTrue(self.socket_path.exists())
        self.reject_exchange('CONNECTION_UNAVAILABLE',lambda:cli.need([h('inner:a')]))
        recover_stale(self.socket_path,identity);marker.unlink()
        restarted=self.spawn('serve',self.root.parent/'source',self.socket_path,marker);self.wait_file(restarted,marker)
        rr=cli.need([h('inner:a')]);self.assertEqual(r[1],rr[1]);self.assertNotEqual(r[0],rr[0]);self.reject_exchange('REMOTE_STALE_VIEW',lambda:cli.fetch(r[0],r[1][0][1]));self.assertEqual(self.cid(cli.fetch(rr[0],rr[1][0][1])[0]),h('inner:a'))
