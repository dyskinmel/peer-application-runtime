"""Provider-neutral crypto admission boundary.

This module validates *declared* provider structure and local replacement
preconditions.  It never turns a provider's own metadata into independent
security qualification and it performs no discovery, download, upgrade, or
fallback.
"""
from __future__ import annotations

import re
from pathlib import Path

from .errors import CryptoError

REQUIRED_CAPABILITIES = (
    'sign_public', 'sign', 'verify', 'dh_public', 'dh',
    'seal', 'open', 'seal_ietf', 'open_ietf',
)
_REQUIRED_IDENTITY = (
    'provider', 'provider_family', 'path', 'sha256', 'version',
    'security_qualified', 'legacy_experiment', 'auto_fallback',
    'maintenance_status', 'key_protection', 'dependency_closure',
    'capabilities',
)
_MAINTENANCE = {'MAINTAINED', 'LEGACY_VERSION_EXPERIMENT_ONLY', 'UNKNOWN', 'UNMAINTAINED'}
_KEY_PROTECTION = {'UNVERIFIED', 'PROCESS_MEMORY_UNVERIFIED', 'SOFTWARE_VERIFIED', 'PLATFORM_VERIFIED'}
_DEPENDENCY_CLOSURE = {'COMPLETE', 'TARGET_IMAGE_ONLY_NOT_COMPLETE_NATIVE_CLOSURE', 'TARGET_IMAGE_ONLY', 'UNKNOWN'}


def _text(value, *, limit=256):
    return type(value) is str and 1 <= len(value) <= limit and '\0' not in value


def _identity(provider):
    identity = getattr(provider, 'identity', None)
    if type(identity) is not dict or any(key not in identity for key in _REQUIRED_IDENTITY):
        raise CryptoError('PROVIDER_IDENTITY')
    if not _text(identity['provider'], limit=128) or not _text(identity['provider_family'], limit=128):
        raise CryptoError('PROVIDER_IDENTITY')
    if not _text(identity['version'], limit=128):
        raise CryptoError('PROVIDER_IDENTITY')
    path = identity['path']
    if not _text(path, limit=4096) or not Path(path).is_absolute() or '..' in Path(path).parts:
        raise CryptoError('PROVIDER_IDENTITY')
    if type(identity['sha256']) is not str or re.fullmatch(r'[0-9a-f]{64}', identity['sha256']) is None:
        raise CryptoError('PROVIDER_IDENTITY')
    for name in ('security_qualified', 'legacy_experiment', 'auto_fallback'):
        if type(identity[name]) is not bool:
            raise CryptoError('PROVIDER_IDENTITY')
    if identity['maintenance_status'] not in _MAINTENANCE:
        raise CryptoError('PROVIDER_IDENTITY')
    if identity['key_protection'] not in _KEY_PROTECTION:
        raise CryptoError('PROVIDER_IDENTITY')
    if identity['dependency_closure'] not in _DEPENDENCY_CLOSURE:
        raise CryptoError('PROVIDER_IDENTITY')
    capabilities = identity['capabilities']
    if type(capabilities) is not list or any(type(v) is not str for v in capabilities):
        raise CryptoError('PROVIDER_IDENTITY')
    if len(capabilities) != len(set(capabilities)) or not set(REQUIRED_CAPABILITIES).issubset(capabilities):
        raise CryptoError('PROVIDER_INTERFACE')
    for name in REQUIRED_CAPABILITIES:
        if not callable(getattr(provider, name, None)):
            raise CryptoError('PROVIDER_INTERFACE')
    return identity


def provider_report(provider) -> dict:
    """Return a deterministic, non-secret boundary report for one provider.

    `security_qualified` is copied only as a declaration for diagnostics.  The
    returned boundary state never promotes that declaration to a security
    decision.
    """
    identity = _identity(provider)
    review_ready = (
        not identity['legacy_experiment']
        and not identity['auto_fallback']
        and identity['maintenance_status'] == 'MAINTAINED'
        and identity['dependency_closure'] == 'COMPLETE'
        and identity['key_protection'] in {'SOFTWARE_VERIFIED', 'PLATFORM_VERIFIED'}
        and identity['security_qualified'] is False
    )
    return {
        'provider': identity['provider'],
        'provider_family': identity['provider_family'],
        'path': identity['path'],
        'sha256': identity['sha256'],
        'version': identity['version'],
        'security_qualified': identity['security_qualified'],
        'legacy_experiment': identity['legacy_experiment'],
        'auto_fallback': identity['auto_fallback'],
        'maintenance_status': identity['maintenance_status'],
        'key_protection': identity['key_protection'],
        'dependency_closure': identity['dependency_closure'],
        'capabilities': list(identity['capabilities']),
        'boundary_state': 'REVIEW_CANDIDATE' if review_ready else 'EXPERIMENT_ONLY',
        'independent_security_review': 'REQUIRED',
        'product_qualified': False,
    }


def admit_provider(provider, *, purpose: str) -> dict:
    """Admit a provider only to the requested local boundary.

    `native-review` means "eligible to enter a separate security review", not
    "safe for production".  A self-declared security-qualified provider is
    rejected because independent evidence must be bound outside this object.
    """
    if purpose not in ('experiment', 'native-review'):
        raise CryptoError('INVALID_INPUT')
    report = provider_report(provider)
    if report['auto_fallback']:
        raise CryptoError('PROVIDER_AUTOFALLBACK')
    if purpose == 'experiment':
        return report
    if report['legacy_experiment']:
        raise CryptoError('PROVIDER_LEGACY')
    if report['maintenance_status'] != 'MAINTAINED':
        raise CryptoError('PROVIDER_MAINTENANCE')
    if report['dependency_closure'] != 'COMPLETE':
        raise CryptoError('PROVIDER_DEPENDENCY_CLOSURE')
    if report['key_protection'] not in ('SOFTWARE_VERIFIED', 'PLATFORM_VERIFIED'):
        raise CryptoError('PROVIDER_KEY_PROTECTION')
    if report['security_qualified']:
        raise CryptoError('PROVIDER_SECURITY_EVIDENCE_REQUIRED')
    if report['boundary_state'] != 'REVIEW_CANDIDATE':
        raise CryptoError('PROVIDER_REVIEW_BLOCKED')
    return report
