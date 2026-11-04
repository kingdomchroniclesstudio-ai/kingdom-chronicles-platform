from __future__ import annotations

import hashlib
import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "apps" / "his_risen_controller_ltx25_audited_update_2026-10-10 (2).zip"
MANIFEST = Path(str(ARCHIVE) + ".sha256")
BASE_SHA256 = "2f409e30699ceb6cfb5bfee4c376c00c3151c7cea4969a2c7f1032502dfee012"
TEST_ROOT = Path("/tmp/his-risen-production-readiness")
QUEUE_MARKER = "def _queue_contains_prompt(queue: dict[str, Any], prompt_id: str) -> bool:"
HTTPS_MARKER = "def validate_comfyui_base_url(base_url: str) -> str:"
REDIRECT_MARKER = "class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):"


def replace_once(files: dict[str, bytes], path: str, old: str, new: str, label: str) -> None:
    if path not in files:
        raise SystemExit(f"Required package file is missing: {path}")
    try:
        content = files[path].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit(f"Expected UTF-8 source file: {path}") from exc
    count = content.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one {label} insertion point; found {count}")
    files[path] = content.replace(old, new, 1).encode("utf-8")


def main() -> None:
    current_digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    with zipfile.ZipFile(ARCHIVE, "r") as source:
        files = {
            info.filename: source.read(info.filename)
            for info in source.infolist()
            if not info.is_dir()
        }
        infos = source.infolist()

    adapter = files["comfyui/adapter.py"].decode("utf-8")
    bootstrap = files["config/bootstrap.py"].decode("utf-8")
    exports = files["exports.py"].decode("utf-8")
    already_patched = (
        QUEUE_MARKER in adapter
        and HTTPS_MARKER in bootstrap
        and REDIRECT_MARKER in exports
    )
    if already_patched:
        manifest_line = MANIFEST.read_text(encoding="utf-8").strip()
        if manifest_line != f"{current_digest}  {ARCHIVE.name}":
            raise SystemExit("Follow-up hardened package does not match its checksum manifest")
        shutil.rmtree(TEST_ROOT, ignore_errors=True)
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(ARCHIVE, "r") as check:
            bad = check.testzip()
            if bad is not None:
                raise SystemExit(f"Follow-up ZIP integrity check failed: {bad}")
            check.extractall(TEST_ROOT)
        print("FOLLOWUP_PATCH_ALREADY_PRESENT", current_digest)
        print("TEST_ROOT", TEST_ROOT)
        return

    if current_digest != BASE_SHA256:
        raise SystemExit(f"Unexpected starting package digest for follow-up hardening: {current_digest}")

    # Require TLS for remote ComfyUI endpoints. Plain HTTP remains available for loopback testing.
    replace_once(
        files, "config/bootstrap.py",
        "from pathlib import Path\nimport os\nfrom typing import Any\n",
        "from pathlib import Path\nimport ipaddress\nimport os\nfrom typing import Any\nfrom urllib.parse import urlsplit\n",
        "bootstrap URL validation imports",
    )
    replace_once(
        files, "config/bootstrap.py",
        "from workflows.capability_registry import LTX25CapabilityRegistry\n\n\ndef build_controller",
        '''from workflows.capability_registry import LTX25CapabilityRegistry


def validate_comfyui_base_url(base_url: str) -> str:
    """Require HTTPS for remote ComfyUI endpoints; allow HTTP only on loopback."""
    try:
        parsed = urlsplit(base_url)
        _ = parsed.port  # Access also validates malformed port values.
    except ValueError as exc:
        raise ValueError("ComfyUI base URL contains an invalid port or URL component") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("ComfyUI base URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("ComfyUI base URL must not contain credentials, query parameters, or fragments")
    host = parsed.hostname.lower()
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    if parsed.scheme == "http" and not loopback:
        raise ValueError("remote ComfyUI endpoints must use HTTPS; plain HTTP is allowed only for loopback")
    return base_url.rstrip("/")


def build_controller''',
        "ComfyUI URL validation helper",
    )
    replace_once(
        files, "config/bootstrap.py",
        '        if not base_url:\n            raise ValueError("HRF_COMFYUI_BASE_URL or runtime.comfyui.base_url is required for the comfyui backend")\n        raw_headers',
        '        if not base_url:\n            raise ValueError("HRF_COMFYUI_BASE_URL or runtime.comfyui.base_url is required for the comfyui backend")\n        base_url = validate_comfyui_base_url(base_url)\n        raw_headers',
        "validate configured ComfyUI URL",
    )

    # Active/running prompts are in /queue; /history is completed/error execution history.
    replace_once(
        files, "comfyui/http_client.py",
        "    def system_stats(self) -> dict[str, Any]:\n",
        '''    def queue(self) -> dict[str, Any]:
        result = self._request_json("GET", "/queue")
        if not isinstance(result, dict):
            raise ComfyUIProtocolError("/queue response must be an object")
        for field in ("queue_running", "queue_pending"):
            if not isinstance(result.get(field), list):
                raise ComfyUIProtocolError(f"/queue response missing list: {field}")
        return result

    def system_stats(self) -> dict[str, Any]:
''',
        "ComfyUI queue client method",
    )
    replace_once(
        files, "comfyui/adapter.py",
        "    def poll(self, job_id: str) -> GenerationUpdate:\n        job = self.jobs.get(job_id)\n",
        '''    @staticmethod
    def _queue_contains_prompt(queue: dict[str, Any], prompt_id: str) -> bool:
        """Recognize ComfyUI queue entries in tuple/list or object form."""
        for field in ("queue_running", "queue_pending"):
            for item in queue.get(field, []):
                if isinstance(item, dict):
                    if item.get("prompt_id") == prompt_id or item.get("id") == prompt_id:
                        return True
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    if item[1] == prompt_id:
                        return True
        return False

    def poll(self, job_id: str) -> GenerationUpdate:
        job = self.jobs.get(job_id)
''',
        "ComfyUI queue prompt matcher",
    )
    replace_once(
        files, "comfyui/adapter.py",
        '''            if isinstance(history, dict) and isinstance(history.get(job_id), dict):
                return GenerationUpdate(state="RUNNING", progress=50)
            raise ComfyUIError(f"unknown or unavailable ComfyUI prompt_id: {job_id}")
''',
        '''            # ComfyUI history records completed/errored executions. Active jobs
            # are exposed separately by GET /queue. Check both after a restart.
            queue = self.http.queue()
            if self._queue_contains_prompt(queue, job_id):
                return GenerationUpdate(state="RUNNING", progress=50)
            # Close the small race where the job completes between the first
            # history lookup and the queue lookup.
            latest_history = self.http.history(job_id)
            result = self._completed_from_history(job_id, latest_history)
            if result:
                return result
            raise ComfyUIError(f"unknown or unavailable ComfyUI prompt_id: {job_id}")
''',
        "restart recovery queue fallback",
    )

    # Ignore malformed event payloads rather than raising on data=None/string.
    replace_once(
        files, "comfyui/websocket_monitor.py",
        '''                if message.get("data", {}).get("prompt_id") != prompt_id:
                    continue
''',
        '''                data = message.get("data")
                if not isinstance(data, dict) or data.get("prompt_id") != prompt_id:
                    continue
''',
        "WebSocket event data validation",
    )

    # Model realistic ComfyUI behavior in the test server.
    replace_once(
        files, "dev/fake_comfyui.py",
        '''            def do_GET(self):
                if self.path.startswith("/history/"):
''',
        '''            def do_GET(self):
                if self.path == "/queue":
                    running = []
                    for prompt_id, job in state["jobs"].items():
                        if job["polls"] < 2:
                            running.append([1, prompt_id, job["prompt"], {}, []])
                    return self._json(200, {"queue_running": running, "queue_pending": []})
                if self.path.startswith("/history/"):
''',
        "fake ComfyUI queue endpoint",
    )
    replace_once(
        files, "dev/fake_comfyui.py",
        '''                    if job["polls"] < 2:
                        return self._json(200, {prompt_id: {"outputs": {}}})
''',
        '''                    if job["polls"] < 2:
                        # Running jobs are visible in /queue, not necessarily /history.
                        return self._json(200, {})
''',
        "fake ComfyUI history semantics",
    )

    # Prevent bearer credentials from following an output URL to a different origin.
    replace_once(
        files, "exports.py",
        "import urllib.request\n",
        "import urllib.error\nimport urllib.request\n",
        "output retriever urllib error import",
    )
    replace_once(
        files, "exports.py",
        "class FileOutputRetriever:\n",
        '''class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Block authenticated output requests from redirecting to a different origin."""

    def __init__(self, allowed_base_url: str):
        self.allowed = urlsplit(allowed_base_url)
        super().__init__()

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if (target.scheme.lower(), target.netloc.lower()) != (self.allowed.scheme.lower(), self.allowed.netloc.lower()):
            raise urllib.error.HTTPError(req.full_url, code, "cross-origin output redirect blocked", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class FileOutputRetriever:
''',
        "same-origin redirect handler",
    )
    replace_once(
        files, "exports.py",
        '''                with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as out:
                    shutil.copyfileobj(response, out)
''',
        '''                opener = (
                    urllib.request.build_opener(_SameOriginRedirectHandler(self.allowed_base_url))
                    if self.allowed_base_url
                    else urllib.request.build_opener()
                )
                with opener.open(request, timeout=120) as response, destination.open("wb") as out:
                    shutil.copyfileobj(response, out)
''',
        "origin-checked output opener",
    )

    # Regression tests for queue recovery, TLS enforcement, safe redirects and malformed WebSocket data.
    replace_once(
        files, "tests/test_integration_layers.py",
        "from comfyui.websocket_monitor import ComfyUIWebSocketMonitor, parse_progress_event, websocket_url\n",
        "from comfyui.websocket_monitor import ComfyUIWebSocketMonitor, parse_progress_event, websocket_url\nfrom exports import _SameOriginRedirectHandler\n",
        "redirect handler test import",
    )
    replace_once(
        files, "tests/test_integration_layers.py",
        '''            history = client.history(result["prompt_id"])
            self.assertIn(result["prompt_id"], history)
''',
        '''            history = client.history(result["prompt_id"])
            self.assertEqual(history, {})
            queue = client.queue()
            self.assertTrue(RealComfyUIAdapter._queue_contains_prompt(queue, result["prompt_id"]))
''',
        "HTTP queue contract assertion",
    )
    replace_once(
        files, "tests/test_integration_layers.py",
        "    def test_real_adapter_blocks_until_real_workflow_is_supplied(self):\n",
        '''    def test_real_adapter_restart_recovery_uses_comfyui_queue(self):
        from dev.fake_comfyui import FakeComfyUI
        root = Path(__file__).resolve().parents[1]
        work = Path(tempfile.mkdtemp(prefix="his-risen-queue-recovery-")) / "project"
        shutil.copytree(root, work, ignore=shutil.ignore_patterns("*.sqlite3", "__pycache__"))
        cfg_path = work / "workflows" / "real_presets.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["L25-T2V-SINGLE"]["ready"] = True
        cfg_path.write_text(json.dumps(cfg))
        fake = FakeComfyUI(); fake.start()
        try:
            adapter = RealComfyUIAdapter(work, fake.base_url, timeout=2, job_timeout=10)
            request = {"workflow":{"preset_id":"L25-T2V-SINGLE"},"specification":{"duration":8},"prompt":"QUEUE RECOVERY","profiles":{"reference_assets":[]}}
            job_id = adapter.submit(request, "TAKE-QUEUE-RECOVERY")
            restarted = RealComfyUIAdapter(work, fake.base_url, timeout=2, job_timeout=10)
            resumed = restarted.poll(job_id)
            self.assertEqual(resumed.state, "RUNNING")
            completed = restarted.poll(job_id)
            self.assertEqual(completed.state, "COMPLETED")
        finally:
            fake.stop()

    def test_remote_comfyui_requires_https(self):
        from config.bootstrap import build_controller
        root = Path(__file__).resolve().parents[1]
        work = Path(tempfile.mkdtemp(prefix="his-risen-url-security-")) / "project"
        shutil.copytree(root, work, ignore=shutil.ignore_patterns("*.sqlite3", "__pycache__"))
        runtime_path = work / "config" / "runtime.json"
        runtime = json.loads(runtime_path.read_text())
        runtime["backend"] = "comfyui"
        runtime["comfyui"]["base_url"] = "http://gpu.example:8188"
        runtime_path.write_text(json.dumps(runtime))
        with self.assertRaisesRegex(ValueError, "must use HTTPS"):
            build_controller(work)

    def test_local_comfyui_http_is_allowed(self):
        from config.bootstrap import build_controller
        root = Path(__file__).resolve().parents[1]
        work = Path(tempfile.mkdtemp(prefix="his-risen-local-comfyui-")) / "project"
        shutil.copytree(root, work, ignore=shutil.ignore_patterns("*.sqlite3", "__pycache__"))
        runtime_path = work / "config" / "runtime.json"
        runtime = json.loads(runtime_path.read_text())
        runtime["backend"] = "comfyui"
        runtime["comfyui"]["base_url"] = "http://127.0.0.1:8188"
        runtime_path.write_text(json.dumps(runtime))
        controller = build_controller(work)
        try:
            self.assertEqual(type(controller.adapter).__name__, "RealComfyUIAdapter")
        finally:
            controller.close()

    def test_websocket_monitor_ignores_malformed_data_objects(self):
        class RecordingSocket:
            def __init__(self):
                self.messages = [
                    json.dumps({"type": "status", "data": None}),
                    json.dumps({"type": "status", "data": "not-an-object"}),
                    json.dumps({"type": "progress", "data": {"prompt_id": "P-1", "value": 1, "max": 2}}),
                    json.dumps({"type": "executing", "data": {"prompt_id": "P-1", "node": None}}),
                ]
            def connect(self, url, timeout=None, **kwargs):
                return None
            def recv(self):
                return self.messages.pop(0)
            def close(self):
                return None
        socket = RecordingSocket()
        monitor = ComfyUIWebSocketMonitor("http://127.0.0.1:8188", socket_factory=lambda: socket)
        events = monitor.wait_for_completion("P-1", timeout=1, client_id="C-1")
        self.assertEqual([event["type"] for event in events], ["progress", "executing"])

    def test_output_redirect_handler_blocks_cross_origin_redirects(self):
        handler = _SameOriginRedirectHandler("https://comfy.example")
        request = urllib.request.Request("https://comfy.example/view?filename=clip.mp4")
        with self.assertRaisesRegex(urllib.error.HTTPError, "cross-origin output redirect blocked"):
            handler.redirect_request(request, None, 302, "Found", {}, "https://attacker.example/steal")
        redirected = handler.redirect_request(request, None, 302, "Found", {}, "https://comfy.example/files/clip.mp4")
        self.assertEqual(redirected.full_url, "https://comfy.example/files/clip.mp4")

    def test_real_adapter_blocks_until_real_workflow_is_supplied(self):
''',
        "production integration regression tests",
    )

    temp_dir = Path(tempfile.mkdtemp(prefix="hrf-followup-"))
    temp_zip = ARCHIVE.with_suffix(".followup.tmp.zip")
    extracted = temp_dir / "package"
    extracted.mkdir()
    try:
        for info in infos:
            if info.is_dir():
                continue
            target = extracted / info.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(files[info.filename])

        with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for info in infos:
                if info.is_dir():
                    target.writestr(info, b"")
                else:
                    target.writestr(info, files[info.filename])

        with zipfile.ZipFile(temp_zip, "r") as check:
            bad = check.testzip()
            if bad is not None:
                raise SystemExit(f"Follow-up package ZIP integrity failure: {bad}")

        shutil.move(temp_zip, ARCHIVE)
        digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
        MANIFEST.write_text(f"{digest}  {ARCHIVE.name}\n", encoding="utf-8")
        shutil.rmtree(TEST_ROOT, ignore_errors=True)
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(ARCHIVE, "r") as check:
            check.extractall(TEST_ROOT)
        print("FOLLOWUP_PATCHED_FILES config/bootstrap.py, comfyui/http_client.py, comfyui/adapter.py, comfyui/websocket_monitor.py, dev/fake_comfyui.py, exports.py, tests/test_integration_layers.py")
        print("PACKAGE_BYTES", ARCHIVE.stat().st_size)
        print("PACKAGE_SHA256", digest)
        print("MANIFEST", MANIFEST.read_text(encoding="utf-8").strip())
        print("TEST_ROOT", TEST_ROOT)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_zip.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
