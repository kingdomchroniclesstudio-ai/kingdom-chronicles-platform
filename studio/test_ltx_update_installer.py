from __future__ import annotations
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ltx_update_installer import DEFAULT_POLICY, IntegrationBlocked, MockComfyUIAdapter, build_integration_plan, execute_integration_plan, run_mock_integration

def candidate():
    return {
        "id": "candidate-123", "source": "comfyui_ltx25_workflows",
        "name": "Official LTX-2.5 workflow graph", "version": "graph-fingerprint-v1",
        "risk_class": "WORKFLOW_GRAPH_REVIEW",
        "compatibility": {"status": "COMPATIBLE", "evidence": {
            "type": "WORKFLOW_TEST", "source": "comfyui_ltx25_workflows", "version": "graph-fingerprint-v1",
            "workflow_id": "L25-T2V", "tested_at": "2026-11-22T12:00:00Z",
            "environment_fingerprint": "env-fingerprint-001", "workflow_test_passed": True}},
        "required_node_classes": ["LTXVBaseSampler"],
        "referenced_model_assets": ["ltx-2.5-video.safetensors"],
        "installation_requirements": {"estimated_download_bytes": None, "license_review": "NOT_CAPTURED", "storage_preflight": "NOT_APPLICABLE_OR_SIZE_UNKNOWN"}
    }

def environment():
    return {"status": "CONNECTED", "environment_fingerprint": "env-fingerprint-001"}

def approval_for(plan):
    return {"decision": "APPROVED", "candidate_id": plan["candidate_id"], "environment_fingerprint": plan["environment_fingerprint"], "approved_by": "Director", "approved_at": "2026-11-22T12:00:00Z"}

class LTXIntegrationPlannerTests(unittest.TestCase):
    def test_noncompatible_candidate_is_blocked(self):
        item = candidate(); item["compatibility"]["status"] = "REQUIRES_MANUAL_APPROVAL"
        plan = build_integration_plan(item, environment())
        self.assertEqual(plan["status"], "BLOCKED"); self.assertEqual(plan["operation"], "NONE")
    def test_environment_and_version_evidence_must_match(self):
        item = candidate()
        self.assertEqual(build_integration_plan(item, {"status": "NOT_CONNECTED"})["status"], "BLOCKED")
        self.assertEqual(build_integration_plan(item, {"status": "CONNECTED", "environment_fingerprint": "other-env"})["status"], "BLOCKED")
        item["compatibility"]["evidence"]["version"] = "old"
        self.assertEqual(build_integration_plan(item, environment())["status"], "BLOCKED")
    def test_workflow_plan_is_low_risk_but_manual_by_default(self):
        plan = build_integration_plan(candidate(), environment())
        self.assertEqual(plan["operation"], "REGISTER_WORKFLOW")
        self.assertTrue(plan["automatic_eligible"]); self.assertTrue(plan["approval_required"])
        self.assertFalse(plan["automatic_execution_enabled"]); self.assertFalse(plan["production_execution_enabled"])
    def test_auto_policy_still_requires_production_adapter(self):
        policy = {**DEFAULT_POLICY, "automatic_install": True, "production_adapter_configured": False}
        plan = build_integration_plan(candidate(), environment(), policy)
        self.assertTrue(plan["automatic_eligible"]); self.assertTrue(plan["approval_required"])
        self.assertIn("no audited production ComfyUI/GPU adapter is configured", plan["automatic_install_blockers"])
    def test_model_asset_downloads_never_enter_low_risk_auto_path(self):
        item = candidate(); item["source"] = "hf_ltx25_comfyui_stack"; item["risk_class"] = "MODEL_ASSET_AND_LICENSE_REVIEW"
        item["installation_requirements"] = {"estimated_download_bytes": 15_000_000_000, "license": "ltx-license", "license_review": "DIRECTOR_REVIEW_REQUIRED", "storage_preflight": "SUFFICIENT_FOR_DOWNLOAD_ONLY"}
        plan = build_integration_plan(item, environment(), {**DEFAULT_POLICY, "automatic_install": True, "production_adapter_configured": True})
        self.assertEqual(plan["operation"], "DOWNLOAD_AND_INSTALL_ASSETS")
        self.assertFalse(plan["automatic_eligible"]); self.assertTrue(plan["approval_required"])
    def test_mock_success_never_marks_production_verified(self):
        plan = build_integration_plan(candidate(), environment()); adapter = MockComfyUIAdapter()
        with self.assertRaises(IntegrationBlocked): run_mock_integration(plan, adapter)
        result = run_mock_integration(plan, adapter, approval_for(plan))
        self.assertEqual(result["status"], "MOCK_INTEGRATION_TEST_PASSED")
        self.assertFalse(result["production_verified"]); self.assertEqual(result["capability_status"], "NOT_VERIFIED")
    def test_failed_workflow_test_rolls_back(self):
        plan = build_integration_plan(candidate(), environment()); adapter = MockComfyUIAdapter(fail_at="test")
        result = run_mock_integration(plan, adapter, approval_for(plan))
        self.assertEqual(result["status"], "ROLLED_BACK")
        self.assertFalse(result["production_verified"]); self.assertNotIn(plan["candidate_id"], adapter.state["workflows"])
        kinds = [event["type"] for event in result["events"]]
        self.assertIn("UPDATE_FAILED_ROLLBACK_INITIATED", kinds); self.assertIn("ROLLBACK_COMPLETED", kinds)
    def test_backup_failure_stops_before_mutation(self):
        plan = build_integration_plan(candidate(), environment()); adapter = MockComfyUIAdapter(fail_at="backup")
        result = run_mock_integration(plan, adapter, approval_for(plan))
        self.assertEqual(result["status"], "FAILED_BEFORE_MUTATION"); self.assertEqual(adapter.state["workflows"], {})
    def test_production_execution_is_disabled(self):
        with self.assertRaises(IntegrationBlocked): execute_integration_plan({})

if __name__ == "__main__":
    unittest.main()
