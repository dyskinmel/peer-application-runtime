import hashlib,importlib,json,os,select,signal,socket,subprocess,sys,time
from pathlib import Path
from host_support import HostTest,h,pr
from par_keeper.contract import authority_body,pin_values
from par_keeper_service.transport import receive,send,frame
from service_support import ROOT
import test_service_recovery as recovery_tests

class ProcessTest(HostTest):
    job=recovery_tests.ServiceRecovery.job
    remote=recovery_tests.ServiceRecovery.remote
    remove_donor=recovery_tests.ServiceRecovery.remove_donor
    run_receiver=recovery_tests.ServiceRecovery.run_receiver
    def setUp(self):
        super().setUp()
        self.assertTrue((ROOT/'tools/keeper_window_host.py').is_file(),'window host CLI is not implemented')
        self.assertTrue((ROOT/'tools/upload_window_admin.py').is_file(),'offline admin CLI is not implemented')
        self.cpmod=importlib.import_module('par_window_host.client');self.hmod=importlib.import_module('par_window_host.host')
        self.cfgpath=Path(self.tmp.name)/'window-host.cbor';self.write_cfg()
    def write_cfg(self):
        self.cfg={0:1,1:self.hp.PROFILE,2:self.kp,3:authority_body(self.authority),4:self.total*3,5:32,6:4096,
                  7:self.store_id,8:self.window.pin(),9:16*1024*1024,10:1024,11:64*1024*1024,12:64}
        self.cfgpath.write_bytes(pr.dump(self.cfg,16384));self.cfgpath.chmod(0o600)
    def host_args(self):
        return [sys.executable,'-I','-S',str(ROOT/'tools/keeper_window_host.py'),'--root',str(self.path),'--spool',str(self.wroot),
                '--socket',str(self.socket_path),'--upload-socket',str(self.upload_path),'--host-config',str(self.cfgpath),
                '--key-fd','0','--deadline-ms','1500','--allow-unpatched-sqlite','--allow-legacy-sodium']
    def start_host(self):
        if self.window is not None:self.window.close();self.window=None
        if self.keeper is not None:self.keeper.close();self.keeper=None
        self.process=subprocess.Popen(self.host_args(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=ROOT,env={'PATH':os.environ.get('PATH','')})
        self.process.stdin.write(self.ks);self.process.stdin.close();self.process.stdin=None
        self.assertTrue(select.select([self.process.stdout],[],[],6)[0],'host startup deadline')
        line=self.process.stdout.readline();self.assertTrue(line,self.process.stderr.read().decode() if self.process.poll() is not None else 'missing ready')
        self.assertEqual(json.loads(line)['state'],'READY')
        self.uclient=self.cpmod.Client(self.upload_path,self.p,self.kp,self.cs,self.cap,self.store_id,self.grant,timeout=3)
        self.client=self.ipc.Client(self.socket_path,self.p,self.kp,self.cs,self.cap,timeout=3)
    def send_bundle(self):
        self.lid,rc=self.uclient.upload_bundle(self.bundle.index,self.rpin,self.bundle.objects,30,h('stable-root'));return self.lid,rc
    def admin(self,action,command=None,archive=None,expect=0):
        n=str(self.counter);self.counter+=1;dest=Path(self.tmp.name)/('admin-'+n+'.bin')
        args=[sys.executable,'-I','-S',str(ROOT/'tools/upload_window_admin.py'),'--root',str(self.path),'--spool',str(self.wroot),
              '--host-config',str(self.cfgpath),'--key-fd','0','--action',action,'--output',str(dest),'--allow-unpatched-sqlite','--allow-legacy-sodium']
        for label,data in (('command',command),('archive',archive)):
            if data is not None:
                p=dest.with_suffix('.'+label);p.write_bytes(data);p.chmod(0o600);args+=['--'+label,str(p)]
        cp=subprocess.run(args,input=self.ks,capture_output=True,timeout=15,env={'PATH':os.environ.get('PATH','')})
        self.assertEqual(cp.returncode,expect,cp.stderr.decode());return dest.read_bytes() if cp.returncode==0 else cp
    def close_offline(self):
        archive=self.admin('export');req=self.w.approve_close(self.p,self.s.owner,self.authority,self.grant,archive,h('close-'+str(self.counter)))
        self.admin('close',req,archive);return self.admin('compact')
    def open_next_offline(self,receipt):
        self.grant=self.grant_for(2,self.w.digest(receipt),authority=self.authority);self.admin('open',self.grant)
    def recover_sockets(self,ids):
        for p,identity in ids.items():self.ipc.recover_stale(p,identity)
