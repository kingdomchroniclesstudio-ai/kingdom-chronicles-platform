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
            return FakeResponse(json.dumps({"id": "Lightricks/LTX-2.5-Diffusers", "sha": revision, "lastModified": "2026-11-20T00:00:00Z"}).encode())
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

    def test_interval_skips_runs_until_due(self):
        initial = manager.initial_state(6)
        initial["last_successful_check_at"] = manager.stamp(self.now)
        with patch.object(manager.urllib.request, "urlopen", side_effect=AssertionError("network should not be called")):
            skipped = manager.monitor_once(initial, interval_hours=6, now=self.now + timedelta(hours=3))
        self.assertTrue(skipped["skipped"])
        self.assertEqual(skipped["next_check_due_at"], manager.stamp(self.now + timedelta(hours=6)))

    def test_inventory_only_marks_exact_revision_already_installed(self):
        self.assertEqual(manager.classify_compatibility({"source": "ltx_core_release", "version": "v1.6.2"}, None)["status"], "REQUIRES_MANUAL_APPROVAL")
        inventory = {"installed_sources": {"ltx_core_release": "v1.6.2"}}
        self.assertEqual(manager.classify_compatibility({"source": "ltx_core_release", "version": "v1.6.2"}, inventory)["status"], "ALREADY_INSTALLED")

    def test_failed_source_does_not_suppress_other_sources(self):
        def opener(request, timeout=10):
            url = getattr(request, "full_url", str(request))
            if url.endswith("LTX-2/releases/latest"):
                raise TimeoutError("simulated upstream timeout")
            return fake_upstream()(request, timeout)
        with patch.object(manager.urllib.request, "urlopen", side_effect=opener):
            state = manager.monitor_once(interval_hours=6, timeout=1, force=True, now=self.now)
        self.assertEqual(state["failed_source_count"], 1)
        self.assertIn("ltx_core_release", state["source_errors"])
        self.assertTrue(any(row["type"] == "SOURCE_CHECK_FAILED" for row in state["notifications"]))

    def test_json_state_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state" / "manager.json"
            state = manager.initial_state(6)
            manager.write_state(path, state)
            self.assertEqual(manager.read_state(path), state)
            self.assertFalse(path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
