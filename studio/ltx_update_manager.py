from __future__ import annotations

"""Read-only bridge from the Director Console to scheduled LTX monitor state."""

import json
import os
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_STATE_URL = (
    "https://raw.githubusercontent.com/kingdomchroniclesstudio-ai/"
    "kingdom-chronicles-platform/ltx-update-state/state/ltx_update_manager.json"
)
USER_AGENT = "HIS-RISEN-Director-Console-LTX-Manager/1.0"
MAX_STATE_BYTES = 1_000_000


class LTXUpdateManager:
    """Loads the durable public metadata-only monitor state with a local cache fallback."""

    def __init__(self, data_root: Path, state_url: str | None = None, timeout: float = 4.0):
        self.data_root = Path(data_root).resolve()
        self.cache_path = self.data_root / "storage" / "ltx_update_manager_state.json"
        self.state_url = (state_url or os.environ.get("HRF_LTX_UPDATE_STATE_URL", DEFAULT_STATE_URL)).strip()
        self.timeout = max(1.0, min(float(timeout), 10.0))

    def _read_cache(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def _write_cache(self, value: dict[str, Any]) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
            temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temp.replace(self.cache_path)
        except OSError:
            pass

    def _fetch_remote(self) -> dict[str, Any]:
        if not self.state_url.startswith("https://raw.githubusercontent.com/"):
            raise ValueError("LTX update state URL must use the trusted raw.githubusercontent.com host")
        request = urllib.request.Request(self.state_url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw = response.read(MAX_STATE_BYTES + 1)
        if len(raw) > MAX_STATE_BYTES:
            raise ValueError("LTX update monitor state exceeded the safe response size")
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError("LTX update monitor state has an unsupported schema")
        if value.get("model_policy", {}).get("primary_model") != "LTX-2.5":
            raise ValueError("LTX update monitor state does not preserve the approved LTX-2.5 primary model")
        return value

    def status(self) -> dict[str, Any]:
        source = "REMOTE_SCHEDULED_STATE"
        stale = False
        error = None
        try:
            state = self._fetch_remote()
            self._write_cache(state)
        except Exception as exc:
            state = self._read_cache() or {}
            source = "LOCAL_CACHE" if state else "UNAVAILABLE"
            stale = True
            error = f"{type(exc).__name__}: {str(exc)[:240]}"

        candidates = state.get("candidates", []) if isinstance(state.get("candidates"), list) else []
        notifications = state.get("notifications", []) if isinstance(state.get("notifications"), list) else []
        activity = state.get("activity", []) if isinstance(state.get("activity"), list) else []
        summary = {
            "detected": sum(1 for item in candidates if item.get("status") == "DETECTED"),
            "pending_approval": sum(1 for item in candidates if item.get("compatibility", {}).get("status") in {"REQUIRES_MANUAL_APPROVAL", "COMPATIBLE"}),
            "already_installed": sum(1 for item in candidates if item.get("compatibility", {}).get("status") == "ALREADY_INSTALLED"),
            "incompatible": sum(1 for item in candidates if item.get("compatibility", {}).get("status") == "INCOMPATIBLE"),
            "verified": len(state.get("capabilities", {}).get("verified", [])),
            "unread_notifications": sum(1 for item in notifications if not item.get("read", False)),
        }
        capabilities = state.get("capabilities", {}) if isinstance(state.get("capabilities"), dict) else {}
        detected_capabilities = capabilities.get("detected", []) if isinstance(capabilities.get("detected"), list) else []
        return {
            "ok": bool(state), "state_source": source, "stale": stale, "read_error": error,
            "manager": state.get("manager", "HIS RISEN LTX Update and Integration Manager"),
            "primary_model": "LTX-2.5",
            "schedule": state.get("schedule", {"enabled": True, "interval_hours": 6, "scheduler": "GitHub Actions"}),
            "last_check_at": state.get("last_check_at"),
            "last_successful_check_at": state.get("last_successful_check_at"),
            "next_check_due_at": state.get("next_check_due_at"),
            "successful_source_count": state.get("successful_source_count", 0),
            "failed_source_count": state.get("failed_source_count", 0),
            "source_total_count": state.get("source_total_count", 15),
            "environment": state.get("environment", {"status": "NOT_CONNECTED", "comfyui_version": None, "installed_ltx_version": None}),
            "summary": summary, "candidates": candidates[-50:],
            "capabilities": {
                "detected": detected_capabilities[-100:],
                "registered": capabilities.get("registered", []),
                "installed": capabilities.get("installed", []),
                "verified": capabilities.get("verified", []),
            },
            "notifications": notifications[-50:], "activity": activity[-50:],
            "safety": state.get("safety", {"automatic_install": False, "downloads_enabled": False, "gpu_jobs_enabled": False, "director_approval_required": True}),
        }
