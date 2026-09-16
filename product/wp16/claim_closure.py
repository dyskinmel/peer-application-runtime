"""Fail-closed local candidate for production-claim closure.

This module is intentionally pure and side-effect free.  It can determine whether a
claim packet is internally eligible to proceed to an external promotion review, but
it can never set Product Qualification.  External service outage, artifact readback,
independent review, native/device evidence and release authorization remain outside
this local candidate.
"""
from __future__ import annotations

from typing import Any, Mapping

_ALLOWED_STATUSES = {"PASS", "FAIL", "BLOCKED", "NOT_RUN", "NOT_APPLICABLE"}
_BINDING_KEYS = (
    "source_digest",
    "spec_digest",
    "toolchain_digest",
    "fixture_digest",
    "platform_id",
)


def _nonempty(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return value is not None


def evaluate_claim_packet(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a candidate claim packet without performing promotion.

    Result precedence is deliberately fail-closed:
    malformed/insufficient evidence -> INVALID, explicit test failure -> FAIL,
    source/spec/toolchain/fixture/platform mismatch -> STALE, then BLOCKED,
    then NOT_RUN.  Only an otherwise complete packet can become
    ELIGIBLE_FOR_EXTERNAL_REVIEW, and even then ``product_qualified`` remains false.
    """
    invalid: list[str] = []
    stale: list[str] = []

    if packet.get("schema_version") != 1:
        invalid.append("unsupported_schema_version")
    if not _nonempty(packet.get("profile_id")):
        invalid.append("missing_profile_id")
    expected = packet.get("binding")
    if not isinstance(expected, Mapping):
        invalid.append("missing_binding")
        expected = {}
    for key in _BINDING_KEYS:
        if not _nonempty(expected.get(key)):
            invalid.append(f"binding:missing:{key}")

    required_gates = packet.get("required_gates")
    gate_evidence = packet.get("gate_evidence")
    if not isinstance(required_gates, list) or not required_gates:
        invalid.append("missing_required_gates")
        required_gates = []
    if not isinstance(gate_evidence, Mapping):
        invalid.append("missing_gate_evidence")
        gate_evidence = {}

    statuses: list[str] = []
    for gate in required_gates:
        ev = gate_evidence.get(gate)
        if not isinstance(ev, Mapping):
            invalid.append(f"missing_gate:{gate}")
            continue
        status = ev.get("status")
        if status not in _ALLOWED_STATUSES:
            invalid.append(f"{gate}:unknown_status:{status}")
            continue
        statuses.append(status)
        if not _nonempty(ev.get("artifact_sha256")):
            invalid.append(f"{gate}:missing_artifact_sha256")
        if not _nonempty(ev.get("raw_log_sha256")):
            invalid.append(f"{gate}:missing_raw_log_sha256")
        if not isinstance(ev.get("test_ids"), list) or not ev.get("test_ids"):
            invalid.append(f"{gate}:empty_test_selection")

        observed = ev.get("binding")
        if not isinstance(observed, Mapping):
            invalid.append(f"{gate}:missing_binding")
        else:
            for key in _BINDING_KEYS:
                if observed.get(key) != expected.get(key):
                    stale.append(f"{gate}:binding_mismatch:{key}")

        if status == "NOT_APPLICABLE":
            if ev.get("approved_profile_exclusion") is not True:
                invalid.append(f"{gate}:unapproved_not_applicable")
            if not _nonempty(ev.get("reviewer")):
                invalid.append(f"{gate}:missing_not_applicable_reviewer")

    claims = packet.get("claims")
    if not isinstance(claims, list) or not claims:
        invalid.append("missing_claims")
        claims = []
    for claim in claims:
        if not isinstance(claim, Mapping):
            invalid.append("malformed_claim")
            continue
        cid = claim.get("id") or "<missing-id>"
        if not _nonempty(claim.get("id")):
            invalid.append("claim:missing_id")
        if not _nonempty(claim.get("guarantee")):
            invalid.append(f"claim:{cid}:missing_guarantee")
        refs = claim.get("evidence_refs")
        reqs = claim.get("required_gates")
        if not isinstance(refs, list) or not refs:
            invalid.append(f"claim:{cid}:missing_evidence_refs")
            refs = []
        if not isinstance(reqs, list) or not reqs:
            invalid.append(f"claim:{cid}:missing_required_gates")
            reqs = []
        for ref in refs:
            if ref not in gate_evidence:
                invalid.append(f"claim:{cid}:missing_evidence:{ref}")
        for gate in reqs:
            if gate not in refs:
                invalid.append(f"claim:{cid}:uncovered_gate:{gate}")

    if not isinstance(packet.get("known_risks"), list) or not packet.get("known_risks"):
        invalid.append("missing_known_risks")
    if not _nonempty(packet.get("support_window")):
        invalid.append("missing_support_window")

    base = {
        "product_qualified": False,
        "requires_external_approval": True,
        "errors": invalid + stale,
    }
    if invalid:
        return {"result": "INVALID", **base}
    if "FAIL" in statuses:
        return {"result": "FAIL", **base}
    if stale:
        return {"result": "STALE", **base}
    if "BLOCKED" in statuses:
        return {"result": "BLOCKED", **base}
    if "NOT_RUN" in statuses:
        return {"result": "NOT_RUN", **base}
    return {"result": "ELIGIBLE_FOR_EXTERNAL_REVIEW", **base}


def validate_extension_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Validate that an extension is a bounded contract, never arbitrary code."""
    required = ("capability_id", "version", "threat_model", "resource_class", "test_contract", "migration")
    errors: list[str] = []
    for key in required:
        if not _nonempty(manifest.get(key)):
            errors.append(f"missing:{key}")
    for key in ("execute", "script", "code", "eval", "arbitrary_json"):
        if key in manifest:
            errors.append(f"arbitrary_execution_field:{key}")
    tests = manifest.get("test_contract")
    if "test_contract" in manifest and (not isinstance(tests, list) or not tests):
        errors.append("invalid:test_contract")
    return {"result": "FAIL" if errors else "PASS", "errors": errors}


def classify_scale_evidence(record: Mapping[str, Any]) -> dict[str, Any]:
    """Keep experiments separate from stable supported limits."""
    scope = record.get("scope")
    stable = record.get("stable_guarantee") is True
    if scope == "EXPERIMENT" and stable:
        return {"result": "FAIL", "classification": "INVALID_PROMOTION", "errors": ["experiment_promoted_to_stable"]}
    if scope == "EXPERIMENT":
        return {"result": "PASS", "classification": "EXPERIMENTAL_LIMIT", "errors": []}
    if scope == "QUALIFICATION" and stable:
        return {"result": "PASS", "classification": "QUALIFIED_LIMIT_CANDIDATE", "errors": []}
    return {"result": "FAIL", "classification": "UNCLASSIFIED", "errors": ["unsupported_scale_evidence"]}


def validate_crypto_extension(extension: Mapping[str, Any]) -> dict[str, Any]:
    """Require explicit recovery/migration trade-offs for stronger crypto claims."""
    errors: list[str] = []
    if not _nonempty(extension.get("profile")):
        errors.append("missing:profile")
    claims = extension.get("claims")
    if not isinstance(claims, list) or not claims:
        errors.append("missing:claims")
        claims = []
    if any(x in {"FORWARD_SECRECY", "POST_COMPROMISE_SECURITY"} for x in claims):
        for key in ("recovery_tradeoff", "migration_plan", "archive_key_policy"):
            if not _nonempty(extension.get(key)):
                errors.append(f"missing:{key}")
    return {"result": "FAIL" if errors else "PASS", "errors": errors}
