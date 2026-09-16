import copy
import importlib
import json
import unittest
from pathlib import Path

from crypto_support import ROOT, PIN


REQUIRED_CAPABILITIES = [
    'sign_public', 'sign', 'verify', 'dh_public', 'dh',
    'seal', 'open', 'seal_ietf', 'open_ietf',
]


class FakeProvider:
    def __init__(self, **identity_updates):
        self.identity = {
            'provider': 'test-provider',
            'provider_family': 'test-family',
            'path': '/opt/par/test-provider.so',
            'sha256': 'a' * 64,
            'version': '9.9.9',
            'security_qualified': False,
            'legacy_experiment': False,
            'auto_fallback': False,
            'maintenance_status': 'MAINTAINED',
            'key_protection': 'SOFTWARE_VERIFIED',
            'dependency_closure': 'COMPLETE',
            'capabilities': list(REQUIRED_CAPABILITIES),
            'secret': 'must-not-leak',
        }
        self.identity.update(identity_updates)

    def sign_public(self, seed): return b'p' * 32
    def sign(self, seed, message): return b's' * 64
    def verify(self, public_key, message, signature): return None
    def dh_public(self, secret): return b'd' * 32
    def dh(self, secret, public_key): return b'x' * 32
    def seal(self, key, nonce, aad, plaintext): return plaintext + b't' * 16
    def open(self, key, nonce, aad, ciphertext): return ciphertext[:-16]
    def seal_ietf(self, key, nonce, aad, plaintext): return plaintext + b't' * 16
    def open_ietf(self, key, nonce, aad, ciphertext): return ciphertext[:-16]


class ProviderAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admission = importlib.import_module('par_crypto.admission')
        provider_module = importlib.import_module('par_crypto.provider')
        cls.legacy = provider_module.SodiumProvider(
            json.loads(PIN.read_text()), allow_legacy_experiment=True
        )

    def error(self, code, fn):
        errors = importlib.import_module('par_crypto.errors')
        with self.assertRaises(errors.CryptoError) as cm:
            fn()
        self.assertEqual(cm.exception.code, code)

    def test_legacy_provider_is_experiment_only(self):
        report = self.admission.provider_report(self.legacy)
        self.assertEqual(report['boundary_state'], 'EXPERIMENT_ONLY')
        self.assertFalse(report['security_qualified'])
        self.assertEqual(
            self.admission.admit_provider(self.legacy, purpose='experiment')['boundary_state'],
            'EXPERIMENT_ONLY',
        )
        self.error(
            'PROVIDER_LEGACY',
            lambda: self.admission.admit_provider(self.legacy, purpose='native-review'),
        )

    def test_native_review_accepts_structural_candidate_without_security_claim(self):
        report = self.admission.admit_provider(FakeProvider(), purpose='native-review')
        self.assertEqual(report['boundary_state'], 'REVIEW_CANDIDATE')
        self.assertFalse(report['security_qualified'])
        self.assertNotIn('secret', report)

    def test_native_review_rejects_auto_fallback(self):
        self.error(
            'PROVIDER_AUTOFALLBACK',
            lambda: self.admission.admit_provider(
                FakeProvider(auto_fallback=True), purpose='native-review'
            ),
        )

    def test_native_review_rejects_incomplete_dependency_closure(self):
        self.error(
            'PROVIDER_DEPENDENCY_CLOSURE',
            lambda: self.admission.admit_provider(
                FakeProvider(dependency_closure='TARGET_IMAGE_ONLY'), purpose='native-review'
            ),
        )

    def test_native_review_rejects_unverified_key_protection(self):
        self.error(
            'PROVIDER_KEY_PROTECTION',
            lambda: self.admission.admit_provider(
                FakeProvider(key_protection='UNVERIFIED'), purpose='native-review'
            ),
        )

    def test_native_review_rejects_unmaintained_provider(self):
        self.error(
            'PROVIDER_MAINTENANCE',
            lambda: self.admission.admit_provider(
                FakeProvider(maintenance_status='UNKNOWN'), purpose='native-review'
            ),
        )

    def test_native_review_rejects_self_declared_security_qualification(self):
        self.error(
            'PROVIDER_SECURITY_EVIDENCE_REQUIRED',
            lambda: self.admission.admit_provider(
                FakeProvider(security_qualified=True), purpose='native-review'
            ),
        )

    def test_missing_required_method_rejected(self):
        p = FakeProvider()
        p.verify = None
        self.error('PROVIDER_INTERFACE', lambda: self.admission.provider_report(p))

    def test_missing_identity_field_rejected(self):
        p = FakeProvider()
        del p.identity['sha256']
        self.error('PROVIDER_IDENTITY', lambda: self.admission.provider_report(p))

    def test_unknown_purpose_rejected(self):
        self.error(
            'INVALID_INPUT',
            lambda: self.admission.admit_provider(FakeProvider(), purpose='production'),
        )


class ProviderDecisionPacketTests(unittest.TestCase):
    def test_decision_packet_exists_and_remains_unresolved(self):
        path = ROOT / 'docs/decisions/G0_CRYPTO_PROVIDER_DECISION_0066.json'
        self.assertTrue(path.is_file(), 'provider decision packet must exist')
        data = json.loads(path.read_text())
        self.assertEqual(data['schema_version'], 1)
        self.assertEqual(data['goal'], 'G0-CRYPTO')
        self.assertEqual(data['status'], 'DECISION_REQUIRED')
        self.assertIsNone(data['selected_provider'])
        self.assertFalse(data['product_qualified'])
        for key in (
            'threat_model', 'trust_boundaries', 'key_lifecycle', 'randomness_and_nonce',
            'serialization_and_migration', 'supply_chain', 'platform_key_protection',
            'required_security_evidence', 'provider_admission', 'stop_conditions',
        ):
            self.assertIn(key, data)
            self.assertTrue(data[key])
        self.assertIn('PAR-CRYPTO-001', data['acceptance_ids'])
        self.assertIn('PAR-ID-002', data['acceptance_ids'])
        self.assertNotEqual(data['provider_admission']['legacy_provider_status'], 'SECURITY_QUALIFIED')


if __name__ == '__main__':
    unittest.main()
