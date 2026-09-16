import json,re,unittest
from pathlib import Path
R=Path(__file__).resolve().parents[3]

class NativeSourceTests(unittest.TestCase):
 def test_swift_caller_source_exists_and_uses_device_only_keychain(self):
  p=R/'product/wp14/native/apple/PARCallerIntentKeychain.swift';self.assertTrue(p.is_file());s=p.read_text()
  for token in ('import Security','SecItemAdd','SecItemCopyMatching','kSecAttrAccessibleWhenUnlockedThisDeviceOnly'):self.assertIn(token,s)
  self.assertNotIn('SecItemDelete',s);self.assertNotRegex(s,r'kSecAttrSynchronizable\s*:\s*true')
 def test_swift_source_is_create_only_not_silent_overwrite(self):
  s=(R/'product/wp14/native/apple/PARCallerIntentKeychain.swift').read_text();self.assertIn('errSecDuplicateItem',s);self.assertIn('existing == bytes',s)
 def test_swift_bridge_has_epoch_and_cleanup_contract(self):
  s=(R/'product/wp14/native/apple/PARProviderBridge.swift').read_text();self.assertIn('ProviderEpoch',s);self.assertIn('cleanupConfirmed',s);self.assertIn('cancel()',s)
 def test_rust_handoff_source_has_no_unsafe_or_network_fallback(self):
  s=(R/'product/wp14/native/rust/provider_handoff.rs').read_text();self.assertNotIn('unsafe',s);self.assertNotIn('TcpStream',s);self.assertIn('trait NativeProvider',s);self.assertIn('ProviderEpoch',s)
 def test_profile_marks_native_build_not_run(self):
  p=json.loads((R/'product/wp14/native-provider-profile.json').read_text());self.assertEqual(p['appleSourceCandidate']['nativeBuild'],'BUILD_NOT_RUN');self.assertFalse(p['appleSourceCandidate']['osProtectionProven']);self.assertFalse(p['nativeBuildExecuted'])
 def test_no_native_binary_shipped_as_verified(self):
  base=R/'product/wp14/native';bad=[p for p in base.rglob('*') if p.is_file() and p.suffix in('.dylib','.so','.a','.framework')]
  self.assertEqual(bad,[])
 def test_contract_doc_states_source_only_native_status(self):
  s=(R/'product/wp14/NATIVE_PROVIDER_HANDOFF.ja.md').read_text();self.assertIn('BUILD_NOT_RUN',s);self.assertIn('DEVICE_UNVERIFIED',s);self.assertIn('OS保護',s)

if __name__=='__main__':unittest.main()
