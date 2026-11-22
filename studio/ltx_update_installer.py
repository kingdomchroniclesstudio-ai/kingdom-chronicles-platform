from __future__ import annotations

"""Dry-run LTX integration planning and isolated in-memory rollback tests only."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Any

DEFAULT_POLICY = {
    "automatic_install": False,
    "auto_register_compatible_workflows": True,
    "production_adapter_configured": False,
    "require_environment_fingerprint_match": True,
    "require_workflow_test_evidence": True,
    "target_environment": "GPU_COMFYUI_ONLY",
}

class IntegrationBlocked(RuntimeError):
    """An integration plan has not satisfied its explicit safety gates."""

def _event(events: list[dict[str, Any]], kind: str, message: str, details: dict[str, Any] | None = None) -> None:
    events.append({"type": kind, "message": message, "details": details or {}})

def build_integration_plan(candidate: dict[str, Any], environment: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a read-only integration plan bound to exact source/version/test evidence."""
    rules = {**DEFAULT_POLICY, **(policy or {})}
    candidate_id = str(candidate.get("id") or "").strip()
    source = str(candidate.get("source") or "").strip()
    version = candidate.get("version")
    name = str(candidate.get("name") or source or "LTX update")
    compatibility = candidate.get("compatibility") if isinstance(candidate.get("compatibility"), dict) else {}
    evidence = compatibility.get("evidence") if isinstance(compatibility.get("evidence"), dict) else {}
    env_fp = str(environment.get("environment_fingerprint") or "").strip()
    reason = None
    if not candidate_id or not source or not version:
        reason = "The candidate is missing its stable ID, source or version/revision."
    elif compatibility.get("status") != "COMPATIBLE":
        reason = "Only an update classified COMPATIBLE can enter the integration planner."
    elif environment.get("status") != "CONNECTED" or not env_fp:
        reason = "A connected production ComfyUI/GPU inventory and fingerprint are required."
    elif evidence.get("type") != "WORKFLOW_TEST" or evidence.get("workflow_test_passed") is not True:
        reason = "A successful version-pinned workflow test is required; metadata or download success is insufficient."
    elif evidence.get("source") != source or evidence.get("version") != version:
        reason = "The compatibility evidence does not match this exact candidate source and version."
    elif rules["require_environment_fingerprint_match"] and evidence.get("environment_fingerprint") != env_fp:
        reason = "The compatibility evidence does not match the current ComfyUI/LTX/GPU fingerprint."

    if reason:
        return {
            "candidate_id": candidate_id, "name": name, "source": source, "version": version,
            "status": "BLOCKED", "operation": "NONE", "approval_required": True,
            "automatic_eligible": False, "automatic_execution_enabled": False,
            "production_execution_enabled": False, "environment_fingerprint": env_fp or None,
            "reason": reason, "stages": [], "automatic_install_blockers": [],
            "rollback": "No production state was touched.",
        }

    requirements = candidate.get("installation_requirements")
    requirements = requirements if isinstance(requirements, dict) else {}
    required_nodes = sorted({str(x) for x in candidate.get("required_node_classes", [])})
    required_assets = sorted({str(x) for x in candidate.get("referenced_model_assets", [])})
    risk = str(candidate.get("risk_class") or "UNCLASSIFIED")
    low_risk = source == "comfyui_ltx25_workflows" and risk == "WORKFLOW_GRAPH_REVIEW"
    if low_risk:
        operation = "REGISTER_WORKFLOW"
        stages = ["BACKUP_CURRENT_WORKFLOW_REGISTRY", "STAGE_WORKFLOW_JSON", "REGISTER_NEW_WORKFLOW", "RUN_WORKFLOW_COMPATIBILITY_TESTS", "RECORD_CAPABILITY_AFTER_TEST"]
    elif requirements.get("estimated_download_bytes"):
        operation = "DOWNLOAD_AND_INSTALL_ASSETS"
        stages = ["DIRECTOR_APPROVAL", "BACKUP_MODEL_AND_WORKFLOW_CONFIGURATION", "DOWNLOAD_ASSETS_TO_GPU_STORAGE", "VERIFY_FILE_HASHES_AND_LICENSE", "INSTALL_ASSETS", "REGISTER_WORKFLOW", "RUN_WORKFLOW_COMPATIBILITY_TESTS"]
    else:
        operation = "INSTALL_OR_UPDATE_COMPONENT"
        stages = ["DIRECTOR_APPROVAL", "BACKUP_CURRENT_CONFIGURATION", "STAGE_IN_ISOLATED_ENVIRONMENT", "INSTALL_COMPONENT", "REGISTER_WORKFLOW", "RUN_WORKFLOW_COMPATIBILITY_TESTS"]

    eligible = bool(low_risk and rules["auto_register_compatible_workflows"] and not requirements.get("license") and not requirements.get("gated_asset"))
    enabled = bool(eligible and rules["automatic_install"] and rules["production_adapter_configured"])
    blockers = []
    if not rules["automatic_install"]:
        blockers.append("automatic installation is disabled by policy")
    if not rules["production_adapter_configured"]:
        blockers.append("no audited production ComfyUI/GPU adapter is configured")
    if not eligible:
        blockers.append("candidate is outside the low-risk workflow-registration allowlist")
    if requirements.get("license_review") == "DIRECTOR_REVIEW_REQUIRED":
        blockers.append("licensing requires Director review")
    if requirements.get("storage_preflight") == "INSUFFICIENT_FOR_DOWNLOAD":
        blockers.append("recorded persistent storage is insufficient")
    if requirements.get("storage_preflight") in {"UNKNOWN", "UNKNOWN_NO_CONNECTED_STORAGE_INVENTORY"}:
        blockers.append("persistent storage preflight is unknown")

    return {
        "candidate_id": candidate_id, "name": name, "source": source, "version": version,
        "status": "READY_FOR_DIRECTOR_REVIEW" if not enabled else "AUTOMATIC_LOW_RISK_ELIGIBLE",
        "operation": operation, "risk_class": risk, "approval_required": not enabled,
        "automatic_eligible": eligible, "automatic_execution_enabled": enabled,
        "production_execution_enabled": False, "target_environment": "GPU_COMFYUI_ONLY",
        "environment_fingerprint": env_fp, "compatibility_evidence": deepcopy(evidence),
        "required_node_classes": required_nodes, "referenced_model_assets": required_assets,
        "estimated_download_bytes": requirements.get("estimated_download_bytes"),
        "license_review": requirements.get("license_review", "NOT_CAPTURED"),
        "stages": stages, "automatic_install_blockers": blockers,
        "reason": "This is a non-mutating plan based on matching workflow-test evidence. It does not authorize or execute a production change.",
        "rollback": "Create and checksum-verify an immutable backup before mutation. If registration or tests fail, restore the previous registry/configuration and verify its checksum.",
    }

