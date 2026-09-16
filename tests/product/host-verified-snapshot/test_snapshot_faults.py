import os, json, subprocess, sys
from unittest.mock import patch
from snapshot_support import SnapshotTest,h

class SnapshotFaults(SnapshotTest):
    def test_non_none_backend_result_rejected(self):
        self.p.close();original=self.base.verify
        def bad(*args):original(*args);return True
        self.base.verify=bad;self.p=self.m.VerificationProvider(self.base,mode='signatures')
        self.err('BACKEND_CONTRACT',self.verify);self.assertEqual(self.p.statistics()['entries'],0)
    def test_provider_changes_during_backend_rejected(self):
        self.p.close();original=self.base.verify
        def changed(*args):original(*args);self.base.identity['version']='changed'
        self.base.verify=changed;self.p=self.m.VerificationProvider(self.base,mode='signatures')
        self.err('PROVIDER_CHANGED',self.verify);self.assertEqual(self.p.statistics()['entries'],0)
    def test_backend_exception_not_cached(self):
        self.p.close()
        def failure(*args):raise OSError('injected provider failure')
        self.base.verify=failure;self.p=self.m.VerificationProvider(self.base,mode='signatures')
        for _ in range(2):
            with self.assertRaises(OSError):self.verify()
        self.assertEqual(self.p.statistics()['entries'],0);self.assertEqual(self.p.statistics()['backend_calls'],2)
    def test_mutable_invalid_clears_prior_success(self):
        self.verify();self.err('INVALID_INPUT',lambda:self.verify(msg=memoryview(self.msg)));self.assertEqual(self.p.statistics()['entries'],0)
    def test_decrypt_failure_clears_success_not_cached(self):
        self.verify();key=h('key');self.err('AEAD_INVALID',lambda:self.p.open(key,b'z'*24,b'',b'q'*16));self.assertEqual(self.p.statistics()['entries'],0)
    def test_same_digest_different_bytes_does_not_hit(self):
        # No digest function participates in the key; replacing a common hash
        # function cannot turn differing messages into a reused success.
        self.verify()
        with patch('hashlib.sha256',return_value=object()):self.err('SIGNATURE_INVALID',lambda:self.verify(msg=b'not the signed message'))
    def test_fork_refuses_inherited_warm_provider(self):
        self.verify();r,w=os.pipe();pid=os.fork()
        if pid==0:
            os.close(r)
            try:self.verify();out=b'ACCEPTED'
            except Exception as e:out=getattr(e,'code','unexpected').encode()
            os.write(w,out);os.close(w);os._exit(0)
        os.close(w)
        try:
            got=os.read(r,128);_,status=os.waitpid(pid,0)
            self.assertEqual(status,0);self.assertEqual(got,b'OWNER_REQUIRED');self.verify();self.assertEqual(self.p.statistics()['hits'],1)
        finally:os.close(r)
    def test_distinct_provider_instances_do_not_share(self):
        self.verify();p=self.m.VerificationProvider(self.base,mode='signatures')
        try:p.verify(self.pk,self.msg,self.sig);self.assertEqual(p.statistics()['hits'],0)
        finally:p.close()
    def test_provider_failure_does_not_fall_back_to_full(self):
        self.verify();self.base.identity['path']='other';self.err('PROVIDER_CHANGED',self.verify);self.assertTrue(self.p.statistics()['poisoned'])
    def test_no_cache_serialization_method(self):
        for name in ('save','load','export','restore'):self.assertFalse(hasattr(self.p,name))
