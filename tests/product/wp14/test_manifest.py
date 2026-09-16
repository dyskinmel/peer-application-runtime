import json, unittest
from pathlib import Path

class ManifestTests(unittest.TestCase):
    def setUp(self):
        from product.wp14.par_native_provider import model
        self.m=model

    def test_experimental_posix_is_never_os_protected(self):
        d=self.m.experimental_posix_descriptor(epoch='11'*16)
        self.assertEqual(d.profile,'par-native-provider-handoff-0056')
        self.assertEqual(d.protection,'LOCAL_UNPROTECTED')
        self.assertFalse(d.os_protection_proven)
        self.assertFalse(d.rollback_protection_proven)

    def test_descriptor_versions_are_independent(self):
        d=self.m.experimental_posix_descriptor(epoch='11'*16)
        self.assertEqual(set(d.versions),{'handoff','wire','suite','store','sdk','ui'})
        self.assertNotEqual(d.versions['handoff'],d.versions['wire'])

    def test_unknown_manifest_field_rejected(self):
        raw=self.m.experimental_posix_descriptor(epoch='11'*16).to_dict();raw['trusted']=True
        with self.assertRaisesRegex(ValueError,'MANIFEST_FIELDS'):self.m.ProviderDescriptor.from_dict(raw)

    def test_string_boolean_rejected(self):
        raw=self.m.experimental_posix_descriptor(epoch='11'*16).to_dict();raw['osProtectionProven']='false'
        with self.assertRaisesRegex(ValueError,'MANIFEST_BOOL'):self.m.ProviderDescriptor.from_dict(raw)

    def test_bad_epoch_rejected(self):
        with self.assertRaisesRegex(ValueError,'PROVIDER_EPOCH'):self.m.experimental_posix_descriptor(epoch='abcd')

    def test_available_capability_requires_factory_flag(self):
        raw=self.m.experimental_posix_descriptor(epoch='11'*16).to_dict();raw['capabilities']['connectionFactory']['status']='AVAILABLE'
        raw['capabilities']['connectionFactory']['factorySupplied']=False
        with self.assertRaisesRegex(ValueError,'CAPABILITY_FACTORY'):self.m.ProviderDescriptor.from_dict(raw)

    def test_unverified_native_source_cannot_claim_protection(self):
        raw=self.m.apple_source_descriptor(epoch='22'*16).to_dict();raw['osProtectionProven']=True
        with self.assertRaisesRegex(ValueError,'PROTECTION_UNVERIFIED'):self.m.ProviderDescriptor.from_dict(raw)

    def test_profile_json_roundtrips_exactly(self):
        root=Path(__file__).resolve().parents[3]
        raw=json.loads((root/'product/wp14/native-provider-profile.json').read_text())
        d=self.m.ProviderDescriptor.from_dict(raw['experimentalLocal'])
        self.assertEqual(d.to_dict(),raw['experimentalLocal'])
        apple=self.m.ProviderDescriptor.from_dict(raw['appleSourceCandidate'])
        self.assertEqual(apple.to_dict(),raw['appleSourceCandidate'])

    def test_profile_default_is_blocked(self):
        root=Path(__file__).resolve().parents[3]
        raw=json.loads((root/'product/wp14/native-provider-profile.json').read_text())
        self.assertEqual(raw['defaultProvider'],'BLOCKED')
        self.assertFalse(raw['autoFallback'])
        self.assertFalse(raw['productQualified'])

    def test_capability_names_are_exact(self):
        d=self.m.experimental_posix_descriptor(epoch='11'*16)
        self.assertEqual(set(d.capabilities),{'pinStore','callerIntentStore','connectionFactory'})

if __name__=='__main__':unittest.main()
