import copy
import unittest

from product.wp16.claim_closure import (
    evaluate_claim_packet,
    validate_extension_manifest,
    classify_scale_evidence,
    validate_crypto_extension,
)


BINDING = {
    "source_digest": "src-1",
    "spec_digest": "spec-1",
    "toolchain_digest": "tool-1",
    "fixture_digest": "fixture-1",
    "platform_id": "linux-x86_64-test",
}


def evidence(status="PASS", **overrides):
    item = {
        "status": status,
        "binding": dict(BINDING),
        "artifact_sha256": "a" * 64,
        "test_ids": ["AT-X-001"],
        "raw_log_sha256": "b" * 64,
    }
    item.update(overrides)
    return item


def packet():
    return {
        "schema_version": 1,
        "profile_id": "candidate-local",
        "binding": dict(BINDING),
        "required_gates": ["G0", "G1", "G7"],
        "gate_evidence": {
            "G0": evidence(),
            "G1": evidence(),
            "G7": evidence(),
        },
        "claims": [
            {
                "id": "claim-integrity",
                "guarantee": "local integrity",
                "required_gates": ["G0", "G1"],
                "evidence_refs": ["G0", "G1"],
            }
        ],
        "known_risks": ["external qualification not executed"],
        "support_window": "candidate-only",
    }


class ClaimClosureTests(unittest.TestCase):
    def test_all_pass_is_only_eligible_for_external_review(self):
        result = evaluate_claim_packet(packet())
        self.assertEqual(result["result"], "ELIGIBLE_FOR_EXTERNAL_REVIEW")
        self.assertFalse(result["product_qualified"])
        self.assertTrue(result["requires_external_approval"])

    def test_not_run_gate_keeps_candidate(self):
        p = packet(); p["gate_evidence"]["G7"] = evidence("NOT_RUN")
        result = evaluate_claim_packet(p)
        self.assertEqual(result["result"], "NOT_RUN")
        self.assertFalse(result["product_qualified"])

    def test_blocked_gate_keeps_candidate(self):
        p = packet(); p["gate_evidence"]["G1"] = evidence("BLOCKED")
        result = evaluate_claim_packet(p)
        self.assertEqual(result["result"], "BLOCKED")

    def test_fail_dominates_later_blocked(self):
        p = packet(); p["gate_evidence"]["G0"] = evidence("FAIL"); p["gate_evidence"]["G1"] = evidence("BLOCKED")
        result = evaluate_claim_packet(p)
        self.assertEqual(result["result"], "FAIL")

    def test_stale_binding_is_rejected(self):
        p = packet(); p["gate_evidence"]["G1"]["binding"]["source_digest"] = "old-src"
        result = evaluate_claim_packet(p)
        self.assertEqual(result["result"], "STALE")
        self.assertIn("G1:binding_mismatch:source_digest", result["errors"])

    def test_same_filename_style_artifact_without_digest_is_rejected(self):
        p = packet(); del p["gate_evidence"]["G0"]["artifact_sha256"]
        result = evaluate_claim_packet(p)
        self.assertEqual(result["result"], "INVALID")
        self.assertIn("G0:missing_artifact_sha256", result["errors"])

    def test_empty_test_selection_is_not_pass(self):
        p = packet(); p["gate_evidence"]["G0"]["test_ids"] = []
        result = evaluate_claim_packet(p)
        self.assertEqual(result["result"], "INVALID")
        self.assertIn("G0:empty_test_selection", result["errors"])

    def test_missing_required_gate_is_not_silently_ignored(self):
        p = packet(); del p["gate_evidence"]["G1"]
        result = evaluate_claim_packet(p)
        self.assertEqual(result["result"], "INVALID")
        self.assertIn("missing_gate:G1", result["errors"])

    def test_unknown_status_is_invalid(self):
        p = packet(); p["gate_evidence"]["G0"] = evidence("SKIPPED")
        result = evaluate_claim_packet(p)
        self.assertEqual(result["result"], "INVALID")
        self.assertIn("G0:unknown_status:SKIPPED", result["errors"])

    def test_not_applicable_requires_approved_exclusion_and_reviewer(self):
        p = packet(); p["gate_evidence"]["G7"] = evidence("NOT_APPLICABLE")
        result = evaluate_claim_packet(p)
        self.assertEqual(result["result"], "INVALID")
        p["gate_evidence"]["G7"].update({"approved_profile_exclusion": True, "reviewer": "independent-reviewer"})
        result = evaluate_claim_packet(p)
        self.assertEqual(result["result"], "ELIGIBLE_FOR_EXTERNAL_REVIEW")

    def test_claim_cannot_reference_missing_evidence(self):
        p = packet(); p["claims"][0]["evidence_refs"].append("G9")
        result = evaluate_claim_packet(p)
        self.assertEqual(result["result"], "INVALID")
        self.assertIn("claim:claim-integrity:missing_evidence:G9", result["errors"])

    def test_claim_must_cover_its_required_gates(self):
        p = packet(); p["claims"][0]["evidence_refs"] = ["G0"]
        result = evaluate_claim_packet(p)
        self.assertEqual(result["result"], "INVALID")
        self.assertIn("claim:claim-integrity:uncovered_gate:G1", result["errors"])

    def test_support_window_and_known_risks_are_required(self):
        p = packet(); p["known_risks"] = []
        self.assertEqual(evaluate_claim_packet(p)["result"], "INVALID")
        p = packet(); p["support_window"] = ""
        self.assertEqual(evaluate_claim_packet(p)["result"], "INVALID")


