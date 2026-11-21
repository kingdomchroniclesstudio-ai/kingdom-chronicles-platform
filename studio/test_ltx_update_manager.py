from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ltx_update_manager import LTXUpdateManager


class FakeResponse:
    def __init__(self, payload: dict):
        self.raw = json.dumps(payload).encode("utf-8")
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, size=-1): return self.raw if size < 0 else self.raw[:size]


def example_state() -> dict:
    return {
        "schema_version": 1,
        "manager": "HIS RISEN LTX Update and Integration Manager",
        "model_policy": {"primary_model": "LTX-2.5", "model_switching": False},
        "schedule": {"enabled": True, "interval_hours": 6, "scheduler": "GitHub Actions"},
        "last_check_at": "2026-11-21T10:00:00Z",
        "last_successful_check_at": "2026-11-21T10:00:00Z",
        "next_check_due_at": "2026-11-21T16:00:00Z",
        "successful_source_count": 10, "failed_source_count": 0,
        "candidates": [
            {"id": "a", "status": "DETECTED", "compatibility": {"status": "REQUIRES_MANUAL_APPROVAL"}},
            {"id": "b", "status": "VERIFIED", "compatibility": {"status": "ALREADY_INSTALLED"}},
        ],
        "notifications": [{"id": "n1", "read": False}, {"id": "n2", "read": True}],
        "activity": [{"id": "e1", "type": "NEW_UPDATE_DETECTED"}],
        "environment": {"status": "NOT_CONNECTED", "comfyui_version": None, "installed_ltx_version": None},
        "capabilities": {"verified": ["metadata_monitoring"]},
        "safety": {"automatic_install": False, "downloads_enabled": False, "gpu_jobs_enabled": False, "director_approval_required": True},
    }


class LTXUpdateManagerRuntimeTests(unittest.TestCase):
    def test_reads_trusted_remote_state_and_returns_dashboard_counts(self):
        payload = example_state()
        with tempfile.TemporaryDirectory() as temp, patch("ltx_update_manager.urllib.request.urlopen", return_value=FakeResponse(payload)):
            data = LTXUpdateManager(Path(temp)).status()
            self.assertTrue(data["ok"])
            self.assertEqual(data["state_source"], "REMOTE_SCHEDULED_STATE")
            self.assertFalse(data["stale"])
            self.assertEqual(data["primary_model"], "LTX-2.5")
            self.assertEqual(data["summary"]["detected"], 1)
            self.assertEqual(data["summary"]["pending_approval"], 1)
            self.assertEqual(data["summary"]["unread_notifications"], 1)
            self.assertTrue((Path(temp) / "storage" / "ltx_update_manager_state.json").is_file())

    def test_remote_failure_falls_back_to_cached_state(self):
        payload = example_state()
        with tempfile.TemporaryDirectory() as temp:
            manager = LTXUpdateManager(Path(temp))
            manager._write_cache(payload)
            with patch("ltx_update_manager.urllib.request.urlopen", side_effect=TimeoutError("offline")):
                data = manager.status()
            self.assertEqual(data["state_source"], "LOCAL_CACHE")
            self.assertTrue(data["stale"])
            self.assertEqual(data["summary"]["detected"], 1)

    def test_rejects_non_raw_github_state_url(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = LTXUpdateManager(Path(temp), state_url="https://github.com/example/file.json")
            with patch("ltx_update_manager.urllib.request.urlopen") as opener:
                data = manager.status()
            opener.assert_not_called()
            self.assertEqual(data["state_source"], "UNAVAILABLE")
            self.assertTrue(data["stale"])

    def test_director_console_route_and_dashboard_are_packaged(self):
        root = Path(__file__).resolve().parents[1]
        console = root / "director_console.py"
        html = root / "studio_control_room.html"
        if not console.exists() or not html.exists():
            self.skipTest("source-only checkout; package integration assertions run inside the controller ZIP")
        console_text = console.read_text(encoding="utf-8")
        html_text = html.read_text(encoding="utf-8")
        self.assertIn('if path == "/api/updates/manager":', console_text)
        self.assertIn("self._console().update_manager_status()", console_text)
        for marker in ("ltxManagerPanel", "ltxManagerCandidates", "ltxManagerNotifications", "ltxManagerActivity", "refreshLtxManager", "CHECK NOW"):
            with self.subTest(marker=marker):
                self.assertIn(marker, html_text)

    def test_rejects_wrong_model_family_from_remote_state(self):
        payload = example_state()
        payload["model_policy"]["primary_model"] = "another-model"
        with tempfile.TemporaryDirectory() as temp, patch("ltx_update_manager.urllib.request.urlopen", return_value=FakeResponse(payload)):
            data = LTXUpdateManager(Path(temp)).status()
            self.assertFalse(data["ok"])
            self.assertEqual(data["state_source"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