@dataclass
class MockComfyUIAdapter:
    """In-memory adapter; cannot access a real ComfyUI server, model files or GPU."""
    fail_at: str | None = None
    def __post_init__(self) -> None:
        self.is_mock = True
        self.state: dict[str, Any] = {"workflows": {}, "components": {}}
        self.backups: dict[str, dict[str, Any]] = {}
        self.counter = 0
    def create_backup(self) -> dict[str, Any]:
        if self.fail_at == "backup":
            return {"verified": False, "reason": "simulated backup checksum failure"}
        self.counter += 1
        backup_id = f"MOCK-BACKUP-{self.counter:04d}"
        snap = deepcopy(self.state)
        checksum = hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest()
        self.backups[backup_id] = {"snapshot": snap, "sha256": checksum}
        return {"backup_id": backup_id, "sha256": checksum, "verified": True}
    def stage_workflow(self, plan: dict[str, Any]) -> dict[str, Any]:
        if self.fail_at == "stage":
            raise RuntimeError("simulated staging failure")
        return {"candidate_id": plan["candidate_id"], "source": plan["source"], "version": plan["version"], "environment_fingerprint": plan["environment_fingerprint"]}
    def register_workflow(self, staged: dict[str, Any]) -> None:
        if self.fail_at == "register":
            raise RuntimeError("simulated registration failure")
        self.state["workflows"][staged["candidate_id"]] = deepcopy(staged)
    def run_workflow_tests(self, plan: dict[str, Any]) -> bool:
        return self.fail_at != "test" and plan.get("operation") == "REGISTER_WORKFLOW"
    def rollback(self, backup_id: str) -> dict[str, Any]:
        backup = self.backups.get(backup_id)
        if not backup or self.fail_at == "rollback":
            return {"restored": False, "verified": False, "reason": "simulated rollback unavailable"}
        snap = deepcopy(backup["snapshot"])
        checksum = hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest()
        if checksum != backup["sha256"]:
            return {"restored": False, "verified": False, "reason": "backup checksum mismatch"}
        self.state = snap
        return {"restored": True, "verified": True, "sha256": checksum}

