import hashlib,importlib,os,subprocess,sys
from pathlib import Path
from host_support import HostTest,h,pr
from host_process_support import ProcessTest,ROOT
from par_keeper.contract import split
class ResponseHardening(HostTest):
    def setUp(self):
        super().setUp();self.client=importlib.import_module('par_window_host.client')
    def begin_body(self):return pr.check_command(self.p,self.w.check_command(self.p,self.grant,self.command())[4])
    def progress(self,b):
        from par_crypto.primitives import hashed
        cap,_=split(b[4]);return {0:hashed('keeper-upload-local/stage',[cap[3],cap[4],b[3]]),1:0,2:b[7][2],3:hashlib.sha256(b'').digest(),4:False,5:False}
    def test_response_wrong_token(self):
        b=self.begin_body();r=self.progress(b);r[0]=h('wrong');self.err('RESPONSE_SCOPE',lambda:self.client.validate_result(self.p,b,r))
    def test_response_wrong_size(self):
        b=self.begin_body();r=self.progress(b);r[2]+=1;self.err('RESPONSE_SCOPE',lambda:self.client.validate_result(self.p,b,r))
    def test_response_boolean_size_rejected(self):
        b=self.begin_body();r=self.progress(b);r[2]=True;self.err(None,lambda:self.client.validate_result(self.p,b,r))
    def test_response_false_product_claim_rejected(self):
        b=self.begin_body();r=self.progress(b);r[5]=True;self.err(None,lambda:self.client.validate_result(self.p,b,r))
    def test_response_empty_prefix_hash_rejected(self):
        b=self.begin_body();r=self.progress(b);r[3]=h('false-empty');self.err('RESPONSE_SCOPE',lambda:self.client.validate_result(self.p,b,r))
    def test_response_complete_begin_hash_rejected(self):
        b=self.begin_body();r=self.progress(b);r[1]=r[2];r[3]=h('false-complete');self.err('RESPONSE_SCOPE',lambda:self.client.validate_result(self.p,b,r))
    def test_response_snapshot_copy_not_alias(self):
        b=self.begin_body();r=self.progress(b);v=self.client.validate_result(self.p,b,r);r[0]=h('mutated');self.assertNotEqual(v[0],r[0])
    def test_client_never_accepts_unwrapped_command(self):
        c=self.client.Client(self.upload_path,self.p,self.kp,self.cs,self.cap,self.store_id,self.grant)
        self.err(None,lambda:c.execute(self.cmd('progress',h('stage'))))
    def test_subprocess_group_not_detached(self):
        cp=subprocess.run([sys.executable,'-c','import os;print(os.getpgrp())'],capture_output=True,check=True)
        self.assertEqual(int(cp.stdout),os.getpgrp())

class AdminHardening(ProcessTest):
    def test_output_exists_refuses_before_compaction(self):
        self.window.close();self.window=None;self.keeper.close();self.keeper=None
        dest=Path(self.tmp.name)/'exists';dest.write_bytes(b'keep');dest.chmod(0o600)
        args=[sys.executable,'-I','-S',str(ROOT/'tools/upload_window_admin.py'),'--root',str(self.path),'--spool',str(self.wroot),'--host-config',str(self.cfgpath),'--key-fd','0','--action','compact','--output',str(dest),'--allow-unpatched-sqlite','--allow-legacy-sodium']
        cp=subprocess.run(args,input=self.ks,capture_output=True,timeout=6);self.assertNotEqual(cp.returncode,0);self.assertIn(b'OUTPUT_EXISTS',cp.stderr);self.assertEqual(dest.read_bytes(),b'keep')
    def test_completed_admin_retry_inspect_is_stable(self):
        self.window.close();self.window=None;self.keeper.close();self.keeper=None
        self.assertEqual(self.admin('inspect'),self.admin('inspect'))
    def test_admin_rejects_extra_archive_for_inspect(self):self.err('ADMIN_INPUT',lambda:self.hmod.administer(self.window,'inspect',archive=b'data'))
    def test_wrong_minimum_pin_rejects_before_listener(self):
        self.cfg[8][2]=h('wrong');self.cfgpath.write_bytes(pr.dump(self.cfg,16384));self.window.close();self.window=None;self.keeper.close();self.keeper=None
        cp=subprocess.run(self.host_args(),input=self.ks,capture_output=True,timeout=6);self.assertNotEqual(cp.returncode,0);self.assertIn(b'WINDOW_PIN',cp.stderr);self.assertFalse(self.upload_path.exists())
