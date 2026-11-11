from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio_workspace import StudioWorkspace


class StudioWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hrf-studio-tests-")
        self.root = Path(self.temp.name)
        self.workspace = StudioWorkspace(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_projects_scenes_and_shots_are_linked(self):
        project = self.workspace.create_project({
            "title": "The Resurrection", "film_type": "FEATURE_FILM", "status": "PRE_PRODUCTION",
            "synopsis": "A cinematic retelling of the resurrection."
        })
        scene = self.workspace.create_scene({
            "project_id": project["project_id"], "scene_number": 16,
            "title": "The Garden Tomb", "location": "Jerusalem garden"
        })
        shot = self.workspace.create_shot({
            "project_id": project["project_id"], "scene_id": scene["scene_id"],
            "shot_code": "SC016-SH001", "description": "The tomb at dawn"
        })
        self.assertEqual(self.workspace.list_scenes(project["project_id"])[0]["shot_count"], 1)
        self.assertEqual(self.workspace.list_shots(project_id=project["project_id"])[0]["shot_code"], shot["shot_code"])
        self.assertEqual(self.workspace.list_projects()[0]["shot_count"], 1)

    def test_shot_cannot_be_attached_to_another_projects_scene(self):
        first = self.workspace.create_project({"title": "Film One"})
        second = self.workspace.create_project({"title": "Film Two"})
        scene = self.workspace.create_scene({"project_id": first["project_id"], "scene_number": 1, "title": "Opening"})
        with self.assertRaisesRegex(ValueError, "does not belong"):
            self.workspace.create_shot({
                "project_id": second["project_id"], "scene_id": scene["scene_id"], "shot_code": "SH001"
            })

    def test_test_records_update_reports_and_cost_totals(self):
        project = self.workspace.create_project({"title": "Moses"})
        record = self.workspace.create_test({
            "project_id": project["project_id"], "test_name": "Staff raise camera A",
            "model_name": "LTX-2.5", "workflow": "T2V", "comparison_group": "CAM-A-B",
            "result_status": "PLANNED", "gpu_minutes": 3.5, "cost_usd": 1.79
        })
        self.workspace.update_status("test", record["test_id"], "PASSED")
        overview = self.workspace.overview()
        self.assertEqual(overview["tests"], 1)
        self.assertEqual(overview["tests_passed"], 1)
        self.assertEqual(overview["tracked_gpu_minutes"], 3.5)
        self.assertEqual(overview["tracked_cost_usd"], 1.79)
        self.assertEqual(self.workspace.reports()["test_results"]["passed"], 1)

    def test_assets_and_review_notes_are_persisted(self):
        project = self.workspace.create_project({"title": "Daniel"})
        asset = self.workspace.create_asset({
            "project_id": project["project_id"], "category": "CHARACTER", "name": "Daniel",
            "reference_code": "CHR-DAN", "continuity_notes": "Keep the same robe and beard.",
            "tags": ["character", "approved"]
        })
        self.assertEqual(self.workspace.list_assets(project_id=project["project_id"])[0]["asset_id"], asset["asset_id"])
        note = self.workspace.create_review({
            "take_id": "TAKE-001", "rating": 4, "decision": "REVISION_REQUEST",
            "note": "Keep the character appearance consistent."
        })
        self.assertEqual(self.workspace.list_reviews("TAKE-001")[0]["review_id"], note["review_id"])
        self.assertEqual(self.workspace.overview()["reviews"], 1)

    def test_database_survives_workspace_reinitialization(self):
        project = self.workspace.create_project({"title": "Noah"})
        restarted = StudioWorkspace(self.root)
        self.assertEqual(restarted.list_projects()[0]["project_id"], project["project_id"])

    def test_invalid_enums_and_oversized_text_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "status"):
            self.workspace.create_project({"title": "Invalid", "status": "NOT_A_STATUS"})
        with self.assertRaisesRegex(ValueError, "120 characters"):
            self.workspace.create_project({"title": "x" * 121})

    def test_workspace_database_uses_configured_data_root_path(self):
        self.assertEqual(self.workspace.db_path.parent, self.root.resolve())
        self.assertTrue(self.workspace.db_path.exists())


class StudioControlRoomUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html_path = Path(__file__).resolve().parents[1] / "studio_control_room.html"
        cls.html = cls.html_path.read_text(encoding="utf-8")

    def test_all_pre_gpu_rooms_and_core_controls_are_present(self):
        for marker in (
            'data-room="overview"', 'data-room="projects"', 'data-room="testing"',
            'data-room="assets"', 'data-room="review"', 'data-room="reports"',
            'data-room="generation"', 'LTX Update Monitor', 'RUN ONE MOCK SHOT',
            'Director Command', 'id="realShotForm"', 'id="takeList"', 'id="comparisonGroups"', 'data-resource="project"', 'data-resource="scene"', 'data-resource="shot"', 'data-resource="test"'
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_html_document_has_no_trailing_visible_code(self):
        self.assertEqual(self.html.count("</html>"), 1)
        self.assertTrue(self.html.rstrip().endswith("</html>"))
        self.assertEqual(self.html.count("<script>"), 1)
        self.assertEqual(self.html.count("</script>"), 1)

    def test_browser_javascript_parses(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is not installed in this test environment.")
        scripts = re.findall(r"<script>(.*?)</script>", self.html, re.S)
        self.assertTrue(scripts, "The control-room page must contain its application script.")
        with tempfile.TemporaryDirectory(prefix="hrf-ui-js-") as temp:
            script_path = Path(temp) / "control-room.js"
            script_path.write_text("\n".join(scripts), encoding="utf-8")
            checked = subprocess.run([node, "--check", str(script_path)], capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)


class StudioControlRoomRouteWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        controller_path = root / "director_console.py"
        cls.source = controller_path.read_text(encoding="utf-8")
        cls.html = (root / "studio_control_room.html").read_text(encoding="utf-8")

    def test_authenticated_studio_get_and_post_routes_are_packaged(self):
        for marker in (
            'if path == "/api/studio/overview":',
            'if path == "/api/studio/projects":',
            'if path == "/api/studio/scenes":',
            'if path == "/api/studio/shots":',
            'if path == "/api/studio/tests":',
            'if path == "/api/studio/assets":',
            'if path == "/api/studio/reviews":',
            'if path == "/api/studio/reports":',
            'self._console().workspace.create_project(body)',
            'self._console().workspace.create_scene(body)',
            'self._console().workspace.create_shot(body)',
            'self._console().workspace.create_test(body)',
            'self._console().workspace.create_asset(body)',
            'self._console().controller.get_take(take_id)',
            'origin_required',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.source)

    def test_status_route_updates_allowlisted_resources(self):
        self.assertIn('status_parts[3] in {"projects", "scenes", "shots", "tests"}', self.source)
        self.assertIn('self._console().workspace.update_status(resource', self.source)


    def test_mira_intelligence_room_has_holographic_identity_and_truthful_states(self):
        for marker in (
            'data-room="mira"', 'id="room-mira"', 'id="miraOrb"',
            'id="miraBriefing"', 'id="miraWatchlist"', 'id="miraVoiceButton"',
            'VOICE ENGINE NOT CONNECTED', 'Mira does not execute commands',
            'prefers-reduced-motion:reduce', 'miraSetState', 'refreshMiraBriefing',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_mira_is_persistently_visible_across_authenticated_studio_rooms(self):
        app_start = self.html.index('<div id="app"')
        homebar = self.html.index('id="miraHomebar"')
        shell = self.html.index('<div class="shell">', app_start)
        self.assertLess(homebar, shell)
        for marker in (
            'id="miraHomeGreeting"', 'id="miraHomeSummary"',
            'id="miraHomeVoiceState"', 'data-go="mira">TALK TO MIRA',
            'await refreshMiraBriefing();',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html)

    def test_mira_briefing_discloses_manual_cost_and_missing_live_telemetry(self):
        self.assertIn('manually entered test-log values', self.html)
        self.assertIn('not live RunPod billing or telemetry', self.html)

    def test_mira_chat_is_authenticated_read_only_and_discloses_gemini_free_tier(self):
        for marker in (
            'if path == "/api/mira/status":',
            'if path == "/api/mira/chat":',
            'body.get("data_use_acknowledged") is not True',
            'self._console().mira_briefing_context()',
            'MiraProviderError',
            'def mira_briefing_context(self)',
            'self.mira = MiraAssistant()',
            'self._console().mira.clear_session(self._cookie_token() or "")',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.source)
        for marker in (
            'id="miraPrivacyNotice"',
            'id="miraDataConsent"',
            'id="miraChatStatus"',
            'id="miraChatInput"',
            'not type confidential scripts',
            'human reviewers may read',
            'store=false',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.html.lower())

if __name__ == "__main__":
    unittest.main()
