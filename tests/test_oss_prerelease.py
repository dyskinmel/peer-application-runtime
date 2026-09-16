import json
import hashlib
import re
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rewrite_rechecksummed_archive(source: Path, destination: Path, mutate, raw_mutate=None) -> None:
    """Apply metadata-only tampering while retaining manifest and ZIP checksums."""
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        entries = {info.filename: archive.read(info.filename) for info in infos}
    metadata_names = (
        'oss/PUBLIC_SOURCE_POLICY.json', 'oss/PUBLIC_ALPHA_RELEASE.json',
        'oss/RELEASE_DECISIONS.json', 'oss/LICENSE_DECISION_REQUIRED.json',
        'oss/THIRD_PARTY_INVENTORY.json', 'oss/SBOM.spdx.json',
        'oss/DEPENDENCY_INVENTORY.json',
        'PUBLIC_SOURCE_MANIFEST.json', 'PUBLIC_PREVIEW_STATUS.json',
    )
    metadata = {name: json.loads(entries[name]) for name in metadata_names}
    mutate(metadata)
    for name in metadata_names:
        entries[name] = (json.dumps(metadata[name], indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode()
    if raw_mutate is not None:
        raw_mutate(entries)
    manifest = metadata['PUBLIC_SOURCE_MANIFEST.json']
    for row in manifest['files'] if isinstance(manifest, dict) else []:
        path = row['path']
        if path in entries:
            row['size_bytes'] = len(entries[path])
            row['sha256'] = hashlib.sha256(entries[path]).hexdigest()
    if isinstance(manifest, dict):
        manifest_body = dict(manifest)
        manifest_body.pop('manifest_sha256', None)
        manifest['manifest_sha256'] = hashlib.sha256(
            json.dumps(manifest_body, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        ).hexdigest()
        if isinstance(metadata['PUBLIC_PREVIEW_STATUS.json'], dict):
            metadata['PUBLIC_PREVIEW_STATUS.json']['manifest_sha256'] = manifest['manifest_sha256']
    for name in ('PUBLIC_SOURCE_MANIFEST.json', 'PUBLIC_PREVIEW_STATUS.json'):
        entries[name] = (json.dumps(metadata[name], indent=2, sort_keys=True, ensure_ascii=False) + '\n').encode()
    entries['SHA256SUMS'] = ''.join(
        f"{hashlib.sha256(entries[name]).hexdigest()}  {name}\n"
        for name in sorted(name for name in entries if name != 'SHA256SUMS')
    ).encode()
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for info in infos:
            archive.writestr(info.filename, entries[info.filename])


class OssPrereleasePolicyTests(unittest.TestCase):
    def load_policy(self):
        return json.loads((ROOT / 'oss/PUBLIC_SOURCE_POLICY.json').read_text(encoding='utf-8'))

    def test_policy_defines_four_required_classifications(self):
        policy = self.load_policy()
        self.assertEqual(
            set(policy['classifications']),
            {'PUBLIC', 'PUBLIC_DEVELOPMENT', 'INTERNAL_ONLY', 'GENERATED_EXCLUDE'},
        )

    def test_classification_is_fail_closed_for_unknown_path(self):
        from harness.public_preview import classify_public_path
        policy = self.load_policy()
        self.assertEqual(classify_public_path(Path('product/wp10/package.json'), policy), 'PUBLIC')
        self.assertEqual(classify_public_path(Path('tests/test_public_alpha_release.py'), policy), 'PUBLIC_DEVELOPMENT')
        self.assertEqual(classify_public_path(Path('tests/test_public_alpha_smoke.py'), policy), 'PUBLIC_DEVELOPMENT')
        self.assertEqual(classify_public_path(Path('tests/product/wire/test_vectors.py'), policy), 'PUBLIC_DEVELOPMENT')
        self.assertEqual(classify_public_path(Path('tests/test_local_closure_sprint_a.py'), policy), 'INTERNAL_ONLY')
        self.assertEqual(classify_public_path(Path('evidence/private.json'), policy), 'INTERNAL_ONLY')
        self.assertEqual(classify_public_path(Path('target/cache.bin'), policy), 'GENERATED_EXCLUDE')
        self.assertIsNone(classify_public_path(Path('mystery/new.txt'), policy))

    def test_every_tracked_path_is_classified_and_public_export_excludes_internal(self):
        from harness.public_preview import audit_tracked_classification, build_public_manifest
        policy = self.load_policy()
        audit = audit_tracked_classification(ROOT, policy)
        self.assertEqual(audit['unclassified'], [])
        self.assertGreater(audit['tracked_files'], 0)
        manifest = build_public_manifest(ROOT, policy)
        classes = {row['classification'] for row in manifest['files']}
        self.assertTrue(classes <= {'PUBLIC', 'PUBLIC_DEVELOPMENT'})
        paths = {row['path'] for row in manifest['files']}
        self.assertIn('LICENSE', paths)
        self.assertIn('NOTICE', paths)
        self.assertNotIn('AGENTS.md', paths)
        self.assertNotIn('release/OSS_READINESS.md', paths)


class OssPrereleaseScannerTests(unittest.TestCase):
    def policy(self):
        return {
            'schema_version': 2,
            'publishable': False,
            'unresolved_gates': ['license'],
            'classification_precedence': ['GENERATED_EXCLUDE','INTERNAL_ONLY','PUBLIC_DEVELOPMENT','PUBLIC'],
            'classifications': {
                'PUBLIC': {'roots':['docs'], 'exact':[]},
                'PUBLIC_DEVELOPMENT': {'roots':['tests'], 'exact':[]},
                'INTERNAL_ONLY': {'roots':['internal','oss'], 'exact':[]},
                'GENERATED_EXCLUDE': {'roots':['target'], 'components':['__pycache__'], 'suffixes':['.pyc']},
            },
            'scan': {
                'max_text_bytes': 2097152,
                'max_public_file_bytes': 64,
                'secret_patterns': ['BEGIN PRIVATE KEY'],
                'local_path_prefixes': ['/mnt/data/','/Users/'],
                'allowed_binary_suffixes': [],
                'allowlist_file': 'oss/SCAN_ALLOWLIST.json',
            },
        }

    def test_scanner_detects_sensitive_privacy_path_remote_binary_and_large_material(self):
        from harness.public_preview import scan_public_surface
        with tempfile.TemporaryDirectory() as td:
            r=Path(td); (r/'docs').mkdir(); (r/'tests').mkdir(); (r/'oss').mkdir()
            (r/'oss'/'SCAN_ALLOWLIST.json').write_text('{"schema_version":1,"entries":[]}', encoding='utf-8')
            (r/'docs'/'token.txt').write_text('api_key = "ABCDEFGHIJKLMNOPQRSTUVWX"\nsk-proj-'+'A'*30, encoding='utf-8')
            (r/'docs'/'key.txt').write_text('-----BEGIN PRIVATE KEY-----\nabc', encoding='utf-8')
            (r/'docs'/'path.txt').write_text('/mnt/data/private/x\nC:\\Users\\alice\\secret.txt', encoding='utf-8')
            (r/'docs'/'email.txt').write_text('owner@example.com', encoding='utf-8')
            (r/'docs'/'remote.txt').write_text('git@github.com:private/repo.git\nhttps://svc.corp/api', encoding='utf-8')
            (r/'docs'/'blob.bin').write_bytes(b'\x00\xff\x01\xfe')
            (r/'docs'/'large.txt').write_text('x'*100, encoding='utf-8')
            scan=scan_public_surface(r,self.policy())
            kinds={f['kind'] for f in scan['findings']}
            self.assertTrue({
                'SECRET_TOKEN','SECRET_ASSIGNMENT','PRIVATE_KEY_MATERIAL','LOCAL_ABSOLUTE_PATH',
                'WINDOWS_USER_PATH','EMAIL_ADDRESS','PRIVATE_GIT_REMOTE','INTERNAL_HOSTNAME',
                'UNEXPECTED_BINARY','OVERSIZED_PUBLIC_FILE'
            } <= kinds)
            self.assertFalse(scan['pass'])

    def test_reasoned_allowlist_suppresses_only_declared_path_and_kind(self):
        from harness.public_preview import scan_public_surface
        with tempfile.TemporaryDirectory() as td:
            r=Path(td); (r/'tests').mkdir(); (r/'oss').mkdir()
            (r/'tests'/'fixture.py').write_text('harness@example.invalid',encoding='utf-8')
            (r/'oss'/'SCAN_ALLOWLIST.json').write_text(json.dumps({
                'schema_version':1,
                'entries':[{'path':'tests/fixture.py','kind':'EMAIL_ADDRESS','reason':'reserved .invalid negative-test identity'}]
            }),encoding='utf-8')
            policy=self.policy()
            scan=scan_public_surface(r,policy)
            self.assertTrue(scan['pass'])
            self.assertEqual(scan['findings'],[])
            self.assertEqual(len(scan['allowlisted_findings']),1)


class OssPrereleaseDocumentationTests(unittest.TestCase):
    REQUIRED = ['README.md','CONTRIBUTING.md','SECURITY.md','RELEASE_NOTES.md','CHANGELOG.md']

    def test_public_docs_are_complete_and_newcomer_oriented(self):
        base=ROOT
        for name in self.REQUIRED:
            self.assertTrue((base/name).is_file(), name)
        readme=(base/'README.md').read_text(encoding='utf-8')
        self.assertIn('Alpha',readme)
        self.assertIn('Production Qualification',readme)
        self.assertIn('python3 tools/check_wire.py --suite python',readme)
        self.assertIn('tools/verify_oss_prerelease_candidate.py',readme)
        self.assertIn('not the public-alpha acceptance criterion',readme)

    def test_known_limitations_state_required_nonclaims(self):
        text=(ROOT/'docs/KNOWN_LIMITATIONS.md').read_text(encoding='utf-8').lower()
        required=[
            'production qualified', 'g0-actor', 'g0-wire', 'g0-store', 'g0-crypto',
            'native key protection', 'independent security review', 'real internet',
            'soak', 'physical recovery', 'release signing', 'hosted attestation'
        ]
        for item in required:
            self.assertIn(item,text)

    def test_root_readme_links_match_archive_alias_layout(self):
        readme=(ROOT/'README.md').read_text(encoding='utf-8')
        for link in ['docs/ARCHITECTURE.md','docs/KNOWN_LIMITATIONS.md','docs/ROADMAP.md','SECURITY.md','CONTRIBUTING.md']:
            self.assertIn(link,readme)

    def test_security_and_release_decisions_record_selected_and_external_states(self):
        sec=(ROOT/'SECURITY.md').read_text(encoding='utf-8')
        self.assertIn('GitHub private vulnerability reporting',sec)
        self.assertIn('public issue',sec.lower())
        decisions=json.loads((ROOT/'oss/RELEASE_DECISIONS.json').read_text(encoding='utf-8'))
        for key in ['license','project_name','release_version','copyright_notice']:
            self.assertEqual(decisions['decisions'][key]['status'],'RESOLVED_LOCAL')
        self.assertEqual(decisions['decisions']['security_reporting']['status'],'EXTERNAL_ACTION_REQUIRED')
        self.assertEqual(decisions['decisions']['final_native_dependency_sbom']['status'],'NOT_APPLICABLE')
        self.assertFalse(decisions['publishable'])
        self.assertFalse(decisions['release_authorized'])


class OssPrereleaseInventoryTests(unittest.TestCase):
    def test_inventory_covers_all_tracked_package_manifests_without_guessing(self):
        dep=json.loads((ROOT/'oss/DEPENDENCY_INVENTORY.json').read_text(encoding='utf-8'))
        manifests=sorted(str(p.relative_to(ROOT)) for p in ROOT.rglob('package.json') if '.git' not in p.parts)
        self.assertEqual(sorted(x['path'] for x in dep['package_manifests']),manifests)
        required={'name','version','source','relationship','scope','detected_license','license_status','license_evidence','pin_status','maintenance_status','native_or_future','inclusion_status'}
        for row in dep['dependencies']:
            self.assertTrue(required <= set(row))
            self.assertNotEqual(row['detected_license'],'ASSUMED')
            self.assertIn(row['maintenance_status'],{'UNKNOWN','RESEARCH_REQUIRED','NOT_APPLICABLE_LOCAL_METADATA'})
        by_name={x['name']:x for x in dep['dependencies']}
        sodium=by_name['libsodium-ctypes-local-candidate']
        self.assertEqual(sodium['version'],'1.0.18')
        self.assertEqual(sodium['detected_license'],'ISC')
        self.assertEqual(sodium['license_status'],'REVIEWED_OFFICIAL_SOURCE')
        self.assertEqual(sodium['inclusion_status'],'SOURCE_REFERENCE_ONLY_BINARY_NOT_BUNDLED')
        self.assertEqual(by_name['sqlite']['detected_license'],'LicenseRef-SQLite-Public-Domain')
        self.assertEqual(by_name['typescript-compiler']['detected_license'],'Apache-2.0')
        self.assertEqual(by_name['automerge-native-dependency']['detected_license'],'MIT')
        self.assertEqual(by_name['production-crypto-provider']['detected_license'],'UNKNOWN')
        self.assertEqual(by_name['production-crypto-provider']['license_status'],'FUTURE_SELECTION_REQUIRED')
        for name in ('libsodium-ctypes-local-candidate','sqlite','typescript-compiler','automerge-native-dependency'):
            evidence=by_name[name]['license_evidence']
            self.assertEqual(evidence['source_kind'],'OFFICIAL_UPSTREAM')
            self.assertTrue(evidence['url'].startswith('https://'))
            self.assertEqual(evidence['reviewed_on'],'2026-09-16')
        self.assertTrue(all(x['license_declared']=='Apache-2.0' for x in dep['package_manifests']))

    def test_license_inventory_preserves_release_decision_gate(self):
        lic=json.loads((ROOT/'oss/THIRD_PARTY_INVENTORY.json').read_text(encoding='utf-8'))
        self.assertEqual(lic['release_license_decision'],'Apache-2.0')
        self.assertFalse(lic['license_authorized_for_publication'])
        self.assertEqual(lic['third_party_compatibility'],'REVIEWED_NO_BUNDLED_THIRD_PARTY_ARTIFACTS')
        self.assertEqual(lic['source_only_alpha_dependency_review']['status'],'COMPLETED')
        self.assertEqual(
            lic['source_only_alpha_dependency_review']['conclusion'],
            'NO_KNOWN_LICENSE_CONFLICT_FOR_SOURCE_ONLY_ALPHA_SCOPE',
        )
        self.assertEqual(lic['potential_license_conflicts'],[])
        self.assertEqual(lic['legal_conclusion'],'FACTUAL_LICENSE_REVIEW_COMPLETED_NOT_LEGAL_ADVICE')
        self.assertTrue(any(x['path']=='LICENSE' and x['included_in_public_candidate'] for x in lic['repository_license_material']))
        gate=json.loads((ROOT/'oss/LICENSE_DECISION_REQUIRED.json').read_text(encoding='utf-8'))
        self.assertEqual(gate['status'],'RESOLVED_SOURCE_ONLY_ALPHA')
        self.assertEqual(gate['selected_spdx_license'],'Apache-2.0')

    def test_source_sbom_candidate_is_deterministic_and_not_final(self):
        sbom=json.loads((ROOT/'oss/SBOM.spdx.json').read_text(encoding='utf-8'))
        self.assertEqual(sbom['spdxVersion'],'SPDX-2.3')
        self.assertIn('SOURCE-SBOM-CANDIDATE',sbom['name'])
        self.assertFalse(sbom['parMetadata']['final'])
        self.assertEqual(sbom['parMetadata']['nativeDependencySbomStatus'],'NOT_APPLICABLE')


class OssPrereleaseExporterTests(unittest.TestCase):
    def test_manifest_has_source_identity_aliases_classification_and_exclusion_summary(self):
        import subprocess
        from harness.public_preview import build_public_manifest
        policy=json.loads((ROOT/'oss/PUBLIC_SOURCE_POLICY.json').read_text(encoding='utf-8'))
        m=build_public_manifest(ROOT,policy)
        head=subprocess.run(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True,capture_output=True)
        tree=subprocess.run(['git','-C',str(ROOT),'rev-parse','HEAD^{tree}'],text=True,capture_output=True)
        if head.returncode == 0 and tree.returncode == 0:
            self.assertEqual(m['source']['head'],head.stdout.strip())
            self.assertEqual(m['source']['tree'],tree.stdout.strip())
            self.assertTrue(m['source']['source_digest'])
        else:
            self.assertIsNone(m['source']['head'])
            self.assertIsNone(m['source']['tree'])
            self.assertIsNone(m['source']['source_digest'])
        rows={x['path']:x for x in m['files']}
        self.assertEqual(rows['README.md']['source_path'],'README.md')
        self.assertEqual(rows['README.md']['classification'],'PUBLIC')
        self.assertNotIn('oss/public/README.md',rows)
        self.assertEqual(m['classification_audit']['unclassified'],[])
        self.assertEqual(
            set(m['excluded_categories']),
            {'PUBLIC','PUBLIC_DEVELOPMENT','INTERNAL_ONLY','GENERATED_EXCLUDE'},
        )
        for count in m['excluded_categories'].values():
            self.assertIsInstance(count,int)
            self.assertGreaterEqual(count,0)

    def test_double_export_is_byte_identical_and_outer_sha_verifies(self):
        import hashlib
        from harness.public_preview import build_preview_archive, write_outer_sha256
        policy=json.loads((ROOT/'oss/PUBLIC_SOURCE_POLICY.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as td:
            td=Path(td); a=td/'a.zip'; b=td/'b.zip'
            ra=build_preview_archive(ROOT,policy,a); rb=build_preview_archive(ROOT,policy,b)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            self.assertEqual(ra['sha256'],hashlib.sha256(a.read_bytes()).hexdigest())
            sf=write_outer_sha256(a)
            expected, name=sf.read_text().strip().split('  ',1)
            self.assertEqual(name,a.name)
            self.assertEqual(expected,hashlib.sha256(a.read_bytes()).hexdigest())

    def test_fresh_archive_verifier_checks_manifest_scan_and_required_docs(self):
        from harness.public_preview import build_preview_archive
        from tools.verify_oss_prerelease_candidate import verify_candidate
        policy=json.loads((ROOT/'oss/PUBLIC_SOURCE_POLICY.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as td:
            archive=Path(td)/'candidate.zip'; build_preview_archive(ROOT,policy,archive)
            report=verify_candidate(archive)
            self.assertEqual(report['overall_result'],'PASS')
            self.assertEqual(report['checksum_result'],'PASS')
            self.assertEqual(report['secret_privacy_scan'],'PASS')
            self.assertEqual(report['public_boundary'],'PASS')
            self.assertTrue(report['required_docs_present'])
            self.assertFalse(report['publishable'])

    def test_verifier_cli_runs_without_tools_harness_shadowing(self):
        import subprocess, sys
        from harness.public_preview import build_preview_archive
        policy=json.loads((ROOT/'oss/PUBLIC_SOURCE_POLICY.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as td:
            archive=Path(td)/'candidate.zip'; build_preview_archive(ROOT,policy,archive)
            cp=subprocess.run([sys.executable,str(ROOT/'tools/verify_oss_prerelease_candidate.py'),str(archive)],cwd=ROOT,text=True,capture_output=True)
            self.assertEqual(cp.returncode,0,cp.stderr+cp.stdout)
            self.assertEqual(json.loads(cp.stdout)['overall_result'],'PASS')

    def test_verifier_requires_matching_outer_checksum_when_supplied(self):
        from unittest.mock import patch
        from harness.public_preview import build_preview_archive
        from tools.verify_oss_prerelease_candidate import verify_candidate

        policy=json.loads((ROOT/'oss/PUBLIC_SOURCE_POLICY.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            archive=root/'candidate.zip'
            checksum=root/'candidate.zip.sha256'
            build_preview_archive(ROOT,policy,archive)
            checksum.write_text('0'*64+'  candidate.zip\n',encoding='utf-8')
            with patch('tools.verify_oss_prerelease_candidate.run_smoke') as smoke:
                report=verify_candidate(archive,checksum)
            smoke.assert_not_called()
            self.assertEqual(report['overall_result'],'FAIL')
            self.assertEqual(report['outer_checksum_result'],'FAIL')
            self.assertEqual(report['smoke_result'],'BLOCKED')

    def test_verifier_rejects_bundled_binary_member(self):
        from harness.public_preview import build_preview_archive
        from tools.verify_oss_prerelease_candidate import verify_candidate

        policy=json.loads((ROOT/'oss/PUBLIC_SOURCE_POLICY.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            original=root/'candidate.zip'
            tampered=root/'candidate-with-native.zip'
            build_preview_archive(ROOT,policy,original)
            with zipfile.ZipFile(original) as source, zipfile.ZipFile(tampered,'w',compression=zipfile.ZIP_DEFLATED) as destination:
                for info in source.infolist():
                    destination.writestr(info,source.read(info.filename))
                destination.writestr('native/libpeer.dylib',b'not-a-native-binary')
            report=verify_candidate(tampered)
            self.assertEqual(report['overall_result'],'FAIL')
            self.assertEqual(report['source_only_result'],'FAIL')

    def test_verifier_rejects_product_qualification_in_self_consistent_metadata(self):
        from harness.public_preview import build_preview_archive
        from tools.verify_oss_prerelease_candidate import verify_candidate

        policy=json.loads((ROOT/'oss/PUBLIC_SOURCE_POLICY.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            original=root/'candidate.zip'
            build_preview_archive(ROOT,policy,original)
            for record, expected_error in (
                ('PUBLIC_SOURCE_MANIFEST.json', 'manifest.product_qualified'),
                ('PUBLIC_PREVIEW_STATUS.json', 'status.product_qualified'),
            ):
                with self.subTest(record=record):
                    tampered=root/f'{record}.zip'
                    rewrite_rechecksummed_archive(
                        original,
                        tampered,
                        lambda metadata, record=record: metadata[record].update(product_qualified=True),
                    )
                    report=verify_candidate(tampered)
                    self.assertEqual(report['technical_result'],'FAIL')
                    self.assertIn(expected_error,{row['field'] for row in report['relationship_errors']})

    def test_verifier_requires_policy_identity_and_prerequisite_order_in_metadata(self):
        from harness.public_preview import build_preview_archive
        from tools.verify_oss_prerelease_candidate import verify_candidate

        policy=json.loads((ROOT/'oss/PUBLIC_SOURCE_POLICY.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            original=root/'candidate.zip'
            build_preview_archive(ROOT,policy,original)
            cases=(
                ('policy-release-profile', 'oss/PUBLIC_SOURCE_POLICY.json', 'release_profile', 'oss/WRONG_PROFILE.json', 'policy.release_profile'),
                ('policy-publishable', 'oss/PUBLIC_SOURCE_POLICY.json', 'publishable', True, 'policy.publishable'),
                ('manifest-gates', 'PUBLIC_SOURCE_MANIFEST.json', 'unresolved_gates', ['hosted_ci','github_private_vulnerability_reporting','public_repository'], 'manifest.unresolved_gates'),
                ('status-gates', 'PUBLIC_PREVIEW_STATUS.json', 'unresolved_gates', ['hosted_ci','github_private_vulnerability_reporting','public_repository'], 'status.unresolved_gates'),
            )
            for name, record, field, value, expected_error in cases:
                with self.subTest(name=name):
                    tampered=root/f'{name}.zip'
                    rewrite_rechecksummed_archive(
                        original,
                        tampered,
                        lambda metadata, record=record, field=field, value=value: metadata[record].update({field: value}),
                    )
                    report=verify_candidate(tampered)
                    self.assertEqual(report['technical_result'],'FAIL')
                    self.assertIn(expected_error,{row['field'] for row in report['relationship_errors']})

    def test_invalid_utf8_companion_and_missing_archive_return_structured_failures(self):
        import subprocess
        import sys
        from harness.public_preview import build_preview_archive
        from tools.verify_oss_prerelease_candidate import verify_candidate

        policy=json.loads((ROOT/'oss/PUBLIC_SOURCE_POLICY.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            archive=root/'candidate.zip'
            checksum=root/'candidate.zip.sha256'
            build_preview_archive(ROOT,policy,archive)
            checksum.write_bytes(b'\xff')
            report=verify_candidate(archive,checksum)
            self.assertEqual(report['technical_result'],'FAIL')
            self.assertEqual(report['outer_checksum_result'],'FAIL')
            self.assertEqual(report['outer_checksum_error'],'SHA256_FILE_UNREADABLE')
            cli=subprocess.run([sys.executable,str(ROOT/'tools/verify_oss_prerelease_candidate.py'),str(archive),'--sha256-file',str(checksum)],cwd=ROOT,text=True,capture_output=True)
            self.assertNotEqual(cli.returncode,0,cli.stderr+cli.stdout)
            self.assertEqual(json.loads(cli.stdout)['outer_checksum_result'],'FAIL')
            missing=verify_candidate(root/'missing.zip')
            self.assertEqual(missing['technical_result'],'FAIL')
            self.assertEqual(missing['archive_error'],'INVALID_ZIP')

    def test_invalid_utf8_notice_returns_structured_api_and_cli_failure(self):
        import subprocess
        import sys
        from harness.public_preview import build_preview_archive
        from tools.verify_oss_prerelease_candidate import verify_candidate

        policy=json.loads((ROOT/'oss/PUBLIC_SOURCE_POLICY.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            original=root/'candidate.zip'
            tampered=root/'invalid-notice.zip'
            build_preview_archive(ROOT,policy,original)
            rewrite_rechecksummed_archive(
                original,
                tampered,
                lambda metadata: None,
                lambda entries: entries.update({'NOTICE': b'\xff'}),
            )
            report=verify_candidate(tampered)
            self.assertEqual(report['technical_result'],'FAIL')
            self.assertIn('NOTICE_INVALID_UTF8',report['legal_material_errors'])
            cli=subprocess.run([sys.executable,str(ROOT/'tools/verify_oss_prerelease_candidate.py'),str(tampered)],cwd=ROOT,text=True,capture_output=True)
            self.assertNotEqual(cli.returncode,0,cli.stderr+cli.stdout)
            cli_report=json.loads(cli.stdout)
            self.assertEqual(cli_report['technical_result'],'FAIL')
            self.assertIn('NOTICE_INVALID_UTF8',cli_report['legal_material_errors'])


class OssPrereleaseGitHubHandoffTests(unittest.TestCase):
    def assert_source_alpha_ci_contract(self, wf):
        self.assertIn('contents: read',wf)
        self.assertNotIn('secrets.',wf)
        self.assertNotRegex(wf, r'(?im)^\s*[\w-]+:\s*(?:write|write-all)\s*$')
        self.assertNotRegex(wf, r'(?im)\buses:\s*\S*(?:upload|attest|release)\S*')
        self.assertNotRegex(wf, r'(?im)\bgh\s+(?:release|attestation)\s+')
        local = re.search(r'(?ms)^  local-reference:\n(.*?)(?=^  [\w-]+:|\Z)', wf)
        self.assertIsNotNone(local, 'local-reference job is required')
        local = local.group(1)
        self.assertIn('native-readiness:',wf)
        self.assertIn('PAR_NATIVE_CI_ENABLED',wf)
        for cmd in [
            'python3 tools/test_runner.py',
            'python3 tools/check_public_preview_boundary.py',
            'python3 tools/build_oss_inventory.py --check',
            'python3 tools/build_public_preview_candidate.py --output /tmp/peer-application-runtime-0.1.0-alpha.1-source.zip --sha256-file /tmp/peer-application-runtime-0.1.0-alpha.1-source.zip.sha256',
            'python3 tools/verify_oss_prerelease_candidate.py /tmp/peer-application-runtime-0.1.0-alpha.1-source.zip --sha256-file /tmp/peer-application-runtime-0.1.0-alpha.1-source.zip.sha256',
        ]:
            self.assertIn(cmd,local)
        self.assertNotIn('python3 tools/harness.py validate',local)

    def test_ci_is_read_only_secret_free_and_separates_native_lane(self):
        wf=(ROOT/'.github/workflows/oss-prerelease-ci.yml').read_text(encoding='utf-8')
        self.assert_source_alpha_ci_contract(wf)

    def test_ci_guard_rejects_commands_in_wrong_job_and_release_actions(self):
        wf=(ROOT/'.github/workflows/oss-prerelease-ci.yml').read_text(encoding='utf-8')
        command = 'python3 tools/build_oss_inventory.py --check'
        moved = wf.replace('        run: ' + command, '        run: true')
        moved += '\n      - run: ' + command + '\n'
        mutations = [moved, wf.replace('contents: read', 'contents: write')]
        for action in ('actions/upload-artifact@v4', 'actions/attest-build-provenance@v2', 'softprops/action-gh-release@v2'):
            mutations.append(wf + '\n      - uses: ' + action + '\n')
        for mutation in mutations:
            with self.subTest(mutation=mutation[-100:]), self.assertRaises(AssertionError):
                self.assert_source_alpha_ci_contract(mutation)

    def test_github_templates_and_codex_handoff_cover_release_decisions_and_commands(self):
        for rel in ['.github/PULL_REQUEST_TEMPLATE.md','.github/ISSUE_TEMPLATE/bug_report.yml','.github/ISSUE_TEMPLATE/security_notice.yml','oss/GITHUB_RELEASE_GUIDE.md','oss/CODEX_OSS_RELEASE_HANDOFF.md']:
            self.assertTrue((ROOT/rel).is_file(),rel)
        guide=(ROOT/'oss/GITHUB_RELEASE_GUIDE.md').read_text(encoding='utf-8')
        handoff=(ROOT/'oss/CODEX_OSS_RELEASE_HANDOFF.md').read_text(encoding='utf-8')
        for item in ['license','project name','security contact','public repository','version/tag','copyright/notice']:
            self.assertIn(item,handoff.lower())
        for text in (guide,handoff):
            for item in [
                'dyskinmel/peer-application-runtime',
                'GitHub private vulnerability reporting',
                'source-only',
                'NOT_APPLICABLE',
                'v0.1.0-alpha.1',
                'peer-application-runtime-0.1.0-alpha.1-source.zip',
                'publishable',
                'release_authorized',
                'No email fallback is supplied.',
            ]:
                self.assertIn(item,text)
        for cmd in ['tools/build_oss_inventory.py --check','tools/verify_oss_prerelease_candidate.py','0.1.0-alpha.1']:
            self.assertIn(cmd,handoff)
        self.assertIn('Pre-release',handoff)
        self.assertIn('hosted CI',handoff)
        self.assertIn('attestation',handoff)


class OssPrereleaseCheckerAuthorityTests(unittest.TestCase):
    def test_public_preview_checker_uses_0068_policy(self):
        import subprocess,sys
        cp=subprocess.run([sys.executable,str(ROOT/'tools/check_public_preview_boundary.py')],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(cp.returncode,0,cp.stderr+cp.stdout)
        data=json.loads(cp.stdout)
        policy=json.loads((ROOT/'oss/PUBLIC_SOURCE_POLICY.json').read_text(encoding='utf-8'))
        self.assertEqual(data['unresolved_gates'],policy['unresolved_gates'])
        self.assertEqual(data['unresolved_gates'],['public_repository','github_private_vulnerability_reporting','hosted_ci'])


if __name__ == '__main__':
    unittest.main()
