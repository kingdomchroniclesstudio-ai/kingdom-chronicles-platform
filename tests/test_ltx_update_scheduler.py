from __future__ import annotations

import json
import io
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ltx_update_scheduled_check as manager


class FakeResponse:
    def __init__(self, body: bytes, content_type: str = "application/json"):
        self.body = body
        self.headers = {"Content-Type": content_type}
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, size=-1): return self.body if size < 0 else self.body[:size]


def fake_upstream(release="v1.6.2", node_release="v1.1.1", revision="abc123", docs="docs-one"):
    def opener(request, timeout=10):
        url = getattr(request, "full_url", str(request))
        if url.endswith("LTX-2/releases/latest"):
            return FakeResponse(json.dumps({"tag_name": release, "published_at": "2026-11-12T14:28:42Z", "html_url": f"https://github.com/Lightricks/LTX-2/releases/tag/{release}", "body": "test release notes"}).encode())
        if url.endswith("ComfyUI-LTXVideo/releases/latest"):
            return FakeResponse(json.dumps({"tag_name": node_release, "published_at": "2026-11-12T14:15:29Z", "html_url": f"https://github.com/Lightricks/ComfyUI-LTXVideo/releases/tag/{node_release}", "body": "nodes updated"}).encode())
        if "raw.githubusercontent.com/Lightricks/ComfyUI-LTXVideo/master/example_workflows/2.5/" in url:
            graph = {"nodes": [
                {"type": "LTXVBaseSampler", "widgets_values": ["ltx-2.5-video.safetensors"]},
                {"class_type": "LTXVImgToVideo", "inputs": {"model": "ltx-2.5-distilled.safetensors"}},
                {"type": "LTXVTemporalUpscale", "widgets_values": []}
            ]}
            return FakeResponse(json.dumps(graph).encode(), "application/json")
        if "example_workflows/2.5" in url:
            return FakeResponse(json.dumps([{"name": "LTX-2.5_T2V.json", "path": "example_workflows/2.5/LTX-2.5_T2V.json", "sha": "file-sha", "type": "file"}]).encode())
        if "LTX-2.5-Diffusers" in url:
            return FakeResponse(json.dumps({"id": "Lightricks/LTX-2.5-Diffusers", "sha": revision, "lastModified": "2026-11-20T00:00:00Z", "siblings": [{"rfilename": "model.safetensors", "size": 1024, "lfs": {"oid": "file-hash", "size": 1024}}]}).encode())
        if "api/models/Lightricks/LTX-2.5?" in url:
            return FakeResponse(json.dumps({"id": "Lightricks/LTX-2.5", "sha": "main-sha", "lastModified": "2026-11-20T00:00:00Z", "license": "ltx-2.x-community-license-agreement", "siblings": [{"rfilename": "diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors", "size": 1000, "lfs": {"oid": "transformer-hash", "size": 1000}}, {"rfilename": "vae/ltx-2.5-video-vae-bf16.safetensors", "size": 200, "lfs": {"oid": "vae-hash", "size": 200}}, {"rfilename": "text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors", "size": 250, "lfs": {"oid": "gemma-encoder-hash", "size": 250}}]}).encode())
        if "Pixel-Spatial-Upscaler" in url:
            return FakeResponse(json.dumps({"id": "Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler", "sha": "lora-sha", "lastModified": "2026-11-20T00:00:00Z", "siblings": [{"rfilename": "ltx-pixel-spatial-upscaler.safetensors", "size": 300, "lfs": {"oid": "lora-file-hash", "size": 300}}]}).encode())
        if "Comfy-Org/gemma-4" in url:
            return FakeResponse(json.dumps({"id": "Comfy-Org/gemma-4", "sha": "gemma-sha", "lastModified": "2026-11-20T00:00:00Z", "siblings": [{"rfilename": "gemma4_e2b_it_bf16.safetensors", "size": 400, "lfs": {"oid": "gemma-file-hash", "size": 400}}]}).encode())
        if "api/models?author=Lightricks" in url:
            return FakeResponse(json.dumps([{"id": "Lightricks/LTX-2.5-22b-IC-LoRA-Refine-Details", "sha": "lora-sha", "lastModified": "2026-11-20T00:00:00Z", "tags": ["safetensors"]}]).encode())
        return FakeResponse((docs + " LTX-2.5 Gemma 4 prompt enhancer tiled fusion HDR IC-LoRA").encode(), "text/html" if url.startswith("https://docs.") else "text/plain")
    return opener