def run_mock_integration(plan: dict[str, Any], adapter: MockComfyUIAdapter, approval: dict[str, Any] | None = None) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    if not isinstance(adapter, MockComfyUIAdapter) or not getattr(adapter, "is_mock", False):
        raise IntegrationBlocked("Only the isolated in-memory mock adapter is implemented in this release.")
    if plan.get("status") == "BLOCKED":
        raise IntegrationBlocked(str(plan.get("reason") or "The plan is blocked."))
    if plan.get("operation") != "REGISTER_WORKFLOW":
        raise IntegrationBlocked("Model downloads and software/node installations are not supported by this mock transaction.")
    if plan.get("production_execution_enabled"):
        raise IntegrationBlocked("The mock harness refuses production execution.")
    if plan.get("approval_required"):
        if not isinstance(approval, dict) or approval.get("decision") != "APPROVED" or approval.get("candidate_id") != plan.get("candidate_id") or approval.get("environment_fingerprint") != plan.get("environment_fingerprint") or not str(approval.get("approved_by") or "").strip() or not str(approval.get("approved_at") or "").strip():
            raise IntegrationBlocked("Approval must bind the exact candidate, environment fingerprint, Director and approval timestamp.")
    _event(events, "UPDATE_APPROVED", "Mock-only transaction authorised for an isolated test.", {"candidate_id": plan["candidate_id"]})
    _event(events, "COMPATIBILITY_CHECK_IN_PROGRESS", "Checking environment-bound workflow evidence.")
    backup = adapter.create_backup()
    if backup.get("verified") is not True or not backup.get("backup_id") or not backup.get("sha256"):
        _event(events, "UPDATE_FAILED", "Backup verification failed; no mutation performed.", backup)
        return {"status": "FAILED_BEFORE_MUTATION", "production_verified": False, "backup": backup, "events": events}
    _event(events, "BACKUP_CREATED_AND_VERIFIED", "Mock pre-change backup checksum verified.", backup)
    try:
        _event(events, "REGISTERING_NEW_WORKFLOW", "Staging workflow metadata in the in-memory mock registry.")
        staged = adapter.stage_workflow(plan)
        adapter.register_workflow(staged)
        _event(events, "RUNNING_COMPATIBILITY_TESTS", "Running simulated workflow acceptance check.")
        if adapter.run_workflow_tests(plan) is not True:
            raise RuntimeError("simulated workflow test failed")
        _event(events, "MOCK_INTEGRATION_TEST_PASSED", "Mock registration passed; no production capability installed or verified.")
        return {"status": "MOCK_INTEGRATION_TEST_PASSED", "production_verified": False, "capability_status": "NOT_VERIFIED", "backup": backup, "events": events}
    except Exception as exc:
        _event(events, "UPDATE_FAILED_ROLLBACK_INITIATED", f"Mock transaction failed: {type(exc).__name__}: {exc}")
        rollback = adapter.rollback(backup["backup_id"])
        if rollback.get("restored") is True and rollback.get("verified") is True:
            _event(events, "ROLLBACK_COMPLETED", "Previous mock registry restored and checksum verified.", rollback)
            status = "ROLLED_BACK"
        else:
            _event(events, "ROLLBACK_FAILED", "Mock restore could not be verified; manual recovery would be required.", rollback)
            status = "ROLLBACK_FAILED"
        return {"status": status, "production_verified": False, "capability_status": "NOT_VERIFIED", "backup": backup, "rollback": rollback, "events": events}

def execute_integration_plan(*args: Any, **kwargs: Any) -> dict[str, Any]:
    raise IntegrationBlocked("Production integration is disabled. This phase supports dry-run planning and mock rollback tests only; no download, ComfyUI mutation or GPU job can be started.")
