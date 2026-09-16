"""Checked-in contract for the source-only public alpha release."""

import json
from pathlib import Path
from typing import Any


PROFILE_RELATIVE_PATH = Path('oss/PUBLIC_ALPHA_RELEASE.json')

EXPECTED = {
    'release_type': 'SOURCE_ONLY_ALPHA',
    'project.name': 'Peer Application Runtime',
    'project.short_name': 'PAR',
    'version': '0.1.0-alpha.1',
    'intended_tag': 'v0.1.0-alpha.1',
    'license.spdx': 'Apache-2.0',
    'copyright.public_holder': 'dyskinmel',
    'copyright.notice': 'Copyright 2026 dyskinmel',
    'security_reporting.provider': 'GITHUB_PRIVATE_VULNERABILITY_REPORTING',
    'security_reporting.email_published': False,
    'repository.import_source': 'VERIFIED_SOURCE_ARCHIVE_CONTENTS',
    'repository.preserve_development_git_history': False,
    'repository.development_checkout_push_allowed': False,
    'source_only.native_dependency_sbom.status': 'NOT_APPLICABLE',
    'publication.publishable': False,
    'publication.release_authorized': False,
}

_MISSING = object()
_EXTERNAL_ACTION_REQUIRED = 'EXTERNAL_ACTION_REQUIRED'
_PREREQUISITES = [
    {'id': 'public_repository', 'status': _EXTERNAL_ACTION_REQUIRED},
    {'id': 'github_private_vulnerability_reporting', 'status': _EXTERNAL_ACTION_REQUIRED},
    {'id': 'hosted_ci', 'status': _EXTERNAL_ACTION_REQUIRED},
]


def load_public_alpha_profile(root: Path) -> dict:
    """Load the checked-in alpha profile, rejecting non-object JSON roots."""
    profile = json.loads((root / PROFILE_RELATIVE_PATH).read_text(encoding='utf-8'))
    if not isinstance(profile, dict):
        raise ValueError('PUBLIC_ALPHA_PROFILE_INVALID')
    return profile


def _value_at(profile: dict[str, Any], field: str) -> Any:
    value: Any = profile
    for part in field.split('.'):
        if not isinstance(value, dict) or part not in value:
            return _MISSING
        value = value[part]
    return value


def _matches(expected: Any, actual: Any) -> bool:
    if isinstance(expected, bool):
        return actual is expected
    return actual == expected


def validate_public_alpha_profile(root: Path, profile: dict | None = None) -> list[dict]:
    """Return one field/reason row for every release-contract mismatch."""
    profile = load_public_alpha_profile(root) if profile is None else profile
    if not isinstance(profile, dict):
        return [{'field': 'profile', 'reason': 'must be an object'}]

    mismatches = []
    for field, expected in EXPECTED.items():
        actual = _value_at(profile, field)
        if not _matches(expected, actual):
            mismatches.append({'field': field, 'reason': f'expected {expected!r}'})

    required = {
        'repository.slug': 'dyskinmel/peer-application-runtime',
        'repository.status': _EXTERNAL_ACTION_REQUIRED,
        'security_reporting.status': _EXTERNAL_ACTION_REQUIRED,
        'project.name_stability': 'CURRENT_NAME_MAY_CHANGE',
        'project.trademark_claim': False,
    }
    for field, expected in required.items():
        actual = _value_at(profile, field)
        if not _matches(expected, actual):
            mismatches.append({'field': field, 'reason': f'expected {expected!r}'})

    if profile.get('external_publish_prerequisites') != _PREREQUISITES:
        mismatches.append({
            'field': 'external_publish_prerequisites',
            'reason': 'must exactly match required external-action prerequisites',
        })
    return mismatches