class ExtensionContractTests(unittest.TestCase):
    def test_extension_manifest_requires_bounded_contract(self):
        valid = {
            "capability_id": "ext.large-space",
            "version": 1,
            "threat_model": "docs/threats/large-space.md",
            "resource_class": "large",
            "test_contract": ["AT-EXT-LS-001"],
            "migration": "explicit-opt-in",
        }
        self.assertEqual(validate_extension_manifest(valid)["result"], "PASS")
        broken = copy.deepcopy(valid); del broken["test_contract"]
        self.assertEqual(validate_extension_manifest(broken)["result"], "FAIL")

    def test_arbitrary_executable_json_extension_is_rejected(self):
        manifest = {
            "capability_id": "ext.exec-anything", "version": 1,
            "threat_model": "x", "resource_class": "small",
            "test_contract": ["AT-X"], "migration": "none",
            "execute": {"language": "js", "code": "doAnything()"},
        }
        result = validate_extension_manifest(manifest)
        self.assertEqual(result["result"], "FAIL")
        self.assertIn("arbitrary_execution_field:execute", result["errors"])

    def test_scale_experiment_is_not_stable_guarantee(self):
        result = classify_scale_evidence({"scope": "EXPERIMENT", "peers": 1000, "stable_guarantee": True})
        self.assertEqual(result["result"], "FAIL")
        ok = classify_scale_evidence({"scope": "EXPERIMENT", "peers": 1000, "stable_guarantee": False})
        self.assertEqual(ok["result"], "PASS")
        self.assertEqual(ok["classification"], "EXPERIMENTAL_LIMIT")

    def test_forward_secrecy_crypto_extension_requires_recovery_tradeoff_and_migration(self):
        result = validate_crypto_extension({"profile": "mls", "claims": ["FORWARD_SECRECY"]})
        self.assertEqual(result["result"], "FAIL")
        result = validate_crypto_extension({
            "profile": "mls",
            "claims": ["FORWARD_SECRECY"],
            "recovery_tradeoff": "archive keys reduce FS for retained history",
            "migration_plan": "versioned opt-in migration",
            "archive_key_policy": "explicit retention window",
        })
        self.assertEqual(result["result"], "PASS")


if __name__ == "__main__":
    unittest.main()

class CurrentRepositoryBoundaryTests(unittest.TestCase):
    def test_current_product_state_remains_unqualified(self):
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parents[3]
        state = json.loads((root / "plan/product-state.json").read_text())
        self.assertEqual(state["qualified_profiles"], [])
        self.assertEqual(set(state["gates"].values()), {"NOT_RUN"})
        self.assertEqual(state["native_runtime"], "NOT_STARTED")

    def test_current_not_run_gate_summary_cannot_be_promoted(self):
        p = packet()
        for gate in list(p["gate_evidence"]):
            p["gate_evidence"][gate] = evidence("NOT_RUN")
        result = evaluate_claim_packet(p)
        self.assertEqual(result["result"], "NOT_RUN")
        self.assertFalse(result["product_qualified"])
