from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "apps" / "his_risen_controller_ltx25_audited_update_2026-10-10 (2).zip"
MANIFEST = Path(str(ARCHIVE) + ".sha256")
ORIGINAL_SHA256 = "df2592a2527f74f6d603357f33f56ad16287bed7f516f4f0a2af993b947d14d9"
TEST_ROOT = Path("/tmp/his-risen-production-readiness")


def replace_once(data: str, old: str, new: str, label: str) -> str:
    count = data.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one {label} insertion point; found {count}")
    return data.replace(old, new, 1)


def patch_text(files: dict[str, bytes], path: str, old: str, new: str, label: str) -> None:
    if path not in files:
        raise SystemExit(f"Required package file is missing: {path}")
    content = files[path].decode("utf-8")
    files[path] = replace_once(content, old, new, label).encode("utf-8")


def main() -> None:
    original_digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    if original_digest != ORIGINAL_SHA256:
        raise SystemExit(f"Unexpected starting package digest: {original_digest}")

    with zipfile.ZipFile(ARCHIVE, "r") as source:
        infos = source.infolist()
        files = {info.filename: source.read(info.filename) for info in infos if not info.is_dir()}

    # Keep WebSocket events routed to the same ComfyUI client_id used by /prompt.
    patch_text(
        files, "comfyui/websocket_monitor.py",
        "    def connect(self, url: str, timeout: float | None = None) -> None: ...",
        "    def connect(self, url: str, timeout: float | None = None, **kwargs: Any) -> None: ...",
        "WebSocket protocol signature",
    )
    patch_text(
        files, "comfyui/websocket_monitor.py",
        """    def __init__(self, base_url: str, socket_factory: Callable[[], WebSocketLike] | None = None, connect_timeout: float = 10.0):
        self.base_url = base_url
        self.connect_timeout = connect_timeout
        self._socket_factory = socket_factory or self._default_factory
""",
        """    def __init__(
        self,
        base_url: str,
        socket_factory: Callable[[], WebSocketLike] | None = None,
        connect_timeout: float = 10.0,
        headers: dict[str, str] | None = None,
    ):
        self.base_url = base_url
        self.connect_timeout = connect_timeout
        self.headers = dict(headers or {})
        self._socket_factory = socket_factory or self._default_factory
""",
        "WebSocket monitor constructor",
    )
    patch_text(
        files, "comfyui/websocket_monitor.py",
        """    def wait_for_completion(self, prompt_id: str, timeout: float) -> list[dict[str, Any]]:
        client_id = str(uuid.uuid4())
        ws = self._socket_factory()
        url = websocket_url(self.base_url, client_id)
""",
        """    def wait_for_completion(
        self,
        prompt_id: str,
        timeout: float,
        client_id: str | None = None,
    ) -> list[dict[str, Any]]:
        # ComfyUI routes execution events to the WebSocket whose clientId matches
        # the client_id submitted with /prompt. A fresh ID here would miss events.
        client_id = client_id or str(uuid.uuid4())
        ws = self._socket_factory()
        url = websocket_url(self.base_url, client_id)
""",
        "WebSocket wait signature",
    )
    patch_text(
        files, "comfyui/websocket_monitor.py",
        "            ws.connect(url, timeout=self.connect_timeout)\n",
        """            connect_kwargs: dict[str, Any] = {"timeout": self.connect_timeout}
            if self.headers:
                connect_kwargs["header"] = [f"{key}: {value}" for key, value in self.headers.items()]
            ws.connect(url, **connect_kwargs)
""",
        "WebSocket connect headers",
    )
    patch_text(
        files, "comfyui/adapter.py",
        "        self.monitor = ComfyUIWebSocketMonitor(self.base_url)\n",
        "        self.monitor = ComfyUIWebSocketMonitor(self.base_url, headers=headers)\n",
        "adapter WebSocket monitor construction",
    )
    patch_text(
        files, "comfyui/adapter.py",
        "            events = self.monitor.wait_for_completion(job_id, timeout=min(2.0, max(0.25, self.job_timeout - elapsed)))\n",
        """            events = self.monitor.wait_for_completion(
                job_id,
                timeout=min(2.0, max(0.25, self.job_timeout - elapsed)),
                client_id=job.get("client_id"),
            )
""",
        "adapter WebSocket client id forwarding",
    )

    # Add portable data root for SQLite, approved exports and updater observation history.
    files["config/data_paths.py"] = b'''from __future__ import annotations

import os
from pathlib import Path


def resolve_data_root(project_root: Path) -> Path:
    """Resolve durable application data outside the extracted application directory.

    HRF_DATA_DIR should point to an attached persistent volume (for example
    /var/data). Setting this variable does not itself make a filesystem durable.
    """
    raw = os.environ.get("HRF_DATA_DIR", "").strip()
    if not raw:
        return Path(project_root).resolve()
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise ValueError("HRF_DATA_DIR must be an absolute path to an attached persistent volume")
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate.resolve()
'''
    patch_text(
        files, "config/bootstrap.py",
        "from pathlib import Path\n\nfrom adapters.mock import MockComfyUIAdapter\n",
        "from pathlib import Path\nimport os\n\nfrom adapters.mock import MockComfyUIAdapter\n",
        "bootstrap os import",
    )
    patch_text(
        files, "config/bootstrap.py",
        "from config.runtime import load_runtime\n",
        "from config.runtime import load_runtime\nfrom config.data_paths import resolve_data_root\n",
        "bootstrap data root import",
    )
    old_bootstrap_block = """    profiles = ProfileRegistry(
        project_root / "profiles" / "characters.json",
        project_root / "profiles" / "voices.json",
        project_root,
    )
    workflows = WorkflowRegistry(project_root / "workflows" / "presets.json")
    capabilities = LTX25CapabilityRegistry(project_root / "workflows" / "ltx25_capabilities.json")
    store = SQLiteStore(project_root / "storage" / "controller.sqlite3")

    retriever = FileOutputRetriever()
    export_manager = ApprovedOutputExportManager(
        project_root,
        store,
        retriever,
        project_root / str(runtime.get("workspace_root", "outputs/production")),
    )

    if selected_backend == "mock":
        adapter = MockComfyUIAdapter(project_root)
    else:
        comfy = runtime.get("comfyui", {})
        if not isinstance(comfy, dict):
            raise ValueError("runtime.comfyui must be an object")
        base_url = str(comfy.get("base_url", "")).strip()
        if not base_url:
            raise ValueError("runtime.comfyui.base_url is required for the comfyui backend")
        headers = comfy.get("headers") if isinstance(comfy.get("headers"), dict) else None
        adapter = RealComfyUIAdapter(
            project_root,
            base_url,
            timeout=float(comfy.get("request_timeout_seconds", 30)),
            job_timeout=float(comfy.get("job_timeout_seconds", 3600)),
            headers=headers,
        )
"""
    new_bootstrap_block = """    data_root = resolve_data_root(project_root)
    comfy: dict[str, Any] = {}
    base_url = ""
    headers: dict[str, str] = {}
    if selected_backend == "comfyui":
        raw_comfy = runtime.get("comfyui", {})
        if not isinstance(raw_comfy, dict):
            raise ValueError("runtime.comfyui must be an object")
        comfy = raw_comfy
        base_url = os.environ.get("HRF_COMFYUI_BASE_URL", str(comfy.get("base_url", ""))).strip()
        if not base_url:
            raise ValueError("HRF_COMFYUI_BASE_URL or runtime.comfyui.base_url is required for the comfyui backend")
        raw_headers = comfy.get("headers") if isinstance(comfy.get("headers"), dict) else {}
        headers = {str(key): str(value) for key, value in raw_headers.items()}
        api_key = os.environ.get("HRF_COMFYUI_API_KEY", "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

    profiles = ProfileRegistry(
        project_root / "profiles" / "characters.json",
        project_root / "profiles" / "voices.json",
        project_root,
    )
    workflows = WorkflowRegistry(project_root / "workflows" / "presets.json")
    capabilities = LTX25CapabilityRegistry(project_root / "workflows" / "ltx25_capabilities.json")
    store = SQLiteStore(data_root / "storage" / "controller.sqlite3")

    workspace_setting = Path(str(runtime.get("workspace_root", "outputs/production"))).expanduser()
    workspace_root = workspace_setting if workspace_setting.is_absolute() else data_root / workspace_setting
    retriever = (
        FileOutputRetriever(headers=headers, allowed_base_url=base_url)
        if selected_backend == "comfyui"
        else FileOutputRetriever()
    )
    export_manager = ApprovedOutputExportManager(
        project_root,
        store,
        retriever,
        workspace_root,
    )

    if selected_backend == "mock":
        adapter = MockComfyUIAdapter(project_root)
    else:
        adapter = RealComfyUIAdapter(
            project_root,
            base_url,
            timeout=float(comfy.get("request_timeout_seconds", 30)),
            job_timeout=float(comfy.get("job_timeout_seconds", 3600)),
            headers=headers,
        )
"""
    patch_text(files, "config/bootstrap.py", old_bootstrap_block, new_bootstrap_block, "bootstrap storage/backend block")

    patch_text(
        files, "updates/check.py",
        "def check_updates(root: Path, timeout: float = 8.0) -> dict:\n",
        "def check_updates(root: Path, timeout: float = 8.0, *, state_root: Path | None = None) -> dict:\n",
        "updater state root signature",
    )
    patch_text(
        files, "updates/check.py",
        "    state_path = root / STATE_RELATIVE_PATH\n",
        "    state_path = (Path(state_root).resolve() if state_root is not None else root) / STATE_RELATIVE_PATH\n",
        "updater state file path",
    )
    patch_text(
        files, "director_console.py",
        "from config.bootstrap import build_controller\n",
        "from config.bootstrap import build_controller\nfrom config.data_paths import resolve_data_root\n",
        "director console data root import",
    )
    patch_text(
        files, "director_console.py",
        "        return check_updates(self.root)\n",
        "        return check_updates(self.root, state_root=resolve_data_root(self.root))\n",
        "director console updater persistence",
    )

    # Restrict output credentials to the explicitly configured ComfyUI origin.
    patch_text(
        files, "exports.py",
        "from pathlib import Path\nfrom typing import Any, Protocol\n",
        "from pathlib import Path\nfrom typing import Any, Protocol\nfrom urllib.parse import urlsplit\n",
        "export URL parser import",
    )
    patch_text(
        files, "exports.py",
        """class FileOutputRetriever:
    \"\"\"Retrieves media from a local source_path or an HTTP URL.\"\"\"

    def retrieve(self, media: dict[str, Any], destination: Path) -> dict[str, Any]:
""",
        """class FileOutputRetriever:
    \"\"\"Retrieves media from local files or an allow-listed HTTP origin.\"\"\"

    def __init__(self, headers: dict[str, str] | None = None, allowed_base_url: str | None = None):
        self.headers = dict(headers or {})
        self.allowed_base_url = allowed_base_url

    def retrieve(self, media: dict[str, Any], destination: Path) -> dict[str, Any]:
""",
        "output retriever constructor",
    )
    patch_text(
        files, "exports.py",
        """        elif url:
            try:
                with urllib.request.urlopen(str(url), timeout=120) as response, destination.open("wb") as out:
                    shutil.copyfileobj(response, out)
""",
        """        elif url:
            try:
                request = urllib.request.Request(str(url))
                if self.allowed_base_url:
                    allowed = urlsplit(self.allowed_base_url)
                    candidate = urlsplit(str(url))
                    if (candidate.scheme, candidate.netloc) != (allowed.scheme, allowed.netloc):
                        raise ExportError("output URL does not belong to the configured ComfyUI origin")
                    for key, value in self.headers.items():
                        request.add_header(key, value)
                elif self.headers:
                    raise ExportError("authenticated output retrieval requires an explicitly configured ComfyUI origin")
                with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as out:
                    shutil.copyfileobj(response, out)
""",
        "output retriever origin and auth enforcement",
    )

    # Keep unauthenticated server variants on loopback; remote MCP needs a bearer token.
    patch_text(
        files, "api/server.py",
        """    def __init__(self, controller: Any, host: str = "127.0.0.1", port: int = 8189):
        self.controller = controller
""",
        """    def __init__(self, controller: Any, host: str = "127.0.0.1", port: int = 8189):
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("the unauthenticated controller API may only bind to loopback")
        self.controller = controller
""",
        "REST API loopback-only guard",
    )
    patch_text(
        files, "mcp_server.py",
        """    def __init__(self, controller: Any, host: str = "127.0.0.1", port: int = 8190, token: str | None = None):
        self.controller = controller
""",
        """    def __init__(self, controller: Any, host: str = "127.0.0.1", port: int = 8190, token: str | None = None):
        if host not in {"127.0.0.1", "localhost", "::1"} and not (token and token.strip()):
            raise ValueError("a non-empty HRF_MCP_BEARER_TOKEN is required for non-loopback MCP binding")
        self.controller = controller
""",
        "MCP public-bind bearer-token guard",
    )

    # Add focused tests.
    patch_text(
        files, "tests/test_integration_layers.py",
        "import json\nimport shutil\n",
        "import json\nimport os\nimport shutil\n",
        "integration test os import",
    )
    patch_text(
        files, "tests/test_integration_layers.py",
        "import urllib.request\nfrom pathlib import Path\n",
        "import urllib.request\nfrom pathlib import Path\nfrom unittest import mock\n",
        "integration test mock import",
    )
    patch_text(
        files, "tests/test_integration_layers.py",
        "from comfyui.websocket_monitor import parse_progress_event, websocket_url\n",
        "from comfyui.websocket_monitor import ComfyUIWebSocketMonitor, parse_progress_event, websocket_url\n",
        "WebSocket monitor test import",
    )
    ws_test = """    def test_websocket_monitor_uses_prompt_client_id_and_auth_headers(self):
        class RecordingSocket:
            def __init__(self):
                self.url = None
                self.kwargs = {}
                self.messages = [
                    json.dumps({"type": "progress", "data": {"prompt_id": "PROMPT-1", "value": 1, "max": 2}}),
                    json.dumps({"type": "executing", "data": {"prompt_id": "PROMPT-1", "node": None}}),
                ]
            def connect(self, url, timeout=None, **kwargs):
                self.url = url
                self.kwargs = kwargs
            def recv(self):
                return self.messages.pop(0)
            def close(self):
                return None

        socket = RecordingSocket()
        monitor = ComfyUIWebSocketMonitor(
            "https://comfy.example",
            socket_factory=lambda: socket,
            headers={"Authorization": "Bearer test-secret"},
        )
        events = monitor.wait_for_completion("PROMPT-1", timeout=1, client_id="stable-client")
        self.assertEqual(len(events), 2)
        self.assertEqual(socket.url, "wss://comfy.example/ws?clientId=stable-client")
        self.assertEqual(socket.kwargs["header"], ["Authorization: Bearer test-secret"])

"""
    patch_text(
        files, "tests/test_integration_layers.py",
        "    def test_http_client_contract_against_fake_server(self):\n",
        ws_test + "    def test_http_client_contract_against_fake_server(self):\n",
        "WebSocket monitor regression test",
    )
    adapter_test = """    def test_real_adapter_forwards_submission_client_id_to_websocket_monitor(self):
        from dev.fake_comfyui import FakeComfyUI
        root = Path(__file__).resolve().parents[1]
        work = Path(tempfile.mkdtemp(prefix="his-risen-websocket-client-")) / "project"
        shutil.copytree(root, work, ignore=shutil.ignore_patterns("*.sqlite3", "__pycache__"))
        cfg_path = work / "workflows" / "real_presets.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["L25-T2V-SINGLE"]["ready"] = True
        cfg_path.write_text(json.dumps(cfg))
        fake = FakeComfyUI()
        fake.start()
        try:
            adapter = RealComfyUIAdapter(work, fake.base_url, timeout=2, job_timeout=10)
            request = {"workflow": {"preset_id": "L25-T2V-SINGLE"}, "specification": {"duration": 8},
                       "prompt": "WEBSOCKET CLIENT TEST", "profiles": {"reference_assets": []}}
            job_id = adapter.submit(request, "TAKE-WEBSOCKET-CLIENT")
            expected_client_id = adapter.jobs[job_id]["client_id"]
            with mock.patch.object(adapter.monitor, "wait_for_completion", return_value=[]) as wait:
                adapter.poll(job_id)
            self.assertEqual(wait.call_args.kwargs["client_id"], expected_client_id)
        finally:
            fake.stop()

"""
    patch_text(
        files, "tests/test_integration_layers.py",
        "    def test_real_adapter_uploads_reference_and_maps_returned_name(self):\n",
        adapter_test + "    def test_real_adapter_uploads_reference_and_maps_returned_name(self):\n",
        "adapter WebSocket client-id regression test",
    )
    api_guard_test = """    def test_unauthenticated_controller_api_refuses_non_loopback_binding(self):
        with self.assertRaisesRegex(ValueError, "only bind to loopback"):
            ControllerHTTPServer(object(), host="0.0.0.0", port=0)

"""
    patch_text(
        files, "tests/test_integration_layers.py",
        "    def test_api_models_strictness(self):\n",
        api_guard_test + "    def test_api_models_strictness(self):\n",
        "REST API bind safety test",
    )
    mcp_guard_test = """    def test_mcp_server_requires_bearer_token_on_non_loopback_binding(self):
        from mcp_server import MCPHTTPServer
        with self.assertRaisesRegex(ValueError, "HRF_MCP_BEARER_TOKEN"):
            MCPHTTPServer(self.controller, host="0.0.0.0", port=0, token=None)

"""
    patch_text(
        files, "tests/test_integration_layers.py",
        "    def _post(self, payload, headers=None):\n",
        mcp_guard_test + "    def _post(self, payload, headers=None):\n",
        "MCP server bind safety test",
    )

    files["tests/test_persistent_data_root.py"] = b'''from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from config.bootstrap import build_controller
from config.data_paths import resolve_data_root
from updates.check import check_updates

ROOT = Path(__file__).resolve().parents[1]


class PersistentDataRootTests(unittest.TestCase):
    def _project_copy(self, parent: Path) -> Path:
        project = parent / "project"
        shutil.copytree(ROOT, project, ignore=shutil.ignore_patterns("*.sqlite3", "__pycache__", "*.pyc"))
        return project

    def test_hrf_data_dir_moves_database_and_export_workspace_to_mounted_volume(self):
        with tempfile.TemporaryDirectory(prefix="his-risen-data-root-") as folder:
            parent = Path(folder)
            project = self._project_copy(parent)
            data_root = parent / "mounted-volume"
            with mock.patch.dict(os.environ, {"HRF_DATA_DIR": str(data_root)}):
                controller = build_controller(project, backend="mock")
                try:
                    self.assertTrue((data_root / "storage" / "controller.sqlite3").is_file())
                    self.assertEqual(
                        controller.export_manager.workspace_root,
                        (data_root / "outputs" / "production").resolve(),
                    )
                    self.assertFalse((project / "storage" / "controller.sqlite3").exists())
                finally:
                    controller.close()

    def test_hrf_data_dir_must_be_absolute(self):
        with mock.patch.dict(os.environ, {"HRF_DATA_DIR": "relative-data"}):
            with self.assertRaisesRegex(ValueError, "absolute path"):
                resolve_data_root(ROOT)

    def test_updater_observation_cache_can_use_the_same_persistent_root(self):
        with tempfile.TemporaryDirectory(prefix="his-risen-updater-data-") as folder:
            parent = Path(folder)
            project = self._project_copy(parent)
            data_root = parent / "mounted-volume"
            (project / "workflows" / "ltx25_capabilities.json").write_text(
                json.dumps({"manifest_version": "test", "model_family": "LTX-2.5"}),
                encoding="utf-8",
            )

            def fake_request(url: str, timeout: float):
                if "api.github.com" in url:
                    body = json.dumps({"tag_name": "v-test", "published_at": "2026-11-01T00:00:00Z", "html_url": "https://example.invalid", "body": "test"}).encode()
                    return 200, body, "application/json"
                if "huggingface.co/api/models" in url:
                    body = json.dumps({"sha": "test-revision", "lastModified": "2026-11-01T00:00:00Z"}).encode()
                    return 200, body, "application/json"
                return 200, b"documentation", "text/html"

            with mock.patch("updates.check._request", side_effect=fake_request):
                check_updates(project, state_root=data_root)
            self.assertTrue((data_root / "storage" / "update_check_state.json").is_file())
            self.assertFalse((project / "storage" / "update_check_state.json").exists())


if __name__ == "__main__":
    unittest.main()
'''

    patch_text(
        files, ".env.example",
        "# REQUIRED: 6-12 digit private Director PIN\nHRF_DIRECTOR_PIN=CHANGE_ME\n",
        """# REQUIRED: 6-12 digit private Director PIN
HRF_DIRECTOR_PIN=CHANGE_ME

# Optional: set only after attaching a persistent disk/volume at this exact path.
# It stores the SQLite database, approved exports and updater observation cache.
# HRF_DATA_DIR=/var/data

# Set these only when connecting a real, secured ComfyUI server.
# HRF_COMFYUI_BASE_URL=https://your-comfyui-endpoint.example
# HRF_COMFYUI_API_KEY=CHANGE_ME
""",
        "environment example",
    )
    patch_text(
        files, "docs/REAL_COMFYUI.md",
        "## What is required outside the controller\n",
        """## Persistent storage before remote production

The controller can place its SQLite database, approved video exports, and updater observation history under HRF_DATA_DIR. Set this only after a durable volume is actually attached and mounted at that path (for example /var/data). An environment variable by itself does not make Render's ephemeral filesystem persistent. Keep the volume attached to a single controller instance when using SQLite; use a managed database/object-storage architecture before multi-instance scaling.

For a secured ComfyUI endpoint, set HRF_COMFYUI_BASE_URL and keep any bearer credential in the secret environment variable HRF_COMFYUI_API_KEY, not in Git. HTTP, WebSocket and output-file retrieval use the configured credential. The unauthenticated local REST API is loopback-only, and the MCP bridge requires a bearer token when bound beyond loopback.

## What is required outside the controller
""",
        "real ComfyUI storage and security documentation",
    )

    temp_zip = ARCHIVE.with_suffix(".production-readiness.tmp.zip")
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(ARCHIVE, "r") as source, zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED) as target:
            seen: set[str] = set()
            for info in source.infolist():
                if info.is_dir():
                    target.writestr(info, b"")
                    continue
                target.writestr(info, files[info.filename])
                seen.add(info.filename)
            for name, data in files.items():
                if name not in seen:
                    target.writestr(name, data)

        with zipfile.ZipFile(temp_zip, "r") as check:
            bad = check.testzip()
            if bad is not None:
                raise SystemExit(f"Rebuilt ZIP failed integrity check: {bad}")
            check.extractall(TEST_ROOT)

        shutil.move(temp_zip, ARCHIVE)
        digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
        MANIFEST.write_text(f"{digest}  {ARCHIVE.name}\n", encoding="utf-8")
        print("PACKAGE_BYTES", ARCHIVE.stat().st_size)
        print("PACKAGE_SHA256", digest)
        print("MANIFEST", MANIFEST.read_text(encoding="utf-8").strip())
        print("TEST_ROOT", TEST_ROOT)
    finally:
        temp_zip.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
