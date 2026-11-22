from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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

    def test_interval_skips_runs_until_due(self):
        initial = manager.initial_state(6)
        initial["last_successful_check_at"] = manager.stamp(self.now)
        with patch.object(manager.urllib.request, "urlopen", side_effect=AssertionError("network should not be called")):
            skipped = manager.monitor_once(initial, interval_hours=6, now=self.now + timedelta(hours=3))
        self.assertTrue(skipped["skipped"])
        self.assertEqual(skipped["next_check_due_at"], manager.stamp(self.now + timedelta(hours=6)))

    def test_inventory_only_marks_exact_revision_already_installed(self):
        candidate = {"source": "ltx_core_release", "version": "v1.6.2"}
        self.assertEqual(manager.classify_compatibility(candidate, None)["status"], "REQUIRES_MANUAL_APPROVAL")
        inventory = {"status": "CONNECTED", "installed_sources": {"ltx_core_release": "v1.6.2"}}
        self.assertEqual(manager.classify_compatibility(candidate, inventory)["status"], "ALREADY_INSTALLED")

    def test_compatibility_and_incompatibility_require_matching_test_and_environment_fingerprint(self):
        candidate = {"source": "comfyui_ltxvideo_release", "version": "v1.1.2"}
        inventory = {
            "status": "CONNECTED",
            "environment_fingerprint": "comfyui-0.44-ltx25-stack-A",
            "compatibility_results": [
                {"source": candidate["source"], "version": candidate["version"],
                 "environment_fingerprint": "different-stack", "result": "COMPATIBLE", "workflow_test_passed": True}
            ],
        }
        self.assertEqual(manager.classify_compatibility(candidate, inventory)["status"], "REQUIRES_MANUAL_APPROVAL")
        inventory["compatibility_results"] = [
            {"source": candidate["source"], "version": candidate["version"],
             "environment_fingerprint": "comfyui-0.44-ltx25-stack-A", "result": "COMPATIBLE", "workflow_test_passed": True}
        ]
        self.assertEqual(manager.classify_compatibility(candidate, inventory)["status"], "COMPATIBLE")
        inventory["compatibility_results"][0]["result"] = "INCOMPATIBLE"
        inventory["compatibility_results"][0]["reason"] = "Required node missing."
        self.assertEqual(manager.classify_compatibility(candidate, inventory)["status"], "INCOMPATIBLE")

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

    def test_json_state_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state" / "manager.json"
            state = manager.initial_state(6)
            manager.write_state(path, state)
            self.assertEqual(manager.read_state(path), state)
            self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
