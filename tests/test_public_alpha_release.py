import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PublicAlphaTestScopeTests(unittest.TestCase):
    def test_public_alpha_suite_excludes_legacy_development_modules(self):
        from tools import test_runner

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tests = root / 'tests'
            tests.mkdir()
            profile = root / 'oss' / 'PUBLIC_ALPHA_RELEASE.json'
            profile.parent.mkdir()
            profile.write_text('{}\n', encoding='utf-8')
            for name in (
                '__init__.py',
                'test_oss_prerelease.py',
                'test_public_alpha_release.py',
                'test_public_alpha_smoke.py',
                'test_legacy_internal_registration.py',
            ):
                (tests / name).write_text('', encoding='utf-8')

            modules = test_runner.test_modules(root)

        self.assertEqual(
            modules,
            [
                'tests.test_oss_prerelease',
                'tests.test_public_alpha_release',
                'tests.test_public_alpha_smoke',
            ],
        )


class PublicAlphaProfileTests(unittest.TestCase):
    def test_profile_has_exact_personal_source_alpha_identity(self):
        from harness.public_alpha import load_public_alpha_profile, validate_public_alpha_profile

        profile = load_public_alpha_profile(ROOT)
        self.assertEqual(validate_public_alpha_profile(ROOT, profile), [])
        self.assertEqual(profile['project']['name'], 'Peer Application Runtime')
        self.assertEqual(profile['project']['short_name'], 'PAR')
        self.assertEqual(profile['version'], '0.1.0-alpha.1')
        self.assertEqual(profile['intended_tag'], 'v0.1.0-alpha.1')
        self.assertEqual(profile['license']['spdx'], 'Apache-2.0')
        self.assertEqual(profile['copyright']['public_holder'], 'dyskinmel')
        self.assertEqual(profile['source_only']['native_dependency_sbom']['status'], 'NOT_APPLICABLE')
        self.assertEqual(profile['repository']['status'], 'PUBLIC')
        self.assertEqual(profile['security_reporting']['status'], 'ENABLED')
        self.assertTrue(profile['publication']['publishable'])
        self.assertTrue(profile['publication']['release_authorized'])
        self.assertTrue(all(row['status'] == 'COMPLETED' for row in profile['external_publish_prerequisites']))

    def test_profile_requires_clean_archive_import_without_development_history(self):
        from harness.public_alpha import load_public_alpha_profile, validate_public_alpha_profile

        profile = load_public_alpha_profile(ROOT)
        self.assertEqual(
            profile['repository']['import_source'],
            'VERIFIED_SOURCE_ARCHIVE_CONTENTS',
        )
        self.assertIs(profile['repository']['preserve_development_git_history'], False)
        self.assertIs(profile['repository']['development_checkout_push_allowed'], False)

        profile['repository']['development_checkout_push_allowed'] = True
        errors = validate_public_alpha_profile(ROOT, profile)
        self.assertIn(
            'repository.development_checkout_push_allowed',
            {row['field'] for row in errors},
        )

    def test_root_license_and_notice_are_exact_public_material(self):
        self.assertEqual(
            hashlib.sha256((ROOT / 'LICENSE').read_bytes()).hexdigest(),
            'cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30',
        )
        self.assertTrue((ROOT / 'NOTICE').read_text(encoding='utf-8').startswith('Copyright 2026 dyskinmel\n'))

    def test_profile_rejects_missing_empty_or_changed_copyright_notice(self):
        from harness.public_alpha import load_public_alpha_profile, validate_public_alpha_profile

        for value in (None, '', 'Copyright 2026 Other'):
            with self.subTest(value=value):
                profile = load_public_alpha_profile(ROOT)
                if value is None:
                    del profile['copyright']['notice']
                else:
                    profile['copyright']['notice'] = value
                errors = validate_public_alpha_profile(ROOT, profile)
                self.assertIn('copyright.notice', {row['field'] for row in errors})

    def test_policy_exports_legal_material_but_keeps_internal_evidence_out(self):
        from harness.public_alpha import load_public_alpha_profile
        from harness.public_preview import build_public_manifest

        policy = json.loads((ROOT / 'oss/PUBLIC_SOURCE_POLICY.json').read_text(encoding='utf-8'))
        profile = load_public_alpha_profile(ROOT)
        rows = {row['path']: row for row in build_public_manifest(ROOT, policy)['files']}
        self.assertEqual(rows['LICENSE']['classification'], 'PUBLIC')
        self.assertEqual(rows['NOTICE']['classification'], 'PUBLIC')
        self.assertNotIn('release/OSS_READINESS.md', rows)
        self.assertEqual(policy['unresolved_gates'], [])
        self.assertTrue(policy['publishable'])

    def test_decision_record_matches_profile_and_authorizes_source_alpha(self):
        from harness.public_alpha import load_public_alpha_profile

        profile = load_public_alpha_profile(ROOT)
        decisions = json.loads((ROOT / 'oss/RELEASE_DECISIONS.json').read_text(encoding='utf-8'))
        self.assertEqual(decisions['decisions']['license']['spdx'], profile['license']['spdx'])
        self.assertEqual(decisions['decisions']['release_version']['value'], profile['version'])
        self.assertEqual(decisions['decisions']['public_repository']['slug'], profile['repository']['slug'])
        self.assertEqual(decisions['decisions']['security_reporting']['provider'], profile['security_reporting']['provider'])
        self.assertTrue(decisions['publishable'])
        self.assertTrue(decisions['release_authorized'])
        self.assertEqual(decisions['decisions']['public_repository']['status'], 'COMPLETED')
        self.assertEqual(decisions['decisions']['security_reporting']['status'], 'COMPLETED')
        self.assertEqual(decisions['decisions']['hosted_ci']['status'], 'COMPLETED')

    def test_public_docs_state_source_only_identity_and_no_email_route(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        security = (ROOT / 'SECURITY.md').read_text(encoding='utf-8')
        limitations = (ROOT / 'docs/KNOWN_LIMITATIONS.md').read_text(encoding='utf-8')
        self.assertIn('may change', readme.lower())
        self.assertIn('Apache-2.0', readme)
        self.assertIn('source-only', readme.lower())
        self.assertIn('GitHub private vulnerability reporting', security)
        self.assertIn('Do not post a sensitive vulnerability directly in a public issue.', security)
        email_pattern = r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
        self.assertRegex('security' + '@example.invalid', email_pattern)
        self.assertNotRegex(security, email_pattern)
        self.assertIn('NOT_APPLICABLE', limitations)


class PublicAlphaInventoryTests(unittest.TestCase):
    def test_inventory_metadata_remains_profile_bound_without_git_checkout(self):
        import subprocess
        from unittest.mock import patch
        from tools import build_oss_inventory as inventory

        unavailable = subprocess.CompletedProcess(['git'], 128, stdout='', stderr='not a git repository')
        with patch.object(inventory.subprocess, 'run', return_value=unavailable):
            try:
                metadata = inventory.load_inventory_generation_metadata()
            except ValueError as error:
                self.fail(f'profile-bound source archive metadata must not require Git history: {error}')
        self.assertEqual(
            metadata['profile_sha256'],
            hashlib.sha256((ROOT / 'oss/PUBLIC_ALPHA_RELEASE.json').read_bytes()).hexdigest(),
        )

    def test_inventory_metadata_allows_manifest_bound_clean_import_without_historical_commit(self):
        import subprocess
        from unittest.mock import patch
        from tools import build_oss_inventory as inventory

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            oss = root / 'oss'
            oss.mkdir()
            profile = ROOT / 'oss/PUBLIC_ALPHA_RELEASE.json'
            metadata = ROOT / 'oss/INVENTORY_GENERATION_METADATA.json'
            (oss / profile.name).write_bytes(profile.read_bytes())
            imported_metadata = oss / metadata.name
            imported_metadata.write_bytes(metadata.read_bytes())
            (root / 'PUBLIC_SOURCE_MANIFEST.json').write_text(
                json.dumps({
                    'files': [{
                        'path': 'oss/INVENTORY_GENERATION_METADATA.json',
                        'sha256': hashlib.sha256(imported_metadata.read_bytes()).hexdigest(),
                    }],
                }),
                encoding='utf-8',
            )
            subprocess.run(['git', 'init', '-q', '-b', 'main', str(root)], check=True)
            subprocess.run(['git', '-C', str(root), 'config', 'user.name', 'test'], check=True)
            subprocess.run(['git', '-C', str(root), 'config', 'user.email', 'test.invalid'], check=True)
            subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(root), 'commit', '-q', '-m', 'clean import'], check=True)

            with patch.object(inventory, 'ROOT', root), patch.object(
                inventory, 'INVENTORY_GENERATION_METADATA', imported_metadata
            ):
                try:
                    loaded = inventory.load_inventory_generation_metadata()
                except ValueError as error:
                    self.fail(f'manifest-bound clean import must not require private Git history: {error}')

        self.assertEqual(loaded['profile_source']['commit'], json.loads(metadata.read_text())['profile_source']['commit'])

    def test_package_manifest_discovery_falls_back_to_source_archive_files(self):
        import subprocess
        from unittest.mock import patch
        from tools import build_oss_inventory as inventory

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'nested').mkdir()
            (root / 'package.json').write_text('{}\n', encoding='utf-8')
            (root / 'nested' / 'package.json').write_text('{}\n', encoding='utf-8')
            with patch.object(inventory, 'ROOT', root):
                try:
                    manifests = inventory.git_tracked('*package.json')
                except (OSError, subprocess.CalledProcessError) as error:
                    self.fail(f'source archive manifest discovery must not require Git metadata: {error}')
        self.assertEqual(manifests, ['nested/package.json', 'package.json'])

    def test_inventory_snapshot_rejects_forged_commit_or_timestamp(self):
        import subprocess
        from unittest.mock import patch
        from tools import build_oss_inventory as inventory

        checkout = subprocess.run(
            ['git', '-C', str(ROOT), 'rev-parse', '--is-inside-work-tree'],
            capture_output=True,
            text=True,
        )
        if checkout.returncode != 0:
            metadata = inventory.load_inventory_generation_metadata()
            self.assertEqual(
                metadata['profile_sha256'],
                hashlib.sha256((ROOT / 'oss/PUBLIC_ALPHA_RELEASE.json').read_bytes()).hexdigest(),
            )
            return
        for field, value in (('commit', '0' * 40), ('commit_timestamp', '2000-01-01T00:00:00Z')):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                metadata = json.loads((ROOT / 'oss/INVENTORY_GENERATION_METADATA.json').read_text())
                metadata['profile_source'][field] = value
                metadata['inventory_snapshot_created'] = metadata['profile_source']['commit_timestamp']
                path = Path(td) / 'metadata.json'
                path.write_text(json.dumps(metadata), encoding='utf-8')
                with patch.object(inventory, 'INVENTORY_GENERATION_METADATA', path):
                    with self.assertRaisesRegex(ValueError, 'INVENTORY_GENERATION_METADATA_INVALID'):
                        inventory.load_inventory_generation_metadata()

    def test_regenerated_inventory_matches_selected_source_only_profile(self):
        import subprocess

        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            cp = subprocess.run(
                [sys.executable, str(ROOT / 'tools/build_oss_inventory.py'), '--output-dir', str(out)],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(cp.returncode, 0, cp.stderr + cp.stdout)
            gate = json.loads((out / 'LICENSE_DECISION_REQUIRED.json').read_text(encoding='utf-8'))
            sbom = json.loads((out / 'SBOM.spdx.json').read_text(encoding='utf-8'))
            third = json.loads((out / 'THIRD_PARTY_INVENTORY.json').read_text(encoding='utf-8'))
            self.assertEqual(gate['status'], 'RESOLVED_SOURCE_ONLY_ALPHA')
            self.assertEqual(gate['selected_spdx_license'], 'Apache-2.0')
            self.assertEqual(sbom['packages'][0]['versionInfo'], '0.1.0-alpha.1')
            self.assertEqual(sbom['parMetadata']['nativeDependencySbomStatus'], 'NOT_APPLICABLE')
            self.assertEqual(third['release_license_decision'], 'Apache-2.0')
            self.assertEqual(
                third['third_party_compatibility'],
                'REVIEWED_NO_BUNDLED_THIRD_PARTY_ARTIFACTS',
            )
            self.assertEqual(third['source_only_alpha_dependency_review']['status'], 'COMPLETED')

    def test_sbom_creation_timestamp_is_a_profile_bound_inventory_snapshot(self):
        import subprocess

        metadata_path = ROOT / 'oss/INVENTORY_GENERATION_METADATA.json'
        self.assertTrue(metadata_path.is_file())
        metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        profile_digest = hashlib.sha256(
            (ROOT / 'oss/PUBLIC_ALPHA_RELEASE.json').read_bytes()
        ).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            cp = subprocess.run(
                [sys.executable, str(ROOT / 'tools/build_oss_inventory.py'), '--output-dir', str(out)],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(cp.returncode, 0, cp.stderr + cp.stdout)
            sbom = json.loads((out / 'SBOM.spdx.json').read_text(encoding='utf-8'))
        self.assertEqual(metadata['profile_sha256'], profile_digest)
        self.assertEqual(sbom['creationInfo']['created'], metadata['inventory_snapshot_created'])
        self.assertEqual(
            sbom['parMetadata']['creationInfoSemantics'],
            'DETERMINISTIC_INVENTORY_SNAPSHOT_NOT_DEVELOPMENT_BASELINE_TIME',
        )


class PublicAlphaArchiveTests(unittest.TestCase):
    def test_public_alpha_archive_has_legal_profile_and_no_internal_or_binary_content(self):
        from harness.public_preview import build_preview_archive
        from tools.verify_oss_prerelease_candidate import verify_candidate

        policy = json.loads((ROOT / 'oss/PUBLIC_SOURCE_POLICY.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / 'peer-application-runtime-0.1.0-alpha.1-source.zip'
            build_preview_archive(ROOT, policy, archive)
            report = verify_candidate(archive)
            self.assertEqual(report['overall_result'], 'PASS')
            self.assertTrue(report['required_legal_material_present'])
            self.assertEqual(report['source_only_result'], 'PASS')
            self.assertEqual(report['smoke_result'], 'PASS')
            self.assertTrue(report['publishable'])
            self.assertTrue(report['release_authorized'])
            self.assertFalse(report['product_qualified'])

    def test_verifier_fails_when_notice_is_missing_from_archive(self):
        from harness.public_preview import build_preview_archive
        from tools.verify_oss_prerelease_candidate import verify_candidate

        policy = json.loads((ROOT / 'oss/PUBLIC_SOURCE_POLICY.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original = root / 'original.zip'
            tampered = root / 'missing-notice.zip'
            build_preview_archive(ROOT, policy, original)
            with zipfile.ZipFile(original) as source, zipfile.ZipFile(tampered, 'w', compression=zipfile.ZIP_DEFLATED) as destination:
                for info in source.infolist():
                    if info.filename != 'NOTICE':
                        destination.writestr(info, source.read(info.filename))
            report = verify_candidate(tampered)
            self.assertEqual(report['overall_result'], 'FAIL')
            self.assertFalse(report['required_legal_material_present'])


class PublicAlphaArchiveContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from harness.public_preview import build_preview_archive

        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.original = Path(cls.directory.name) / 'original.zip'
        policy = json.loads((ROOT / 'oss/PUBLIC_SOURCE_POLICY.json').read_text(encoding='utf-8'))
        build_preview_archive(ROOT, policy, cls.original)

    def verify_mutation(self, mutate, raw_mutate=None):
        from unittest.mock import patch
        from harness.public_preview import write_outer_sha256
        from tests.test_oss_prerelease import rewrite_rechecksummed_archive
        from tools.verify_oss_prerelease_candidate import verify_candidate

        archive = Path(self.directory.name) / 'mutated.zip'
        rewrite_rechecksummed_archive(self.original, archive, mutate, raw_mutate)
        checksum = write_outer_sha256(archive)
        with patch('tools.verify_oss_prerelease_candidate.run_smoke', return_value={
            'overall_result': 'PASS', 'checks': [],
        }) as smoke:
            report = verify_candidate(archive, checksum)
        self.assertEqual(report['outer_checksum_result'], 'PASS')
        self.assertEqual(report['technical_result'], 'FAIL', report)
        self.assertEqual(report['smoke_result'], 'BLOCKED')
        smoke.assert_not_called()
        self.assertIs(report['publishable'], False)
        self.assertIs(report['release_authorized'], False)
        self.assertIs(report['product_qualified'], False)
        return report

    def test_contradictory_inventory_claims_fail_with_valid_checksums(self):
        cases = (
            ('LICENSE_DECISION_REQUIRED.json', 'publishable', False),
            ('LICENSE_DECISION_REQUIRED.json', 'status', 'DECISION_REQUIRED'),
            ('LICENSE_DECISION_REQUIRED.json', 'selected_spdx_license', 'MIT'),
            ('LICENSE_DECISION_REQUIRED.json', 'notice_finalized', False),
            ('THIRD_PARTY_INVENTORY.json', 'release_license_decision', 'MIT'),
            ('THIRD_PARTY_INVENTORY.json', 'license_authorized_for_publication', False),
            ('THIRD_PARTY_INVENTORY.json', 'repository_license_material', []),
            ('THIRD_PARTY_INVENTORY.json', 'repository_license_material.1.sha256', '0' * 64),
            ('THIRD_PARTY_INVENTORY.json', 'repository_license_material_complete', False),
            ('THIRD_PARTY_INVENTORY.json', 'third_party_compatibility', 'COMPATIBLE'),
            ('THIRD_PARTY_INVENTORY.json', 'legal_conclusion', 'APPROVED'),
            ('THIRD_PARTY_INVENTORY.json', 'dependency_license_status.0.status', 'APPROVED'),
            ('SBOM.spdx.json', 'parMetadata.final', True),
            ('SBOM.spdx.json', 'parMetadata.sourceOnlyRelease', False),
            ('SBOM.spdx.json', 'parMetadata.nativeArtifactBundled', True),
            ('SBOM.spdx.json', 'parMetadata.nativeDependencySbomStatus', 'COMPLETE'),
            ('SBOM.spdx.json', 'packages.0.versionInfo', '1.0.0'),
            ('SBOM.spdx.json', 'packages.0.licenseDeclared', 'MIT'),
            ('DEPENDENCY_INVENTORY.json', 'network_resolution_performed', True),
        )
        for filename, field, value in cases:
            with self.subTest(filename=filename, field=field):
                def mutate(metadata):
                    target = metadata['oss/' + filename]
                    parts = field.split('.')
                    for part in parts[:-1]:
                        target = target[int(part)] if isinstance(target, list) else target[part]
                    target[parts[-1]] = value
                report = self.verify_mutation(mutate)
                self.assertEqual(report['checksum_result'], 'PASS')
                self.assertEqual(report['dependency_inventory'], 'FAIL')
                self.assertTrue(report['inventory_errors'])

    def test_decision_statuses_reject_incorrect_external_state_or_native_sbom(self):
        cases = (
            ('license', 'status', 'PASS'),
            ('project_name', 'status', 'PASS'),
            ('project_name', 'value', 'Other Project'),
            ('release_version', 'status', 'PASS'),
            ('release_version', 'intended_tag', 'v1.0.0'),
            ('copyright_notice', 'status', 'PASS'),
            ('copyright_notice', 'value', ''),
            ('final_native_dependency_sbom', 'status', 'COMPLETE'),
            ('final_native_dependency_sbom', 'scope', 'NATIVE'),
            ('public_repository', 'status', 'EXTERNAL_ACTION_REQUIRED'),
            ('security_reporting', 'status', 'EXTERNAL_ACTION_REQUIRED'),
            ('hosted_ci', 'status', 'EXTERNAL_ACTION_REQUIRED'),
            ('release_signing', 'status', 'PASS'),
            ('hosted_attestation', 'status', 'PASS'),
        )
        for decision, field, value in cases:
            with self.subTest(decision=decision, field=field):
                report = self.verify_mutation(lambda metadata: metadata[
                    'oss/RELEASE_DECISIONS.json']['decisions'][decision].update({field: value}))
                self.assertEqual(report['checksum_result'], 'PASS')
                self.assertTrue(report['relationship_errors'])

    def test_missing_profile_copyright_and_empty_notice_fail(self):
        def mutate(metadata):
            del metadata['oss/PUBLIC_ALPHA_RELEASE.json']['copyright']['notice']
        report = self.verify_mutation(mutate, lambda entries: entries.update({'NOTICE': b''}))
        self.assertEqual(report['checksum_result'], 'PASS')
        self.assertIn('copyright.notice', {row['field'] for row in report['profile_errors']})
        self.assertIn('NOTICE_MISMATCH', report['legal_material_errors'])

    def test_nonobject_json_records_fail_closed(self):
        for name in (
            'PUBLIC_SOURCE_MANIFEST.json', 'PUBLIC_PREVIEW_STATUS.json',
            'oss/PUBLIC_SOURCE_POLICY.json', 'oss/PUBLIC_ALPHA_RELEASE.json',
            'oss/RELEASE_DECISIONS.json', 'oss/LICENSE_DECISION_REQUIRED.json',
            'oss/THIRD_PARTY_INVENTORY.json', 'oss/SBOM.spdx.json',
            'oss/DEPENDENCY_INVENTORY.json',
        ):
            with self.subTest(name=name):
                self.verify_mutation(lambda metadata: metadata.update({name: []}))