def connected_inventory(installed_sources=None, compatibility_results=None):
    raw = {
        "schema_version": 1,
        "status": "CONNECTED",
        "observed_at": "2026-11-22T12:00:00Z",
        "comfyui": {"version": "0.44.0", "commit": "comfy-commit"},
        "runtime": {"python_version": "3.11.9", "pytorch_version": "2.7.1", "cuda_version": "12.8"},
        "gpu": {"model": "NVIDIA RTX 5090", "vram_total_gib": 32.0, "driver_version": "NOT_RECORDED"},
        "storage": {"persistent_mount_configured": True, "available_bytes": 100_000_000_000, "mount_label": "GPU_DATA"},
        "ltx": {"primary_model": "LTX-2.5", "model_revision": "ltx25-abc"},
        "custom_nodes": [{"name": "ComfyUI-LTXVideo", "repository": "https://github.com/Lightricks/ComfyUI-LTXVideo", "version": "v1.1.1", "commit": "nodes-abc", "license": "Other", "node_classes": ["LTXVBaseSampler", "LTXVImgToVideo"]}],
        "installed_node_classes": ["LTXVBaseSampler", "LTXVImgToVideo"],
        "installed_sources": installed_sources or {},
        "installed_assets": [{"repo_id": "Lightricks/LTX-2.5", "revision": "ltx25-abc", "filename": "transformer.safetensors", "size_bytes": 1000, "sha256_or_lfs_oid": "asset-hash", "license": "ltx-2.x-community-license-agreement", "gated": False}],
        "compatibility_results": compatibility_results or [],
    }
    return raw


class ScheduledMonitorTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)

    def test_activation_surfaces_updates_since_existing_approved_baselines(self):
        with patch.object(manager.urllib.request, "urlopen", side_effect=fake_upstream()):
            state = manager.monitor_once(interval_hours=6, timeout=1, force=True, now=self.now)
        self.assertEqual(state["successful_source_count"], len(manager.SOURCES))
        self.assertEqual(state["failed_source_count"], 0)
        self.assertEqual({item["source"] for item in state["candidates"]}, {"ltx_core_release", "comfyui_ltxvideo_release", "hf_ltx25_diffusers"})
        self.assertEqual(len(state["notifications"]), 6)
        self.assertEqual(len(state["source_observations"]), len(manager.SOURCES))
        self.assertFalse(state["safety"]["automatic_install"])
        detected = state["capabilities"]["detected"]
        self.assertTrue(any(item["name"] == "prompt_enhancement" for item in detected))
        self.assertTrue(any(item["name"] == "tiled_fusion" for item in detected))
        self.assertTrue(all(item["installation_status"] == "UNKNOWN" for item in detected))
        hosted = [item for item in detected if item["source"] == "ltx_api_changelog_docs"]
        self.assertTrue(all(item["scope"] == "HOSTED_API_ONLY" for item in hosted))

    def test_simulated_release_revision_and_docs_changes_create_candidates(self):
        with patch.object(manager.urllib.request, "urlopen", side_effect=fake_upstream()):
            baseline = manager.monitor_once(interval_hours=6, timeout=1, force=True, now=self.now)
        with patch.object(manager.urllib.request, "urlopen", side_effect=fake_upstream(release="v1.6.3", revision="def456", docs="docs-two")):
            changed = manager.monitor_once(baseline, interval_hours=6, timeout=1, force=True, now=self.now + timedelta(hours=6))
        sources = {item["source"] for item in changed["candidates"]}
        self.assertIn("ltx_core_release", sources)
        self.assertIn("hf_ltx25_diffusers", sources)
        self.assertIn("ltx_open_source_comfyui_docs", sources)
        self.assertTrue(all(item["compatibility"]["status"] == "REQUIRES_MANUAL_APPROVAL" for item in changed["candidates"]))
        self.assertTrue(all(item["installation_status"] == "NOT_INSTALLED" for item in changed["candidates"]))

    def test_huggingface_asset_manifest_tracks_names_sizes_and_lfs_hashes(self):
        with patch.object(manager.urllib.request, "urlopen", side_effect=fake_upstream()):
            observed = manager.observe("hf_ltx25_comfyui_stack", manager.SOURCES["hf_ltx25_comfyui_stack"], 1)
        self.assertEqual(observed["status"], "OBSERVED")
        files = observed["metadata"]["files"]
        self.assertTrue(any(item["name"].endswith("distilled-transformer-bf16.safetensors") for item in files))
        self.assertTrue(any(item["sha256_or_lfs_oid"] == "transformer-hash" for item in files))
        self.assertIn("gemma4_text_encoder", observed["feature_tags"])
        self.assertNotIn("model.safetensors", [item["name"] for item in files])

    def test_feature_scanner_reads_full_document_beyond_the_dashboard_excerpt(self):
        body = ("introductory documentation " * 30) + " Native 4K 8K Tiled Fusion HDR character consistency."
        with patch.object(manager.urllib.request, "urlopen", return_value=FakeResponse(body.encode(), "text/html")):
            observed = manager.observe("ltx_open_source_comfyui_docs", manager.SOURCES["ltx_open_source_comfyui_docs"], 1)
        self.assertEqual(len(observed["summary"]), 480)
        self.assertIn("native_resolution", observed["feature_tags"])
        self.assertIn("tiled_fusion", observed["feature_tags"])
        self.assertIn("hdr", observed["feature_tags"])
        self.assertIn("consistency", observed["feature_tags"])

    def test_official_workflow_graph_parser_extracts_nodes_and_model_refs(self):
        with patch.object(manager.urllib.request, "urlopen", side_effect=fake_upstream()):
            observed = manager.observe("comfyui_ltx25_workflows", manager.SOURCES["comfyui_ltx25_workflows"], 1)
        self.assertEqual(observed["status"], "OBSERVED")
        self.assertIn("LTXVBaseSampler", observed["required_node_classes"])
        self.assertIn("LTXVImgToVideo", observed["required_node_classes"])
        self.assertIn("LTXVTemporalUpscale", observed["required_node_classes"])
        self.assertIn("ltx-2.5-video.safetensors", observed["referenced_model_assets"])
        self.assertIn("ltx-2.5-distilled.safetensors", observed["referenced_model_assets"])
        graph_entry = observed["metadata"][0]
        self.assertIn("node_classes", graph_entry)
        self.assertIn("model_refs", graph_entry)

    def test_missing_required_workflow_node_is_incompatible(self):
        inventory = manager.validate_environment_inventory(connected_inventory())
        result = manager.classify_compatibility({
            "source": "comfyui_ltxvideo_release",
            "version": "v1.1.2",
            "required_node_classes": ["LTXVBaseSampler", "LTXVTemporalUpscale"],
        }, inventory)
        self.assertEqual(result["status"], "INCOMPATIBLE")
        self.assertIn("LTXVTemporalUpscale", result["reason"])

    def test_missing_official_workflow_node_class_is_incompatible(self):
        inventory = manager.validate_environment_inventory(connected_inventory())
        observed = manager.observe("comfyui_ltx25_workflows", manager.SOURCES["comfyui_ltx25_workflows"], 1)
        candidate = {
            "source": "comfyui_ltxvideo_release",
            "version": "v1.1.2",
            "required_node_classes": observed["required_node_classes"],
        }
        result = manager.classify_compatibility(candidate, inventory)
        self.assertEqual(result["status"], "INCOMPATIBLE")
        self.assertIn("LTXVTemporalUpscale", result["reason"])
        self.assertIn("LTXVTemporalUpscale", observed["required_node_classes"])

    def test_interval_skips_runs_until_due(self):
        initial = manager.initial_state(6)
        initial["last_successful_check_at"] = manager.stamp(self.now)
        with patch.object(manager.urllib.request, "urlopen", side_effect=AssertionError("network should not be called")):
            skipped = manager.monitor_once(initial, interval_hours=6, now=self.now + timedelta(hours=3))
        self.assertTrue(skipped["skipped"])
        self.assertEqual(skipped["next_check_due_at"], manager.stamp(self.now + timedelta(hours=6)))

    def test_partial_scan_retry_timestamp_overrides_full_interval_gate(self):
        retry_state = manager.initial_state(6)
        retry_state["last_successful_check_at"] = manager.stamp(self.now - timedelta(hours=3))
        retry_state["next_check_due_at"] = manager.stamp(self.now - timedelta(minutes=1))
        retry_state["schedule"]["interval_hours"] = 6
        with patch.object(manager.urllib.request, "urlopen", side_effect=TimeoutError("simulated source outage")):
            updated = manager.monitor_once(retry_state, interval_hours=6, timeout=1, force=False, now=self.now)
        self.assertFalse(updated.get("skipped", False))
        self.assertEqual(updated["failed_source_count"], len(manager.SOURCES))
        self.assertEqual(updated["next_check_due_at"], manager.stamp(self.now + timedelta(hours=1)))

    def test_inventory_only_marks_exact_revision_already_installed(self):
        candidate = {"source": "ltx_core_release", "version": "v1.6.2"}
        self.assertEqual(manager.classify_compatibility(candidate, None)["status"], "REQUIRES_MANUAL_APPROVAL")
        inventory = connected_inventory(installed_sources={"ltx_core_release": "v1.6.2"})
        self.assertEqual(manager.classify_compatibility(candidate, inventory)["status"], "ALREADY_INSTALLED")

    def test_compatibility_and_incompatibility_require_matching_test_and_environment_fingerprint(self):
        candidate = {"source": "comfyui_ltxvideo_release", "version": "v1.1.2"}
        inventory = manager.validate_environment_inventory(connected_inventory())
        fingerprint = inventory["environment_fingerprint"]
        inventory["compatibility_results"] = [
            {"source": candidate["source"], "version": candidate["version"], "environment_fingerprint": "different-stack",
             "result": "COMPATIBLE", "workflow_test_passed": True, "reason": "Prior stack passed.",
             "workflow_id": "L25-T2V", "tested_at": "2026-11-22T12:00:00Z"}
        ]
        self.assertEqual(manager.classify_compatibility(candidate, inventory)["status"], "REQUIRES_MANUAL_APPROVAL")
        inventory["compatibility_results"][0]["environment_fingerprint"] = fingerprint
        self.assertEqual(manager.classify_compatibility(candidate, inventory)["status"], "COMPATIBLE")
        inventory["compatibility_results"][0]["result"] = "INCOMPATIBLE"
        inventory["compatibility_results"][0]["reason"] = "Required node missing."
        self.assertEqual(manager.classify_compatibility(candidate, inventory)["status"], "INCOMPATIBLE")

    def test_connected_inventory_requires_ltx25_gpu_comfyui_and_persistent_storage(self):
        raw = connected_inventory()
        normalized = manager.validate_environment_inventory(raw)
        self.assertEqual(normalized["status"], "CONNECTED")
        self.assertEqual(normalized["environment_fingerprint"], manager.environment_fingerprint(normalized))
        invalid = connected_inventory()
        invalid["ltx"]["primary_model"] = "LTX-2.3"
        with self.assertRaises(ValueError):
            manager.validate_environment_inventory(invalid)
        invalid = connected_inventory()
        invalid["storage"]["persistent_mount_configured"] = False
        with self.assertRaises(ValueError):
            manager.validate_environment_inventory(invalid)
        invalid = connected_inventory()
        invalid["api_key"] = "should-never-be-accepted"
        with self.assertRaises(ValueError):
            manager.validate_environment_inventory(invalid)

    def test_environment_fingerprint_ignores_free_space_but_tracks_node_and_gpu_versions(self):
        raw = connected_inventory()
        baseline = manager.environment_fingerprint(manager.validate_environment_inventory(raw))
        changed_space = connected_inventory()
        changed_space["storage"]["available_bytes"] = 50_000_000_000
        self.assertEqual(baseline, manager.environment_fingerprint(manager.validate_environment_inventory(changed_space)))
        changed_nodes = connected_inventory()
        changed_nodes["custom_nodes"][0]["node_classes"].append("LTXVTemporalUpscale")
        changed_nodes["installed_node_classes"].append("LTXVTemporalUpscale")
        self.assertNotEqual(baseline, manager.environment_fingerprint(manager.validate_environment_inventory(changed_nodes)))
        changed_gpu = connected_inventory()
        changed_gpu["gpu"]["driver_version"] = "new-driver"
        self.assertNotEqual(baseline, manager.environment_fingerprint(manager.validate_environment_inventory(changed_gpu)))

    def test_inventory_reader_accepts_not_connected_state_and_rejects_invalid_json(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "inventory.json"
            path.write_text(json.dumps({"schema_version": 1, "status": "NOT_CONNECTED"}), encoding="utf-8")
            self.assertEqual(manager.read_inventory(path)["status"], "NOT_CONNECTED")
            path.write_text("{bad", encoding="utf-8")
            with self.assertRaises(ValueError):
                manager.read_inventory(path)

    def test_inventory_fingerprint_mismatch_invalidates_environment_evidence(self):
        raw = connected_inventory()
        raw["environment_fingerprint"] = "stale-or-tampered-fingerprint"
        with self.assertRaises(ValueError):
            manager.validate_environment_inventory(raw)

    def test_validated_inventory_can_be_loaded_and_used_for_environment_summary(self):
        raw = connected_inventory(installed_sources={"ltx_core_release": "v1.6.2"})
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "inventory.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            inventory = manager.read_inventory(path)
        self.assertEqual(inventory["status"], "CONNECTED")
        self.assertEqual(inventory["ltx"]["primary_model"], "LTX-2.5")
        self.assertTrue(inventory["environment_fingerprint"])
        current = manager.initial_state(6)
        with patch.object(manager.urllib.request, "urlopen", side_effect=fake_upstream()):
            updated = manager.monitor_once(current, interval_hours=6, force=True, inventory=inventory, now=self.now)
        self.assertEqual(updated["environment"]["status"], "CONNECTED")
        self.assertEqual(updated["environment"]["gpu_vram_gib"], 32)

    def test_model_manifest_yields_storage_estimate_without_starting_download(self):
        observation = {"metadata": {"license": "ltx-2.x-community-license-agreement", "gated": False,
            "files": [{"name": "transformer.safetensors", "size_bytes": 8_000_000_000},
                      {"name": "gemma.safetensors", "size_bytes": 2_000_000_000}]}}
        result = manager.build_installation_requirements(observation, connected_inventory())
        self.assertEqual(result["estimated_download_bytes"], 10_000_000_000)
        self.assertEqual(result["storage_preflight"], "SUFFICIENT_FOR_DOWNLOAD_ONLY")
        self.assertTrue(result["requires_director_approval"])

    def test_failed_source_does_not_suppress_other_sources(self):
        def opener(request, timeout=10):
            url = getattr(request, "full_url", str(request))
            if url.endswith("LTX-2/releases/latest"):
                raise TimeoutError("simulated upstream timeout")
            return fake_upstream()(request, timeout)
        with patch.object(manager.urllib.request, "urlopen", side_effect=opener):
            state = manager.monitor_once(interval_hours=6, timeout=1, force=True, now=self.now)
        self.assertEqual(state["failed_source_count"], 1)
        self.assertEqual(state["successful_source_count"], len(manager.SOURCES) - 1)
        self.assertIn("ltx_core_release", state["source_errors"])
        self.assertTrue(any(row["type"] == "SOURCE_CHECK_FAILED" for row in state["notifications"]))
        self.assertIsNone(state.get("last_successful_check_at"))
        self.assertEqual(state["next_check_due_at"], manager.stamp(self.now + timedelta(hours=1)))

    def test_cli_persists_outage_notifications_without_failing_the_workflow(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state" / "manager.json"
            with patch.object(manager.urllib.request, "urlopen", side_effect=TimeoutError("network unavailable")):
                exit_code = manager.main(["--state-file", str(path), "--interval-hours", "6", "--force", "--timeout", "1"])
            self.assertEqual(exit_code, 0)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["successful_source_count"], 0)
            self.assertEqual(saved["failed_source_count"], len(manager.SOURCES))
            self.assertTrue(any(row["type"] == "SOURCE_CHECK_FAILED" for row in saved["notifications"]))

    def test_invalid_inventory_print_command_reports_invalid_instead_of_not_connected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "inventory.json"
            path.write_text("{bad", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = manager.main(["--inventory-file", str(path), "--print-inventory-fingerprint"])
        self.assertEqual(code, 2)
        self.assertTrue(output.getvalue().startswith("INVALID:"))

    def test_invalid_inventory_does_not_stop_metadata_discovery_and_is_notified(self):
        with tempfile.TemporaryDirectory() as temp:
            state_path = Path(temp) / "state" / "manager.json"
            inventory_path = Path(temp) / "inventory.json"
            inventory_path.write_text("{bad", encoding="utf-8")
            with patch.object(manager.urllib.request, "urlopen", side_effect=fake_upstream()):
                code = manager.main(["--state-file", str(state_path), "--inventory-file", str(inventory_path), "--force"])
            saved = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(saved["environment"]["status"], "INVALID_INVENTORY")
        self.assertTrue(any(row["type"] == "MANUAL_ACTION_REQUIRED" for row in saved["notifications"]))
        self.assertEqual(saved["successful_source_count"], len(manager.SOURCES))

    def test_json_state_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state" / "manager.json"
            state = manager.initial_state(6)
            manager.write_state(path, state)
            self.assertEqual(manager.read_state(path), state)
            self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
