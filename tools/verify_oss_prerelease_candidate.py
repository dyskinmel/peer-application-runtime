#!/usr/bin/env python3
"""Validate a source-only public-alpha ZIP without trusting its checkout of origin."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.public_alpha import PROFILE_RELATIVE_PATH, validate_public_alpha_profile
from harness.public_preview import classify_public_path, scan_public_surface
from tools.check_public_alpha_smoke import run_smoke


GENERATED = {'PUBLIC_SOURCE_MANIFEST.json', 'PUBLIC_PREVIEW_STATUS.json', 'SHA256SUMS'}
REQUIRED_DOCS = {
    'README.md', 'CONTRIBUTING.md', 'SECURITY.md', 'RELEASE_NOTES.md', 'CHANGELOG.md',
    'docs/ARCHITECTURE.md', 'docs/GETTING_STARTED.md', 'docs/KNOWN_LIMITATIONS.md',
    'docs/ROADMAP.md',
}
REQUIRED_INVENTORY = {
    'oss/DEPENDENCY_INVENTORY.json', 'oss/THIRD_PARTY_INVENTORY.json',
    'oss/SBOM.spdx.json', 'oss/LICENSE_DECISION_REQUIRED.json',
}
REQUIRED_LEGAL = {'LICENSE', 'NOTICE'}
REQUIRED_PROFILE_RECORDS = {PROFILE_RELATIVE_PATH.as_posix(), 'oss/RELEASE_DECISIONS.json'}
FORBIDDEN_PREFIXES = (
    '.git/', '.harness/', '.agents/', 'evidence/', 'handoff/', 'plan/', 'release/',
    'knowledge/', 'target/', 'node_modules/', '__pycache__/', 'docs/history/',
    'baseline/spec-00.02.00/history/',
)
FORBIDDEN_EXACT = {'AGENTS.md', 'PLANS.md', 'START_HERE.ja.md'}
FORBIDDEN_SUFFIXES = {'.a', '.dylib', '.dll', '.exe', '.so', '.whl', '.zip', '.tar', '.gz', '.tgz'}
APACHE_LICENSE_SHA256 = 'cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30'
_SHA256_RECORD = re.compile(r'([0-9a-f]{64})  ([^\r\n]+)\Z')


def _unsafe_member(info: zipfile.ZipInfo) -> str | None:
    name = info.filename
    posix = PurePosixPath(name)
    windows = PureWindowsPath(name)
    if not name or name.startswith(('\\', '/')) or posix.is_absolute() or windows.is_absolute():
        return 'ABSOLUTE_PATH'
    if '..' in posix.parts or '..' in windows.parts:
        return 'PARENT_TRAVERSAL'
    if stat.S_ISLNK(info.external_attr >> 16):
        return 'SYMLINK'
    return None


def _parse_outer_checksum(archive: Path, sha256_file: Path | None) -> tuple[str, str | None]:
    if sha256_file is None:
        return 'NOT_PROVIDED', None
    if not archive.is_file():
        return 'FAIL', 'ARCHIVE_UNREADABLE'
    try:
        lines = sha256_file.read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeDecodeError):
        return 'FAIL', 'SHA256_FILE_UNREADABLE'
    if len(lines) != 1:
        return 'FAIL', 'SHA256_RECORD_COUNT'
    match = _SHA256_RECORD.fullmatch(lines[0])
    if match is None:
        return 'FAIL', 'SHA256_RECORD_FORMAT'
    digest, filename = match.groups()
    if filename != archive.name:
        return 'FAIL', 'SHA256_FILENAME_MISMATCH'
    try:
        archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    except OSError:
        return 'FAIL', 'ARCHIVE_UNREADABLE'
    if digest != archive_digest:
        return 'FAIL', 'SHA256_DIGEST_MISMATCH'
    return 'PASS', None


def _parse_sums(z: zipfile.ZipFile, names: list[str]) -> list[dict]:
    errors: list[dict] = []
    try:
        lines = z.read('SHA256SUMS').decode('utf-8').splitlines()
    except (KeyError, UnicodeDecodeError):
        return [{'kind': 'SHA256SUMS_UNREADABLE'}]
    sums: dict[str, str] = {}
    for line in lines:
        match = _SHA256_RECORD.fullmatch(line)
        if match is None:
            errors.append({'kind': 'SHA256SUMS_FORMAT', 'line': line})
            continue
        digest, name = match.groups()
        if name in sums:
            errors.append({'kind': 'SHA256SUMS_DUPLICATE', 'path': name})
            continue
        sums[name] = digest
    expected_names = set(names) - {'SHA256SUMS'}
    if set(sums) != expected_names:
        errors.append({'kind': 'SHA256SUMS_COVERAGE', 'missing': sorted(expected_names - set(sums)), 'unexpected': sorted(set(sums) - expected_names)})
    for name, digest in sums.items():
        if name in names and hashlib.sha256(z.read(name)).hexdigest() != digest:
            errors.append({'kind': 'SHA256SUMS_MISMATCH', 'path': name})
    return errors


def _read_json(root: Path, rel: str) -> tuple[dict, str | None]:
    try:
        value = json.loads((root / rel).read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}, f'{rel}:INVALID_JSON'
    return (value, None) if isinstance(value, dict) else ({}, f'{rel}:NOT_OBJECT')


def _value_at(record: dict, field: str):
    value = record
    for part in field.split('.'):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _contract_errors(record: dict, expected: dict, prefix: str) -> list[dict]:
    errors = []
    for field, want in expected.items():
        actual = _value_at(record, field)
        if actual != want or (isinstance(want, bool) and actual is not want):
            errors.append({'field': f'{prefix}.{field}', 'expected': want, 'actual': actual})
    return errors


def _decision_errors(profile: dict, decision: dict) -> list[dict]:
    expected = {
        'publishable': _value_at(profile, 'publication.publishable'),
        'release_authorized': _value_at(profile, 'publication.release_authorized'),
        'decisions.license.spdx': _value_at(profile, 'license.spdx'),
        'decisions.project_name.value': _value_at(profile, 'project.name'),
        'decisions.project_name.may_change': True,
        'decisions.release_version.value': profile.get('version'),
        'decisions.release_version.intended_tag': profile.get('intended_tag'),
        'decisions.copyright_notice.value': _value_at(profile, 'copyright.notice'),
        'decisions.final_native_dependency_sbom.status': 'NOT_APPLICABLE',
        'decisions.final_native_dependency_sbom.scope': 'SOURCE_ONLY_ALPHA',
        'decisions.public_repository.slug': _value_at(profile, 'repository.slug'),
        'decisions.security_reporting.provider': _value_at(profile, 'security_reporting.provider'),
        'decisions.release_signing.status': 'NOT_REQUIRED_FOR_SOURCE_ONLY_ALPHA',
        'decisions.hosted_attestation.status': 'NOT_REQUIRED_FOR_SOURCE_ONLY_ALPHA',
    }
    for name in ('license', 'project_name', 'release_version', 'copyright_notice'):
        expected[f'decisions.{name}.status'] = 'RESOLVED_LOCAL'
    for name in ('public_repository', 'security_reporting', 'hosted_ci'):
        expected[f'decisions.{name}.status'] = 'COMPLETED'
    return _contract_errors(decision, expected, 'decision')


def _inventory_errors(root: Path, profile: dict) -> list[dict]:
    """Validate source-only claims as data, without executing archive code."""
    records = {}
    errors = []
    for path in sorted(REQUIRED_INVENTORY):
        records[path], error = _read_json(root, path)
        if error:
            errors.append({'field': path, 'reason': error})
    gate = records['oss/LICENSE_DECISION_REQUIRED.json']
    errors.extend(_contract_errors(gate, {
        'status': 'RESOLVED_SOURCE_ONLY_ALPHA',
        'publishable': _value_at(profile, 'publication.publishable'),
        'selected_spdx_license': 'Apache-2.0', 'final_license_text': 'LICENSE',
        'copyright_holder': 'dyskinmel', 'notice_finalized': True,
        'baseline_license_is_release_authorization': False,
        'external_publish_prerequisites': profile.get('external_publish_prerequisites'),
    }, 'license_gate'))
    third = records['oss/THIRD_PARTY_INVENTORY.json']
    errors.extend(_contract_errors(third, {
        'release_license_decision': 'Apache-2.0',
        'license_authorized_for_publication': _value_at(profile, 'publication.release_authorized'),
        'repository_license_material_complete': True,
        'third_party_compatibility': 'REVIEWED_NO_BUNDLED_THIRD_PARTY_ARTIFACTS',
        'source_only_alpha_dependency_review.status': 'COMPLETED',
        'source_only_alpha_dependency_review.scope': 'DECLARED_AND_REFERENCED_UNBUNDLED_DEPENDENCIES',
        'source_only_alpha_dependency_review.conclusion': 'NO_KNOWN_LICENSE_CONFLICT_FOR_SOURCE_ONLY_ALPHA_SCOPE',
        'potential_license_conflicts': [],
        'legal_conclusion': 'FACTUAL_LICENSE_REVIEW_COMPLETED_NOT_LEGAL_ADVICE',
    }, 'third_party'))
    material = third.get('repository_license_material')
    if not isinstance(material, list) or len(material) != 2 or any(not isinstance(row, dict) for row in material):
        errors.append({'field': 'third_party.repository_license_material', 'reason': 'LICENSE_AND_NOTICE_REQUIRED'})
    else:
        by_path = {row.get('path'): row for row in material if isinstance(row.get('path'), str)}
        for path in sorted(REQUIRED_LEGAL):
            try:
                digest = hashlib.sha256((root / path).read_bytes()).hexdigest()
            except OSError:
                digest = None
            errors.extend(_contract_errors(by_path.get(path, {}), {
                'path': path, 'sha256': digest, 'included_in_public_candidate': True,
                'status': 'FINAL_REPOSITORY_LICENSE_MATERIAL',
            }, f'third_party.repository_license_material.{path}'))
    license_rows = third.get('dependency_license_status')
    expected_license_status = {
        'libsodium-ctypes-local-candidate': ('ISC', 'REVIEWED_OFFICIAL_SOURCE'),
        'sqlite': ('LicenseRef-SQLite-Public-Domain', 'REVIEWED_OFFICIAL_SOURCE'),
        'typescript-compiler': ('Apache-2.0', 'REVIEWED_OFFICIAL_SOURCE'),
        'automerge-native-dependency': ('MIT', 'REVIEWED_OFFICIAL_SOURCE'),
        'production-crypto-provider': ('UNKNOWN', 'FUTURE_SELECTION_REQUIRED'),
    }
    if not isinstance(license_rows, list) or any(not isinstance(row, dict) for row in license_rows):
        errors.append({'field': 'third_party.dependency_license_status', 'reason': 'REVIEW_ROWS_REQUIRED'})
    else:
        by_name = {row.get('name'): row for row in license_rows}
        for name, (license_id, status) in expected_license_status.items():
            row = by_name.get(name, {})
            errors.extend(_contract_errors(row, {
                'name': name, 'detected_license': license_id, 'status': status,
            }, f'third_party.dependency_license_status.{name}'))
            evidence = row.get('license_evidence')
            if not isinstance(evidence, dict) or evidence.get('reviewed_on') != '2026-09-16':
                errors.append({'field': f'third_party.dependency_license_status.{name}.license_evidence', 'reason': 'DATED_EVIDENCE_REQUIRED'})
            elif status == 'REVIEWED_OFFICIAL_SOURCE' and (evidence.get('source_kind') != 'OFFICIAL_UPSTREAM' or not str(evidence.get('url', '')).startswith('https://')):
                errors.append({'field': f'third_party.dependency_license_status.{name}.license_evidence', 'reason': 'OFFICIAL_HTTPS_SOURCE_REQUIRED'})
    dependency = records['oss/DEPENDENCY_INVENTORY.json']
    errors.extend(_contract_errors(dependency, {
        'classification': 'PRE_RELEASE_SOURCE_DEPENDENCY_INVENTORY_NOT_FINAL_RESOLUTION',
        'network_resolution_performed': False,
    }, 'dependency'))
    sbom = records['oss/SBOM.spdx.json']
    errors.extend(_contract_errors(sbom, {
        'spdxVersion': 'SPDX-2.3',
        'parMetadata.final': False,
        'parMetadata.classification': 'SOURCE_ONLY_ALPHA_DEPENDENCY_INVENTORY',
        'parMetadata.sourceOnlyRelease': True,
        'parMetadata.nativeArtifactBundled': False,
        'parMetadata.nativeDependencySbomStatus': 'NOT_APPLICABLE',
        'parMetadata.nativeDependencySbomRequiredBefore': ['native_artifact_distribution', 'binary_distribution'],
        'parMetadata.networkResolutionPerformed': False,
    }, 'sbom'))
    packages = sbom.get('packages')
    project = [row for row in packages if isinstance(row, dict) and row.get('SPDXID') == 'SPDXRef-PAR-Source-Candidate'] if isinstance(packages, list) else []
    if len(project) != 1:
        errors.append({'field': 'sbom.packages', 'reason': 'EXACTLY_ONE_PROJECT_REQUIRED'})
    else:
        errors.extend(_contract_errors(project[0], {
            'name': _value_at(profile, 'project.name'),
            'versionInfo': profile.get('version'), 'licenseDeclared': 'Apache-2.0',
            'filesAnalyzed': False, 'licenseConcluded': 'NOASSERTION',
        }, 'sbom.project'))
    return errors


def _base_report(archive: Path, outer_checksum_result: str, outer_checksum_error: str | None) -> dict:
    try:
        archive_bytes = archive.read_bytes()
    except OSError:
        archive_bytes = None
    return {
        'overall_result': 'FAIL', 'technical_result': 'FAIL', 'archive_integrity': 'FAIL',
        'archive_bytes': len(archive_bytes) if archive_bytes is not None else 0,
        'archive_sha256': hashlib.sha256(archive_bytes).hexdigest() if archive_bytes is not None else None,
        'outer_checksum_result': outer_checksum_result, 'outer_checksum_error': outer_checksum_error,
        'required_legal_material_present': False, 'source_only_result': 'FAIL', 'smoke_result': 'BLOCKED',
        'external_publish_prerequisites': [], 'publishable': False, 'release_authorized': False,
        'product_qualified': False,
    }


def verify_candidate(archive: Path, sha256_file: Path | None = None) -> dict:
    archive = Path(archive)
    sha256_file = Path(sha256_file) if sha256_file is not None else None
    outer_result, outer_error = _parse_outer_checksum(archive, sha256_file)
    report = _base_report(archive, outer_result, outer_error)
    try:
        z = zipfile.ZipFile(archive)
    except (OSError, zipfile.BadZipFile):
        report['archive_error'] = 'INVALID_ZIP'
        return report

    with z:
        infos = z.infolist()
        names = [info.filename for info in infos]
        unsafe = [{'path': info.filename, 'kind': reason} for info in infos if (reason := _unsafe_member(info))]
        duplicate_count = len(names) - len(set(names))
        crc_bad = z.testzip()
        report.update({'unsafe_paths': unsafe, 'duplicate_count': duplicate_count, 'crc_bad': crc_bad, 'archive_integrity': 'PASS' if not unsafe and not duplicate_count and not crc_bad else 'FAIL'})
        if unsafe or duplicate_count or crc_bad:
            return report

        member_set = set(names)
        required_legal = REQUIRED_LEGAL <= member_set
        required_paths = REQUIRED_DOCS | REQUIRED_LEGAL | REQUIRED_PROFILE_RECORDS | REQUIRED_INVENTORY | GENERATED
        required_missing = sorted(required_paths - member_set)
        report.update({'required_legal_material_present': required_legal, 'required_docs_present': REQUIRED_DOCS <= member_set, 'required_missing': required_missing})

        try:
            manifest = json.loads(z.read('PUBLIC_SOURCE_MANIFEST.json'))
            status = json.loads(z.read('PUBLIC_PREVIEW_STATUS.json'))
            if not isinstance(manifest, dict) or not isinstance(status, dict):
                raise ValueError('GENERATED_METADATA_NOT_OBJECT')
        except (KeyError, UnicodeDecodeError, ValueError):
            manifest, status = {}, {}
            report['metadata_error'] = 'GENERATED_METADATA_INVALID'
        rows = manifest.get('files') if isinstance(manifest.get('files'), list) else []
        expected: dict[str, dict] = {}
        manifest_errors: list[dict] = []
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('path'), str):
                manifest_errors.append({'kind': 'MANIFEST_ROW_INVALID'})
                continue
            if row['path'] in expected:
                manifest_errors.append({'kind': 'MANIFEST_DUPLICATE', 'path': row['path']})
            expected[row['path']] = row
        actual = member_set - GENERATED
        missing = sorted(set(expected) - actual)
        unexpected = sorted(actual - set(expected))
        for path, row in expected.items():
            if path in member_set:
                data = z.read(path)
                if row.get('size_bytes') != len(data) or row.get('sha256') != hashlib.sha256(data).hexdigest():
                    manifest_errors.append({'kind': 'MANIFEST_CONTENT_MISMATCH', 'path': path})
        sums_errors = _parse_sums(z, names)
        checksum_errors = manifest_errors + sums_errors
        checksum_ok = not checksum_errors and not missing and not unexpected
        report.update({'source': manifest.get('source'), 'candidate_file_count': len(expected), 'candidate_bytes': manifest.get('total_bytes'), 'manifest_sha256': manifest.get('manifest_sha256'), 'checksum_result': 'PASS' if checksum_ok else 'FAIL', 'checksum_errors': checksum_errors, 'missing': missing, 'unexpected': unexpected})

        forbidden = sorted(name for name in names if name in FORBIDDEN_EXACT or any(name.startswith(prefix) for prefix in FORBIDDEN_PREFIXES))
        binary = sorted(name for name in names if name not in GENERATED and Path(name).suffix.lower() in FORBIDDEN_SUFFIXES)
        dockerfiles = sorted(name for name in names if PurePosixPath(name).name.lower() == 'dockerfile')

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            z.extractall(root)
            policy, policy_error = _read_json(root, 'oss/PUBLIC_SOURCE_POLICY.json')
            profile, profile_error = _read_json(root, PROFILE_RELATIVE_PATH.as_posix())
            decision, decision_error = _read_json(root, 'oss/RELEASE_DECISIONS.json')
            profile_errors = ([{'field': 'profile', 'reason': profile_error}] if profile_error else validate_public_alpha_profile(root, profile))
            prerequisites = profile.get('external_publish_prerequisites')
            unresolved_ids = [
                row.get('id') for row in prerequisites
                if isinstance(row, dict) and row.get('status') != 'COMPLETED'
            ] if isinstance(prerequisites, list) else []
            inventory_errors = _inventory_errors(root, profile)
            relationship_errors = []
            if policy_error:
                relationship_errors.append({'field': 'policy', 'reason': policy_error})
            else:
                if policy.get('release_profile') != PROFILE_RELATIVE_PATH.as_posix():
                    relationship_errors.append({'field': 'policy.release_profile'})
                if policy.get('publishable') is not _value_at(profile, 'publication.publishable'):
                    relationship_errors.append({'field': 'policy.publishable'})
                if policy.get('unresolved_gates') != unresolved_ids:
                    relationship_errors.append({'field': 'policy.unresolved_gates'})
            for source, record in (('manifest', manifest), ('status', status)):
                if record.get('release_profile') != PROFILE_RELATIVE_PATH.as_posix(): relationship_errors.append({'field': f'{source}.release_profile'})
                if record.get('external_publish_prerequisites') != profile.get('external_publish_prerequisites'): relationship_errors.append({'field': f'{source}.external_publish_prerequisites'})
                if record.get('unresolved_gates') != unresolved_ids: relationship_errors.append({'field': f'{source}.unresolved_gates'})
                if record.get('publishable') is not _value_at(profile, 'publication.publishable'): relationship_errors.append({'field': f'{source}.publishable'})
                if record.get('release_authorized') is not _value_at(profile, 'publication.release_authorized'): relationship_errors.append({'field': f'{source}.release_authorized'})
                if record.get('product_qualified') is not False: relationship_errors.append({'field': f'{source}.product_qualified'})
            if decision_error:
                relationship_errors.append({'field': 'decision', 'reason': decision_error})
            else:
                relationship_errors.extend(_decision_errors(profile, decision))
            classification_violations = []
            if not policy_error:
                classification_violations = [name for name in sorted(actual) if classify_public_path(Path(name), policy) not in {'PUBLIC', 'PUBLIC_DEVELOPMENT'}]
            try:
                scan = scan_public_surface(root, policy, [Path(path) for path in sorted(actual)]) if not policy_error else {'pass': False, 'findings': [{'kind': 'POLICY_INVALID'}]}
            except OSError:
                scan = {'pass': False, 'findings': [{'kind': 'PUBLIC_SURFACE_SCAN_FAILED'}]}
            notice_error = None
            if not required_legal:
                notice_ok = False
            else:
                try:
                    notice = _value_at(profile, 'copyright.notice')
                    notice_ok = notice == 'Copyright 2026 dyskinmel' and (root / 'NOTICE').read_text(encoding='utf-8').startswith(notice)
                except UnicodeDecodeError:
                    notice_ok = False
                    notice_error = 'NOTICE_INVALID_UTF8'
                except OSError:
                    notice_ok = False
                    notice_error = 'NOTICE_UNREADABLE'
            try:
                license_ok = required_legal and hashlib.sha256((root / 'LICENSE').read_bytes()).hexdigest() == APACHE_LICENSE_SHA256
            except OSError:
                license_ok = False

            source_only_violations = forbidden + binary + dockerfiles + classification_violations
            source_only_ok = not source_only_violations and profile.get('release_type') == 'SOURCE_ONLY_ALPHA'
            boundary_ok = not forbidden and not classification_violations and not unexpected and not missing
            report.update({
                'required_legal_material_present': required_legal and license_ok and notice_ok,
                'legal_material_errors': ([] if license_ok else ['LICENSE_NOT_CANONICAL']) + ([] if notice_ok else [notice_error or 'NOTICE_MISMATCH']),
                'source_only_result': 'PASS' if source_only_ok else 'FAIL',
                'source_only_violations': source_only_violations,
                'secret_privacy_scan': 'PASS' if scan['pass'] else 'FAIL',
                'scan_findings': scan['findings'],
                'scan_allowlisted_count': len(scan.get('allowlisted_findings', [])),
                'public_boundary': 'PASS' if boundary_ok else 'FAIL',
                'forbidden_paths': forbidden, 'classification_violations': classification_violations,
                'dependency_inventory': 'FAIL' if inventory_errors else 'PASS',
                'inventory_errors': inventory_errors,
                'profile_errors': profile_errors, 'relationship_errors': relationship_errors,
                'smoke_checks': [],
                'external_publish_prerequisites': profile.get('external_publish_prerequisites', []),
                'unresolved_publish_gates': status.get('unresolved_gates', []),
            })
            static_ok = all((
                report['archive_integrity'] == 'PASS', outer_result in {'PASS', 'NOT_PROVIDED'},
                checksum_ok, not required_missing, report['required_legal_material_present'],
                source_only_ok, scan['pass'], boundary_ok, not profile_errors,
                not relationship_errors, not inventory_errors, not report.get('metadata_error'),
            ))
            if not static_ok:
                return report
            smoke = run_smoke(root)
            report.update({'smoke_result': smoke['overall_result'], 'smoke_checks': smoke['checks']})
        technical = smoke['overall_result'] == 'PASS'
        report['technical_result'] = 'PASS' if technical else 'FAIL'
        report['overall_result'] = report['technical_result']
        report['publishable'] = bool(technical and manifest.get('publishable') is True)
        report['release_authorized'] = bool(technical and manifest.get('release_authorized') is True)
        return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    parser.add_argument('--sha256-file', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = verify_candidate(args.archive, args.sha256_file)
    text = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + '\n'
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')
    return 0 if result['technical_result'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
