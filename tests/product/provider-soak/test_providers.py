"""Reusable contract against injected providers, with lying-provider controls."""
import dataclasses,importlib,os,subprocess,signal,sys,unittest
from pathlib import Path
class ProviderTests(unittest.TestCase):
 def setUp(self):
  from tools import check_application_intent
  from intent_support import JournalTest
  self.f=JournalTest();self.f.setUp();self.addCleanup(self.f.doCleanups)
  self.j=self.f.create();self.p0=self.j.pin();self.j.prepare(self.f.intent);self.p1=self.j.pin();self.root=self.f.parent/'pins'
  self.m=importlib.import_module('product.wp13.par_soak')
  self.assertTrue(hasattr(self.m,'pin_conformance'),'common provider conformance runner missing')
  from product.wp09.par_application_intent import LocalPinStore
  self.create=lambda:LocalPinStore.create(self.root,self.f.intent.binding(),self.p0)
  self.reopen=lambda:LocalPinStore.open(self.root,self.f.intent.binding())
 def test_local_pin_contract_passes_and_reopens(self):
  r=self.m.pin_conformance(self.create,self.reopen,self.p0,self.p1)
  self.assertEqual(r['result'],'PASS');self.assertFalse(r['os_protection_proven'])
 def test_missing_provider_is_blocked_without_fallback(self):
  r=self.m.pin_conformance(None,None,self.p0,self.p1)
  self.assertEqual(r['result'],'BLOCKED');self.assertFalse(self.root.exists())
 def test_ack_without_storing_is_detected(self):
  from product.wp09.par_application_intent import PinStore
  base=self.create
  class Liar(PinStore):
   def __init__(s):s.real=base();s.binding=s.real.binding
   def load(s):return s.real.load()
   def advance(s,a,b):pass
   def close(s):s.real.close()
  with self.assertRaisesRegex(Exception,'READBACK'):self.m.pin_conformance(Liar,self.reopen,self.p0,self.p1)
 def test_readback_only_memory_does_not_pass_reopen(self):
  from product.wp09.par_application_intent import PinStore
  base=self.create
  class Volatile(PinStore):
   def __init__(s):s.real=base();s.binding=s.real.binding;s.value=self.p0
   def load(s):return s.value
   def advance(s,a,b):s.value=b
   def close(s):s.real.close()
  with self.assertRaisesRegex(Exception,'REOPEN'):self.m.pin_conformance(Volatile,self.reopen,self.p0,self.p1)
 def test_external_exception_not_expected_rejection(self):
  base=self.reopen
  def bad():
   p=base();p.advance=lambda *a:(_ for _ in()).throw(OSError('provider offline'));return p
  with self.assertRaises(OSError):self.m.pin_conformance(self.create,bad,self.p0,self.p1)
 def test_unrelated_pin_not_allowed_as_next(self):
  bad=dataclasses.replace(self.p1,metadata_digest='f'*64)
  with self.assertRaisesRegex(Exception,'CONFORMANCE_INPUT'):self.m.pin_conformance(self.create,self.reopen,self.p0,bad)
 def test_second_process_owner_and_sigkill_release(self):
  p=self.create();p.close();r=Path(__file__).resolve().parents[3]
  code="import sys,time;sys.path.insert(0,sys.argv[1]);from tools import check_application_intent;from product.wp09.par_application_intent import LocalPinStore;p=LocalPinStore.open(sys.argv[2],bytes.fromhex(sys.argv[3]));print('LOCKED',flush=True);sys.stdin.read()"
  child=subprocess.Popen([sys.executable,'-I','-S','-B','-c',code,str(r),str(self.root),self.f.intent.binding().hex()],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  try:
   import select
   self.assertTrue(select.select([child.stdout],[],[],10)[0]);self.assertEqual(child.stdout.readline(),b'LOCKED\n')
   with self.assertRaisesRegex(Exception,'PIN_STORE_LOCKED'):self.reopen()
   child.kill();child.communicate(timeout=5);self.assertEqual(child.returncode,-signal.SIGKILL)
   p=self.reopen();self.assertEqual(p.load(),self.p0);p.close()
  finally:
   if child.poll()is None:child.kill()
   child.communicate()
