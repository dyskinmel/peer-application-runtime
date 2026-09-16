"""No absent package can count as a passing Automerge run."""
import json,subprocess,sys,tempfile,unittest
from pathlib import Path
from product.wp04.core_port import NodeCorePort
from product.wp04.contracts import SharedChangeError
ROOT=Path(__file__).resolve().parents[3]
class CorePortTests(unittest.TestCase):
 def test_absent_manifest_is_blocked_not_mock(self):
  with tempfile.TemporaryDirectory() as p:
   with self.assertRaises(SharedChangeError) as e:NodeCorePort(Path(p)/'absent.json')
   self.assertEqual(e.exception.code,'CORE_UNAVAILABLE')
 def test_manifest_must_be_absolute(self):
  with self.assertRaises(SharedChangeError) as e:NodeCorePort(Path('relative.json'))
  self.assertEqual(e.exception.code,'CORE_MANIFEST_INVALID')
 def test_invalid_manifest_refused(self):
  with tempfile.TemporaryDirectory() as p:
   f=Path(p)/'bad.json';f.write_text('{}')
   with self.assertRaises(SharedChangeError) as e:NodeCorePort(f)
   self.assertEqual(e.exception.code,'CORE_MANIFEST_INVALID')
 def test_timeout_bounded(self):
  with self.assertRaises(SharedChangeError):NodeCorePort(Path('/absent'),timeout=61)
 def test_bool_timeout_refused(self):
  with self.assertRaises(SharedChangeError):NodeCorePort(Path('/absent'),timeout=True)
 def test_real_worker_absent_is_exit_78(self):
  cp=subprocess.run(['node',str(ROOT/'product/wp04/core_worker.mjs'),'/no-such-core-par32.json'],capture_output=True,text=True,timeout=10)
  self.assertEqual(cp.returncode,78);self.assertEqual(json.loads(cp.stdout),{'ok':False,'code':'CORE_UNAVAILABLE'})
