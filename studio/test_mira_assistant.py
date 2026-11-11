from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mira_assistant import (
    MiraAssistant,
    MiraConfigurationError,
    MiraProviderError,
    MiraRateLimitError,
)


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size=-1):
        return self.payload[:size] if size >= 0 else self.payload


class MiraAssistantTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "GEMINI_API_KEY": "test-key",
            "MIRA_GEMINI_FREE_TIER_ACK": "true",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.mira = MiraAssistant()
        self.context = {
            "controller": {"online": True, "backend_adapter": "MockComfyUIAdapter", "mock_mode": True},
            "workspace": {"projects": 2, "scenes": 5, "shots": 8, "tests": 3, "assets": 4, "reviews": 1, "tests_passed": 1, "tests_failed": 0, "tracked_cost_usd": 99},
            "project_status_counts": {"PRE_PRODUCTION": 2, "UNKNOWN": 8},
            "test_status_counts": {"PLANNED": 2, "PASSED": 1},
            "private_project_title": "Confidential Script Name",
        }

    def test_status_never_returns_api_key(self):
        status = self.mira.status()
        self.assertTrue(status["configured"])
        self.assertEqual(status["model"], "gemini-3.8-flash")
        self.assertEqual(status["api"], "Interactions API (store=false; short history in session memory)")
        self.assertNotIn("test-key", json.dumps(status))

    def test_status_stays_locked_without_free_tier_acknowledgement(self):
        with patch.dict(os.environ, {"MIRA_GEMINI_FREE_TIER_ACK": ""}):
            status = self.mira.status()
            self.assertFalse(status["configured"])
            self.assertTrue(status["key_present"])
            self.assertFalse(status["free_tier_acknowledged"])

    def test_chat_sends_only_aggregated_allowlisted_context_and_disables_google_storage(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse({"steps": [
                {"type": "model_thought", "content": [{"type": "text", "text": "Private internal reasoning."}]},
                {"type": "model_output", "content": [{"type": "text", "text": "Good morning, boss. Your studio briefing is ready."}]},
            ]})

        with patch("mira_assistant.urllib.request.urlopen", side_effect=fake_urlopen):
            result = self.mira.chat("How is the studio?", self.context, "director-session")
        request = captured["request"]
        payload = json.loads(request.data.decode("utf-8"))
        system_text = payload["system_instruction"]
        self.assertTrue(request.full_url.endswith("/v1/interactions"))
        self.assertEqual(request.get_header("X-goog-api-key"), "test-key")
        self.assertEqual(captured["timeout"], 22)
        self.assertFalse(payload["store"])
        self.assertEqual(payload["model"], "gemini-3.8-flash")
        self.assertEqual(payload["input"][-1], {"type": "user_input", "content": "How is the studio?"})
        self.assertIn('"projects":2', system_text)
        self.assertIn('"PRE_PRODUCTION":2', system_text)
        self.assertNotIn("Confidential Script Name", system_text)
        self.assertNotIn("tracked_cost_usd", system_text)
        self.assertNotIn("99", system_text)
        self.assertEqual(result["answer"], "Good morning, boss. Your studio briefing is ready.")
        self.assertNotIn("Private internal reasoning", result["answer"])

    def test_history_is_held_in_session_memory_and_sent_statelessly(self):
        captured = []
        responses = [
            FakeResponse({"steps": [
                {"type": "model_thought", "content": [{"type": "text", "text": "Keep this internal step too."}]},
                {"type": "model_output", "content": [{"type": "text", "text": "Your studio is in Mock Mode."}]},
            ]}),
            FakeResponse({"steps": [
                {"type": "model_output", "content": [{"type": "text", "text": "No, the GPU is not connected."}]},
            ]}),
        ]

        def fake_urlopen(request, timeout):
            captured.append(json.loads(request.data.decode("utf-8")))
            return responses.pop(0)

        with patch("mira_assistant.urllib.request.urlopen", side_effect=fake_urlopen):
            self.mira.chat("How is the studio?", self.context, "session-2")
            self.mira.chat("Is a GPU ready?", self.context, "session-2")

        self.assertEqual(captured[1]["input"][0], {"type": "user_input", "content": "How is the studio?"})
        self.assertEqual(captured[1]["input"][1]["type"], "model_thought")
        self.assertEqual(captured[1]["input"][2], {"type": "model_output", "content": [{"type": "text", "text": "Your studio is in Mock Mode."}]})
        self.assertEqual(captured[1]["input"][3], {"type": "user_input", "content": "Is a GPU ready?"})
        self.assertFalse(captured[0]["store"])
        self.assertFalse(captured[1]["store"])

    def test_logout_clears_session_conversation_history(self):
        requests = []
        responses = [
            FakeResponse({"steps": [{"type": "model_output", "content": [{"type": "text", "text": "Mira reply."}]}]}),
            FakeResponse({"steps": [{"type": "model_output", "content": [{"type": "text", "text": "New session."}]}]}),
        ]
        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data.decode("utf-8")))
            return responses.pop(0)
        with patch("mira_assistant.urllib.request.urlopen", side_effect=fake_urlopen):
            self.mira.chat("First question", self.context, "session-3")
            self.mira.clear_session("session-3")
            self.mira.chat("After sign in again", self.context, "session-3")
        self.assertEqual(len(requests[1]["input"]), 1)
        self.assertEqual(requests[1]["input"][0], {"type": "user_input", "content": "After sign in again"})

    def test_missing_key_is_a_clear_configuration_error(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            with self.assertRaisesRegex(MiraConfigurationError, "GEMINI_API_KEY"):
                self.mira.chat("Hello", [], "session")

    def test_chat_stays_locked_until_free_tier_flag_is_set(self):
        with patch.dict(os.environ, {"MIRA_GEMINI_FREE_TIER_ACK": ""}):
            with self.assertRaisesRegex(MiraConfigurationError, "MIRA_GEMINI_FREE_TIER_ACK"):
                self.mira.chat("Hello", self.context, "session")

    def test_message_length_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "2000 characters"):
            self.mira.chat("x" * 2001, self.context, "session")

    def test_missing_session_is_rejected(self):
        with self.assertRaises(MiraConfigurationError):
            self.mira.chat("Hello", self.context, "")

    def test_session_rate_limit_is_enforced(self):
        response = FakeResponse({"steps": [{"type": "model_output", "content": [{"type": "text", "text": "ok"}]}]})
        with patch("mira_assistant.urllib.request.urlopen", return_value=response):
            for _ in range(8):
                self.mira.chat("Hello", self.context, "session")
            with self.assertRaises(MiraRateLimitError):
                self.mira.chat("Hello", self.context, "session")

    def test_provider_failures_do_not_expose_raw_http_details(self):
        import urllib.error
        failure = urllib.error.HTTPError("url", 403, "forbidden", {}, None)
        with patch("mira_assistant.urllib.request.urlopen", side_effect=failure):
            with self.assertRaisesRegex(MiraProviderError, "Google rejected"):
                self.mira.chat("Hello", self.context, "session")


if __name__ == "__main__":
    unittest.main()
