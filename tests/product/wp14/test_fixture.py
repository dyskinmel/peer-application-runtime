import json,unittest
from pathlib import Path
R=Path(__file__).resolve().parents[3]
class FixtureTests(unittest.TestCase):
 def setUp(self):self.f=json.loads((R/'product/wp14/provider-lifetime-fixture.json').read_text())
 def test_exact_profile_and_states(self):
  self.assertEqual(self.f['profile'],'par-native-provider-lifetime-0056');self.assertEqual(self.f['states'],['NEW','ACTIVE','DRAINING','CLOSED','STALE','CLEANUP_UNCONFIRMED'])
 def test_default_operations_are_readonly(self):self.assertEqual(self.f['defaultAllowed'],['observe','inquire','close'])
 def test_write_operations_require_explicit_provider(self):self.assertEqual(self.f['writeOperations'],['pinAdvance','callerSave','callerMarkDispatch','connect'])
 def test_native_status_not_promoted(self):self.assertEqual(self.f['nativeBuild'],'BUILD_NOT_RUN');self.assertEqual(self.f['deviceVerification'],'DEVICE_UNVERIFIED');self.assertFalse(self.f['productQualified'])
 def test_epoch_transition_is_fail_closed(self):self.assertEqual(self.f['rules']['epochChange'],'STALE_CLOSE_RETURNED_RESOURCE')
 def test_cleanup_failure_is_not_closed(self):self.assertEqual(self.f['rules']['closeFailure'],'CLEANUP_UNCONFIRMED_RETAIN')
