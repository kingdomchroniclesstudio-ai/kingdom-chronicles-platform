from __future__ import annotations

import json
import zipfile
from pathlib import PurePosixPath


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 1:
        return text.replace(old, new, 1)
    if count == 0 and new in text:
        return text
    raise RuntimeError(f"Expected exactly one {label} insertion point; found {count}.")


def patch_text(entries: dict[str, tuple[zipfile.ZipInfo, bytes]], path: str,
               replacements: list[tuple[str, str, str]]) -> None:
    if path not in entries:
        raise RuntimeError(f"Required package file is missing: {path}")
    info, raw = entries[path]
    content = raw.decode("utf-8")
    for old, new, label in replacements:
        content = replace_once(content, old, new, label)
    entries[path] = (info, content.encode("utf-8"))


def _test_source() -> str:
    return r'''from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from director_console import DirectorConsole, Handler, INDEX_HTML


class _FakeConnection:
    def execute(self, *args, **kwargs):
        return []


class _FakeStore:
    def __init__(self):
        self.connection = _FakeConnection()
        self._lock = threading.RLock()
        self.requests = {}

    def get_submission_request(self, request_id):
        return self.requests.get(request_id)


class _FakeHTTP:
    def _request_json(self, method, path, payload=None, timeout=None):
        if path == "/system_stats":
            return {"devices": [{"name": "NVIDIA A100", "type": "cuda", "vram_total": 80 * 1024 ** 3}]}
        if path == "/object_info":
            return {"TestLTXNode": {"input": {"required": {"prompt": ["STRING"]}}}}
        raise AssertionError(f"Unexpected ComfyUI preflight request: {method} {path}")


class MockComfyUIAdapter:
    pass


class RealComfyUIAdapter:
    def __init__(self):
        self.http = _FakeHTTP()


class _FakeController:
    def __init__(self, root: Path):
        self.adapter = MockComfyUIAdapter()
        self.root = root
        self.store = _FakeStore()
        self.auto_export_approved = False
        self.generated = []
        self.takes = {}

    def generate(self, specification, submission_request_id=None, submission_payload_hash=None, return_created=False):
        if submission_request_id:
            existing = self.store.get_submission_request(submission_request_id)
            if existing:
                if existing["payload_hash"] != submission_payload_hash:
                    raise ValueError("This request_id was already used with a different shot specification.")
                take = self.takes[existing["take_id"]]
                return (take, False) if return_created else take
        self.generated.append(json.loads(json.dumps(specification)))
        take = {
            "take_id": f"TAKE-{len(self.generated):03d}",
            "film_id": specification["film_id"],
            "scene_id": specification["scene_id"],
            "shot_id": specification["shot_id"],
            "status": "SUBMITTED",
        }
        self.takes[take["take_id"]] = take
        if submission_request_id:
            self.store.requests[submission_request_id] = {
                "request_id": submission_request_id,
                "payload_hash": submission_payload_hash,
                "take_id": take["take_id"],
            }
        return (take, True) if submission_request_id and return_created else take

    def get_take(self, take_id):
        return self.takes[take_id]


class RealShotSubmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="his-risen-real-shot-test-")
        self.root = Path(self.temp.name)
        (self.root / "config").mkdir()
        (self.root / "workflows" / "real").mkdir(parents=True)
        self.template = {
            "film_id": "HRF-MEX-001",
            "scene_id": "SC016",
            "shot_id": "SC016-SH004",
            "shot_type": "SINGLE-SHOT",
            "character_ids": ["CHR-MOS"],
            "voice_profile_ids": ["VP-MOS"],
            "environment": "Night shoreline.",
            "action": "Moses raises his staff.",
            "camera": "Medium frontal shot.",
            "lighting": "Natural moonlight.",
            "audio": "Wind and distant water.",
            "dialogue": [],
            "continuity": "Keep Moses' approved appearance and staff.",
            "duration": 8,
            "reference_assets": [],
            "status": "READY",
            "resolution": "1440p",
            "aspect_ratio": "16:9",
            "frame_rate": 24,
            "quality_preset": "LTX-2.5 Fast workhorse",
        }
        (self.root / "config" / "test_shot.json").write_text(json.dumps(self.template), encoding="utf-8")
        self.workflow_path = "workflows/real/t2v.api.json"
        self.mapping_path = "workflows/real/t2v.mapping.json"
        (self.root / self.workflow_path).write_text(
            json.dumps({"1": {"class_type": "TestLTXNode", "inputs": {
                "prompt": "", "duration": 8, "seed": 0, "width": 2560, "height": 1440, "fps": 24
            }}}),
            encoding="utf-8",
        )
        self.mapping = {
            key: {"node_id": "1", "input": key, "required": True}
            for key in ("prompt", "duration", "seed", "width", "height", "fps")
        }
        (self.root / self.mapping_path).write_text(json.dumps(self.mapping), encoding="utf-8")
        self.presets_path = self.root / "workflows" / "real_presets.json"
        self.presets_path.write_text(json.dumps({
            "L25-T2V-SINGLE": {
                "ready": False,
                "workflow_file": self.workflow_path,
                "mapping_file": self.mapping_path,
            }
        }), encoding="utf-8")
        self.controller = _FakeController(self.root)
        (self.root / "storage").mkdir()
        database_path = self.root / "storage" / "controller.sqlite3"
        database_path.touch()
        self.controller.store.path = database_path
        self._old_data_root = os.environ.get("HRF_DATA_DIR")
        os.environ["HRF_DATA_DIR"] = str(self.root)
        self.console = DirectorConsole(self.controller, "123456", self.root)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.console = self.console
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.origin = self.base
        self.cookie = f"hrf_director_session={self.console.sessions.create()}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.console.stop()
        if self._old_data_root is None:
            os.environ.pop("HRF_DATA_DIR", None)
        else:
            os.environ["HRF_DATA_DIR"] = self._old_data_root
        self.temp.cleanup()

    def request(self, method, path, payload=None, *, auth=True, origin=True):
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Cookie"] = self.cookie
        if origin:
            headers["Origin"] = self.origin
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_new_shot_ui_has_explicit_cost_confirmation_and_safe_gate(self):
        self.assertIn("New real shot submission", INDEX_HTML)
        self.assertIn("confirmRealCost", INDEX_HTML)
        self.assertIn("submitRealShot", INDEX_HTML)
        self.assertIn("Mock Mode", INDEX_HTML)

    def test_shot_template_and_readiness_require_authenticated_session(self):
        self.assertEqual(self.request("GET", "/api/shot-template", auth=False)[0], 401)
        self.assertEqual(self.request("GET", "/api/generation-readiness", auth=False)[0], 401)
        status, template = self.request("GET", "/api/shot-template")
        self.assertEqual(status, 200)
        self.assertEqual(template["data"]["generation_mode"], "TEXT_TO_VIDEO")

    def test_server_requires_explicit_cost_acknowledgement(self):
        payload = {
            "request_id": str(uuid.uuid4()),
            "specification": self.template,
            "cost_acknowledged": False,
        }
        status, result = self.request("POST", "/api/shots/generate", payload)
        self.assertEqual(status, 409)
        self.assertIn("cost acknowledgement", result["error"])
        self.assertEqual(self.controller.generated, [])

    def test_mock_mode_refuses_real_shot_submission_without_calling_controller(self):
        request_id = str(uuid.uuid4())
        payload = {"request_id": request_id, "specification": self.template, "cost_acknowledged": True}
        status, result = self.request("POST", "/api/shots/generate", payload)
        self.assertEqual(status, 409)
        self.assertFalse(result["ok"])
        self.assertEqual(self.controller.generated, [])
        status, readiness = self.request("GET", "/api/generation-readiness")
        self.assertEqual(status, 200)
        self.assertFalse(readiness["data"]["enabled"])
        self.assertTrue(readiness["data"]["mock_mode"])

    def test_missing_or_untrusted_origin_is_rejected(self):
        payload = {"request_id": str(uuid.uuid4()), "specification": self.template}
        self.assertEqual(self.request("POST", "/api/shots/generate", payload, origin=False)[0], 403)
        req = Request(
            self.base + "/api/shots/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Cookie": self.cookie,
                "Origin": "https://attacker.invalid",
            },
            method="POST",
        )
        try:
            urlopen(req, timeout=3)
            status = 200
        except HTTPError as exc:
            status = exc.code
        self.assertEqual(status, 403)
        self.assertEqual(self.controller.generated, [])

    def test_real_t2v_preflight_and_idempotent_submission(self):
        self.controller.adapter = RealComfyUIAdapter()
        cfg = json.loads(self.presets_path.read_text(encoding="utf-8"))
        cfg["L25-T2V-SINGLE"]["ready"] = True
        self.presets_path.write_text(json.dumps(cfg), encoding="utf-8")

        from unittest.mock import patch
        with patch.object(Path, "is_mount", autospec=True, side_effect=lambda path: path.resolve() == self.root.resolve()):
            status, readiness = self.request("GET", "/api/generation-readiness")
            self.assertEqual(status, 200)
            self.assertTrue(readiness["data"]["enabled"])
            self.assertTrue(readiness["data"]["persistent_storage_ready"])
            self.assertEqual(readiness["data"]["gpu_vram_gib"], 80)

            request_id = str(uuid.uuid4())
            spec = dict(self.template)
            spec["generation_mode"] = "TEXT_TO_VIDEO"
            spec["seed"] = 0
            payload = {"request_id": request_id, "specification": spec, "cost_acknowledged": True}
            status, first = self.request("POST", "/api/shots/generate", payload)
            self.assertEqual(status, 202)
            self.assertTrue(first["data"]["created"])
            self.assertEqual(len(self.controller.generated), 1)

            status, retry = self.request("POST", "/api/shots/generate", payload)
            self.assertEqual(status, 202)
            self.assertTrue(retry["data"]["reused"])
            self.assertEqual(len(self.controller.generated), 1)

        changed = dict(spec)
        changed["action"] = "A different action."
        status, conflict = self.request(
            "POST",
            "/api/shots/generate",
            {"request_id": request_id, "specification": changed, "cost_acknowledged": True},
        )
        self.assertEqual(status, 409)
        self.assertEqual(len(self.controller.generated), 1)

    def test_real_preflight_requires_all_director_settings_to_be_mapped(self):
        from unittest.mock import patch
        self.controller.adapter = RealComfyUIAdapter()
        cfg = json.loads(self.presets_path.read_text(encoding="utf-8"))
        cfg["L25-T2V-SINGLE"]["ready"] = True
        self.presets_path.write_text(json.dumps(cfg), encoding="utf-8")
        self.mapping["fps"]["required"] = False
        (self.root / self.mapping_path).write_text(json.dumps(self.mapping), encoding="utf-8")
        with patch.object(Path, "is_mount", autospec=True, side_effect=lambda path: path.resolve() == self.root.resolve()):
            readiness = self.console.real_shot_readiness(force=True)
        self.assertFalse(readiness["enabled"])
        self.assertIn("fps", readiness["reason"])

    def test_real_preflight_refuses_ephemeral_storage(self):
        from unittest.mock import patch
        self.controller.adapter = RealComfyUIAdapter()
        cfg = json.loads(self.presets_path.read_text(encoding="utf-8"))
        cfg["L25-T2V-SINGLE"]["ready"] = True
        self.presets_path.write_text(json.dumps(cfg), encoding="utf-8")
        with patch.dict(os.environ, {"HRF_DATA_DIR": str(self.root)}):
            with patch.object(Path, "is_mount", autospec=True, return_value=False):
                readiness = self.console.real_shot_readiness(force=True)
        self.assertFalse(readiness["enabled"])
        self.assertIn("mounted persistent volume", readiness["reason"])

    def test_resolution_and_frame_rate_are_forwarded_to_comfyui_mapping(self):
        from comfyui.adapter import RealComfyUIAdapter
        request = {
            "prompt": "Moses raises his staff.",
            "specification": {
                "duration": 8,
                "seed": 1234,
                "resolution": "1440p",
                "aspect_ratio": "16:9",
                "frame_rate": 24,
            },
        }
        values = RealComfyUIAdapter._mapping_values(None, request, {})
        self.assertEqual(values["width"], 2560)
        self.assertEqual(values["height"], 1440)
        self.assertEqual(values["fps"], 24)
        self.assertEqual(values["seed"], 1234)

    def test_non_16_by_9_resolution_is_rejected_by_first_t2v_mapper(self):
        from comfyui.adapter import RealComfyUIAdapter
        from workflows.loader import WorkflowTemplateError
        request = {
            "prompt": "Moses raises his staff.",
            "specification": {
                "duration": 8,
                "resolution": "1440p",
                "aspect_ratio": "9:16",
                "frame_rate": 24,
            },
        }
        with self.assertRaises(WorkflowTemplateError):
            RealComfyUIAdapter._mapping_values(None, request, {})

    def test_real_submission_rejects_missing_seed_before_take_creation(self):
        self.controller.adapter = RealComfyUIAdapter()
        spec = dict(self.template)
        spec["generation_mode"] = "TEXT_TO_VIDEO"
        spec.pop("seed", None)
        status, result = self.request(
            "POST",
            "/api/shots/generate",
            {"request_id": str(uuid.uuid4()), "specification": spec, "cost_acknowledged": True},
        )
        self.assertEqual(status, 409)
        self.assertIn("seed", result["error"])
        self.assertEqual(self.controller.generated, [])

    def test_real_submission_rejects_non_t2v_and_invalid_specification(self):
        self.controller.adapter = RealComfyUIAdapter()
        cfg = json.loads(self.presets_path.read_text(encoding="utf-8"))
        cfg["L25-T2V-SINGLE"]["ready"] = True
        self.presets_path.write_text(json.dumps(cfg), encoding="utf-8")
        invalid = dict(self.template)
        invalid["generation_mode"] = "FIRST_LAST_FRAME"
        status, result = self.request(
            "POST",
            "/api/shots/generate",
            {"request_id": str(uuid.uuid4()), "specification": invalid, "cost_acknowledged": True},
        )
        self.assertEqual(status, 409)
        self.assertEqual(self.controller.generated, [])


if __name__ == "__main__":
    unittest.main()
'''


def apply(entries: dict[str, tuple[zipfile.ZipInfo, bytes]]) -> None:
    """Patch the deployable controller package with a guarded, authenticated T2V path."""
    patch_text(
        entries,
        "director_console.py",
        [
            ("import argparse\nimport json\n", "import argparse\nimport hashlib\nimport json\n", "shot idempotency hash import"),
            ("import time\nfrom http import HTTPStatus\n", "import time\nimport uuid\nfrom http import HTTPStatus\n", "shot request ID import"),
            (
                "from config.bootstrap import build_controller\n",
                "from config.bootstrap import build_controller\nfrom models.specification import ValidationError, validate_specification\n",
                "shot request validation imports",
            ),
            (
                "        self.sessions = SessionStore()\n        self.limiter = LoginLimiter()\n        self._autopoll_stop = threading.Event()\n",
                "        self.sessions = SessionStore()\n        self.limiter = LoginLimiter()\n        self._generation_lock = threading.RLock()\n        self._generation_requests: dict[str, dict[str, str]] = {}\n        self._readiness_lock = threading.RLock()\n        self._readiness_cache: tuple[float, dict[str, Any]] | None = None\n        self._autopoll_stop = threading.Event()\n",
                "director console guarded submission state",
            ),
        ],
    )

    patch_text(
        entries,
        "storage/sqlite_store.py",
        [(
            "        path.parent.mkdir(parents=True,exist_ok=True); self.connection=sqlite3.connect(path,isolation_level=None,timeout=10,check_same_thread=False); self._lock=RLock();",
            "        path.parent.mkdir(parents=True,exist_ok=True); self.path=path.resolve(); self.connection=sqlite3.connect(path,isolation_level=None,timeout=10,check_same_thread=False); self._lock=RLock();",
            "record durable SQLite database path",
        )],
    )

    patch_text(
        entries,
        "storage/sqlite_store.py",
        [
            (
                'CREATE INDEX IF NOT EXISTS exports_take ON exports(take_id);"""',
                'CREATE INDEX IF NOT EXISTS exports_take ON exports(take_id); CREATE TABLE IF NOT EXISTS submission_requests(request_id TEXT PRIMARY KEY,payload_hash TEXT NOT NULL,take_id TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,FOREIGN KEY(take_id) REFERENCES takes(take_id)); CREATE INDEX IF NOT EXISTS submission_requests_take ON submission_requests(take_id);"""',
                "durable submission idempotency schema",
            ),
            (
                "def reserve_take(self,snapshot,parent_take_id=None):",
                "def reserve_take(self,snapshot,parent_take_id=None,submission_request_id=None,submission_payload_hash=None):",
                "durable take reservation signature",
            ),
            (
                "        with self._transaction():\n            parent_reason=None",
                """        with self._transaction():
            if submission_request_id is not None:
                if not submission_payload_hash:
                    raise ValueError("submission_payload_hash is required with submission_request_id.")
                existing=self.connection.execute("SELECT payload_hash,take_id FROM submission_requests WHERE request_id=?",(submission_request_id,)).fetchone()
                if existing:
                    if existing["payload_hash"] != submission_payload_hash:
                        raise ValueError("This request_id was already used with a different shot specification.")
                    return existing["take_id"], False
            elif submission_payload_hash is not None:
                raise ValueError("submission_payload_hash requires submission_request_id.")
            parent_reason=None""",
                "atomic durable request lookup",
            ),
        ],
    )

    # Insert the durable request row immediately before reserve_take returns.
    # Keep this transformation resilient to whitespace differences in the packaged controller.
    store_info, store_raw = entries["storage/sqlite_store.py"]
    store_source = store_raw.decode("utf-8")
    reserve_start = store_source.index("    def reserve_take(")
    reserve_end = store_source.index("    def record_submission(", reserve_start)
    reserve_method = store_source[reserve_start:reserve_end]
    if "INSERT INTO submission_requests" not in reserve_method:
        return_pos = reserve_method.rfind("return take_id")
        if return_pos < 0:
            raise RuntimeError("Could not locate reserve_take return statement for durable idempotency.")
        line_start = reserve_method.rfind("\n", 0, return_pos) + 1
        line_end = reserve_method.find("\n", return_pos)
        if line_end < 0:
            line_end = len(reserve_method)
        original_line = reserve_method[line_start:line_end]
        prefix = original_line[:original_line.rfind("return take_id")].strip().rstrip(";")
        if not prefix:
            raise RuntimeError("Could not preserve the PENDING progress event while adding durable idempotency.")
        replacement_line = (
            "            " + prefix + "\n"
            "            if submission_request_id is not None:\n"
            "                self.connection.execute(\"INSERT INTO submission_requests (request_id,payload_hash,take_id,created_at) VALUES (?,?,?,?)\",(submission_request_id,submission_payload_hash,take_id,timestamp))\n"
            "            return (take_id, True) if submission_request_id is not None else take_id"
        )
        reserve_method = reserve_method[:line_start] + replacement_line + reserve_method[line_end:]
        store_source = store_source[:reserve_start] + reserve_method + store_source[reserve_end:]
        entries["storage/sqlite_store.py"] = (store_info, store_source.encode("utf-8"))

    patch_text(
        entries,
        "storage/sqlite_store.py",
        [(
            "    def record_submission(self,take_id,job_id):\n",
            """    def get_submission_request(self,request_id):
        with self._lock:
            row=self.connection.execute("SELECT request_id,payload_hash,take_id,created_at FROM submission_requests WHERE request_id=?",(request_id,)).fetchone()
            return dict(row) if row else None

    def record_submission(self,take_id,job_id):
""",
            "durable submission request lookup method",
        )],
    )

    controller_info, controller_raw = entries["controller/service.py"]
    controller_source = controller_raw.decode("utf-8")
    generate_start = controller_source.index("    def generate(")
    generate_end = controller_source.index("    def _submit(", generate_start)
    generate_method = controller_source[generate_start:generate_end]
    if "submission_request_id" not in generate_method:
        signature_end = generate_method.find("\n")
        if signature_end < 0:
            raise RuntimeError("Controller.generate signature could not be parsed.")
        body = generate_method[signature_end + 1:]
        reservation_index = body.find("self.store.reserve_take(snapshot)")
        if reservation_index < 0:
            raise RuntimeError("Controller.generate reservation point not found; refusing to replace the method.")
        assignment_start = body.rfind("take_id=", 0, reservation_index)
        if assignment_start < 0:
            raise RuntimeError("Controller.generate take reservation assignment could not be located.")
        prefix = body[:assignment_start]
        new_signature = "    def generate(self,specification,submission_request_id=None,submission_payload_hash=None,return_created=False):"
        new_body = (
            prefix
            + "reservation=self.store.reserve_take(snapshot,submission_request_id=submission_request_id,submission_payload_hash=submission_payload_hash)\n"
            + "        if submission_request_id is not None:\n"
            + "            take_id,created=reservation\n"
            + "            if not created:\n"
            + "                existing=self.store.get_take(take_id)\n"
            + "                return (existing,False) if return_created else existing\n"
            + "        else:\n"
            + "            take_id=reservation\n"
            + "            created=True\n"
            + "        take=self._submit(take_id)\n"
            + "        return (take,True) if submission_request_id is not None and return_created else take\n"
        )
        generate_method = new_signature + "\n" + new_body
        controller_source = controller_source[:generate_start] + generate_method + controller_source[generate_end:]
        entries["controller/service.py"] = (controller_info, controller_source.encode("utf-8"))


    # Pass the actual requested dimensions and frame rate into the ComfyUI mapping layer.
    # The workflow's authentic exported graph must expose mappings for these values.
    patch_text(
        entries,
        "comfyui/adapter.py",
        [(
            '        values: dict[str, Any] = {"prompt": request["prompt"], "duration": spec.get("duration"), "seed": spec.get("seed")}\n',
            '''        values: dict[str, Any] = {"prompt": request["prompt"], "duration": spec.get("duration"), "seed": spec.get("seed")}
        dimensions = {"720p": (1280, 720), "1080p": (1920, 1080), "1440p": (2560, 1440), "4K": (3840, 2160)}
        resolution = spec.get("resolution")
        if resolution in dimensions:
            if spec.get("aspect_ratio", "16:9") != "16:9":
                raise WorkflowTemplateError("The initial director submission path supports 16:9 only.")
            values["width"], values["height"] = dimensions[resolution]
        if spec.get("frame_rate") is not None:
            values["fps"] = spec["frame_rate"]
''',
            "map requested resolution and frame rate",
        )],
    )

    real_methods = r'''    def shot_template(self) -> dict[str, Any]:
        """Return the validated starter specification used by the Director form."""
        template_path = self.root / "config" / "test_shot.json"
        value = json.loads(template_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("shot template must be a JSON object")
        value["generation_mode"] = "TEXT_TO_VIDEO"
        value["shot_type"] = "SINGLE-SHOT"
        return value

    def real_shot_readiness(self, force: bool = False) -> dict[str, Any]:
        """Read-only preflight. It never queues a job or downloads anything."""
        now = time.monotonic()
        with self._readiness_lock:
            if not force and self._readiness_cache and now - self._readiness_cache[0] < 15:
                return dict(self._readiness_cache[1])

        adapter = self.controller.adapter
        if type(adapter).__name__ == "MockComfyUIAdapter":
            result = {
                "enabled": False,
                "mock_mode": True,
                "reason": "Mock Mode is active. Real submissions are locked until a secured ComfyUI endpoint is configured.",
                "workflow": "L25-T2V-SINGLE",
            }
            with self._readiness_lock:
                self._readiness_cache = (time.monotonic(), result)
            return dict(result)

        if type(adapter).__name__ != "RealComfyUIAdapter":
            result = {
                "enabled": False,
                "mock_mode": False,
                "reason": "The active controller adapter is not the verified ComfyUI production adapter.",
                "workflow": "L25-T2V-SINGLE",
            }
            with self._readiness_lock:
                self._readiness_cache = (time.monotonic(), result)
            return dict(result)

        try:
            data_root_text = os.environ.get("HRF_DATA_DIR", "").strip()
            if not data_root_text:
                raise ValueError("Persistent controller storage is not configured. Attach a durable Render volume and set HRF_DATA_DIR before enabling real shots.")
            configured_data_root = Path(data_root_text)
            if not configured_data_root.is_absolute():
                raise ValueError("HRF_DATA_DIR must be an absolute path on an attached durable volume.")
            data_root = configured_data_root.resolve()
            if not data_root.is_dir():
                raise ValueError("HRF_DATA_DIR does not exist or is not a directory.")
            database_path = getattr(self.controller.store, "path", None)
            if database_path is None or not Path(database_path).resolve().is_relative_to(data_root):
                raise ValueError("The controller SQLite database is not located inside HRF_DATA_DIR.")
            mount_path = data_root
            while mount_path != mount_path.parent and not mount_path.is_mount():
                mount_path = mount_path.parent
            if not mount_path.is_mount() or mount_path == Path("/"):
                raise ValueError("HRF_DATA_DIR is not backed by a mounted persistent volume; ephemeral filesystem storage is not safe for real-shot submissions.")
            presets_path = self.root / "workflows" / "real_presets.json"
            presets = json.loads(presets_path.read_text(encoding="utf-8"))
            config = presets.get("L25-T2V-SINGLE") if isinstance(presets, dict) else None
            if not isinstance(config, dict) or config.get("ready") is not True:
                raise ValueError("The verified LTX-2.5 T2V workflow is not installed and approved. Real presets remain safely disabled.")

            from workflows.loader import WorkflowLoader
            loader = WorkflowLoader(self.root)
            workflow = loader.load(config["workflow_file"])
            mapping_path = (self.root / config["mapping_file"]).resolve()
            if not mapping_path.is_relative_to(self.root) or not mapping_path.is_file():
                raise ValueError("The T2V mapping file is missing or outside the controller package.")
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
            if not isinstance(mapping, dict):
                raise ValueError("The T2V mapping must be a JSON object.")
            required_values = {
                "prompt": "HIS RISEN read-only preflight",
                "duration": 8,
                "seed": 0,
                "width": 2560,
                "height": 1440,
                "fps": 24,
            }
            missing_mappings = [
                key for key in required_values
                if not isinstance(mapping.get(key), dict) or mapping[key].get("required") is not True
            ]
            if missing_mappings:
                raise ValueError(
                    "The exported T2V mapping must explicitly require these director controls: "
                    + ", ".join(missing_mappings)
                )
            loader.validate_required_mappings(workflow, mapping, required_values)

            node_types = {
                node.get("class_type")
                for node in workflow.values()
                if isinstance(node, dict) and isinstance(node.get("class_type"), str)
            }
            if not node_types:
                raise ValueError("The exported T2V API workflow contains no ComfyUI node classes.")

            stats = adapter.http._request_json("GET", "/system_stats", timeout=3)
            if not isinstance(stats, dict):
                raise ValueError("ComfyUI /system_stats returned an invalid response.")
            devices = stats.get("devices")
            devices = devices if isinstance(devices, list) else []
            cuda_devices = [
                device for device in devices
                if isinstance(device, dict)
                and str(device.get("type", "")).lower() == "cuda"
                and isinstance(device.get("vram_total"), (int, float))
            ]
            eligible = [
                device for device in cuda_devices
                if device["vram_total"] >= 32 * 1024 ** 3
            ]
            if not eligible:
                raise ValueError("ComfyUI is reachable, but no CUDA GPU with at least 32 GiB VRAM was detected.")

            object_info = adapter.http._request_json("GET", "/object_info", timeout=5)
            if not isinstance(object_info, dict):
                raise ValueError("ComfyUI /object_info returned an invalid response.")
            missing_nodes = sorted(node_types - set(object_info))
            if missing_nodes:
                raise ValueError("ComfyUI is missing required workflow node classes: " + ", ".join(missing_nodes[:8]))

            gpu = max(eligible, key=lambda device: device["vram_total"])
            result = {
                "enabled": True,
                "mock_mode": False,
                "reason": "The T2V API workflow, required node classes, remote ComfyUI endpoint and CUDA GPU passed read-only preflight.",
                "workflow": "L25-T2V-SINGLE",
                "comfyui_reachable": True,
                "persistent_storage_ready": True,
                "persistent_storage_mount": str(mount_path),
                "gpu_name": str(gpu.get("name", "CUDA GPU")),
                "gpu_vram_gib": round(gpu["vram_total"] / (1024 ** 3), 1),
                "supported_modes": ["TEXT_TO_VIDEO"],
                "submission_requires_director_confirmation": True,
                "note": "A successful preflight does not prove the selected model weights load or that a video renders. The first real shot remains the acceptance test.",
            }
        except Exception as exc:
            result = {
                "enabled": False,
                "mock_mode": False,
                "reason": f"Real submission preflight is blocked: {type(exc).__name__}: {str(exc)[:240]}",
                "workflow": "L25-T2V-SINGLE",
            }

        with self._readiness_lock:
            self._readiness_cache = (time.monotonic(), result)
        return dict(result)

    def submit_real_shot(self, specification: dict[str, Any], request_id: str) -> dict[str, Any]:
        """Submit exactly one explicitly approved T2V shot; retries are idempotent."""
        if not isinstance(request_id, str):
            raise ValueError("request_id must be a UUIDv4 string.")
        try:
            parsed_request_id = uuid.UUID(request_id)
        except (ValueError, AttributeError) as exc:
            raise ValueError("request_id must be a UUIDv4 string.") from exc
        if parsed_request_id.version != 4:
            raise ValueError("request_id must be a UUIDv4 string.")
        if not isinstance(specification, dict):
            raise ValueError("specification must be a JSON object.")

        spec = json.loads(json.dumps(specification, ensure_ascii=False))
        if spec.get("generation_mode") != "TEXT_TO_VIDEO":
            raise ValueError("The first real-shot submission path currently accepts TEXT_TO_VIDEO only.")
        if spec.get("shot_type") != "SINGLE-SHOT":
            raise ValueError("The first real-shot submission path currently accepts SINGLE-SHOT only.")
        if spec.get("input_image") or spec.get("frame_conditioning") or spec.get("continuation_source"):
            raise ValueError("Image conditioning and continuation are not enabled in the first T2V submission path.")
        if spec.get("aspect_ratio", "16:9") != "16:9":
            raise ValueError("The first real T2V submission path currently supports 16:9 only.")
        if spec.get("resolution") not in {"720p", "1080p", "1440p", "4K"}:
            raise ValueError("Select a supported resolution before submitting.")
        if type(spec.get("duration")) is not int or not 1 <= spec["duration"] <= 20:
            raise ValueError("The first real T2V path accepts whole-number durations from 1 to 20 seconds only.")
        if type(spec.get("frame_rate")) is not int or not 1 <= spec["frame_rate"] <= 60:
            raise ValueError("Frame rate must be a whole number between 1 and 60 fps.")
        if type(spec.get("seed")) is not int or spec["seed"] < 0:
            raise ValueError("A nonnegative integer seed is required by the approved T2V workflow mapping.")

        validate_specification(spec, self.root)
        payload_hash = hashlib.sha256(
            json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()

        with self._generation_lock:
            existing = self._generation_requests.get(request_id)
            if existing:
                if existing["payload_hash"] != payload_hash:
                    raise ValueError("This request_id was already used with a different shot specification.")
                take = self.controller.get_take(existing["take_id"])
                message = (
                    "This request is still PENDING. It was not submitted again automatically; inspect ComfyUI queue/history before taking further action."
                    if take.get("status") == "PENDING"
                    else "The existing durable submission was returned; no second GPU job was created."
                )
                return {"created": False, "reused": True, "take": take, "message": message}

            durable = self.controller.store.get_submission_request(request_id)
            if durable:
                if durable["payload_hash"] != payload_hash:
                    raise ValueError("This request_id was already used with a different shot specification.")
                take = self.controller.get_take(durable["take_id"])
                self._generation_requests[request_id] = {
                    "payload_hash": payload_hash,
                    "take_id": durable["take_id"],
                }
                message = (
                    "A previous attempt reserved this shot but left it PENDING. It was not re-queued to avoid a duplicate GPU job; inspect ComfyUI queue/history before deciding what to do next."
                    if take.get("status") == "PENDING"
                    else "The existing durable submission was returned; no second GPU job was created."
                )
                return {"created": False, "reused": True, "take": take, "message": message}

            readiness = self.real_shot_readiness(force=True)
            if not readiness.get("enabled"):
                raise ValueError(str(readiness.get("reason", "Real shot submission is locked by preflight.")))

            take, created = self.controller.generate(
                spec,
                submission_request_id=request_id,
                submission_payload_hash=payload_hash,
                return_created=True,
            )
            take_id = take.get("take_id") if isinstance(take, dict) else None
            if not isinstance(take_id, str) or not take_id:
                raise RuntimeError("Controller did not return a valid take_id after submission.")
            self._generation_requests[request_id] = {
                "payload_hash": payload_hash,
                "take_id": take_id,
            }
            while len(self._generation_requests) > 256:
                self._generation_requests.pop(next(iter(self._generation_requests)))
            message = (
                "An existing durable submission was returned; no second GPU job was created."
                if not created
                else "Real T2V shot accepted by the controller. Monitor its progress and review the output before approval."
            )
            return {
                "created": created,
                "reused": not created,
                "take": take,
                "message": message,
            }

'''
    # Insert methods before the fixed mock-test helper.
    patch_text(
        entries,
        "director_console.py",
        [(
            "    def create_mock_test(self) -> dict[str, Any]:\n",
            real_methods + "    def create_mock_test(self) -> dict[str, Any]:\n",
            "real shot preflight and submission methods",
        )],
    )

    html_card = r'''  <div class="card" id="realShotCard">
    <div class="row">
      <div class="grow"><h3>New real shot submission</h3><p class="muted small">This submits a single text-to-video shot through the authenticated controller. It stays locked in Mock Mode and until the verified T2V workflow, ComfyUI nodes and CUDA GPU pass preflight.</p></div>
      <span id="realShotGate" class="pill warn">LOCKED</span>
    </div>
    <div id="realShotGateMessage" class="small muted" role="status" aria-live="polite">Checking production readiness…</div>
    <form id="realShotForm" onsubmit="submitRealShot(event)">
      <div class="shot-form-grid">
        <label>Film ID<input id="shotFilmId" required autocomplete="off"></label>
        <label>Scene ID<input id="shotSceneId" required autocomplete="off"></label>
        <label>Shot ID<input id="shotId" required autocomplete="off"></label>
        <label>Character IDs (comma-separated)<input id="shotCharacters" required autocomplete="off"></label>
        <label>Voice profile IDs (comma-separated)<input id="shotVoices" required autocomplete="off"></label>
        <label>Duration (seconds)<input id="shotDuration" type="number" min="1" max="20" step="1" required></label>
        <label>Resolution<select id="shotResolution"><option>720p</option><option>1080p</option><option>1440p</option><option>4K</option></select></label>
        <label>Aspect ratio<input id="shotAspectRatio" value="16:9" readonly></label>
        <label>Frame rate<input id="shotFrameRate" type="number" min="1" max="60" step="1" required></label>
        <label>Seed<input id="shotSeed" type="number" min="0" step="1" value="0" required></label>
      </div>
      <label>Environment<textarea id="shotEnvironment" required></textarea></label>
      <label>Action<textarea id="shotAction" required></textarea></label>
      <label>Camera<textarea id="shotCamera" required></textarea></label>
      <label>Lighting<textarea id="shotLighting" required></textarea></label>
      <label>Audio and sound design<textarea id="shotAudio" required></textarea></label>
      <label>Continuity requirements<textarea id="shotContinuity" required></textarea></label>
      <label class="shot-confirm"><input id="confirmRealCost" type="checkbox" required> I confirm this is a real generation request and may incur GPU charges.</label>
      <div class="actions"><button id="submitRealShotButton" class="primary" type="submit" disabled>SUBMIT REAL SHOT</button><span id="realShotResult" class="small muted" role="status" aria-live="polite"></span></div>
    </form>
  </div>

'''
    patch_text(
        entries,
        "director_console.py",
        [(
            '  <div class="grid">\n',
            html_card + '  <div class="grid">\n',
            "real shot submission form card",
        )],
    )

    css = r'''
.shot-form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:12px 0}
.shot-form-grid label,.shot-shot-fields label{display:block;font-size:13px;color:#cbd3de}
#realShotForm>label{display:block;font-size:13px;color:#cbd3de;margin-top:10px}
#realShotForm textarea{min-height:64px;margin-top:5px}
#realShotForm input,#realShotForm select{margin-top:5px}
#realShotForm .shot-confirm{display:flex;align-items:center;gap:8px;margin-top:14px}
#realShotForm .shot-confirm input{width:auto;margin:0}
@media(max-width:700px){.shot-form-grid{grid-template-columns:1fr}}
'''
    patch_text(
        entries,
        "director_console.py",
        [(
            ".frame-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}\n",
            ".frame-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}\n" + css,
            "real shot form responsive styles",
        )],
    )

    patch_text(
        entries,
        "director_console.py",
        [(
            "let currentFilm=null,pollHandle=null;\n",
            "let currentFilm=null,pollHandle=null;\nlet shotTemplate=null,generationGate=null,pendingShotRequestId=null,pendingShotPayload=null;\n",
            "real shot form client state",
        )],
    )

    js_functions = r'''function csvIds(value){return value.split(',').map(v=>v.trim()).filter(Boolean)}
async function loadShotTemplate(){
 try{
  shotTemplate=await api('/shot-template');
  $('shotFilmId').value=shotTemplate.film_id||'';
  $('shotSceneId').value=shotTemplate.scene_id||'';
  $('shotId').value=shotTemplate.shot_id||'';
  $('shotCharacters').value=(shotTemplate.character_ids||[]).join(', ');
  $('shotVoices').value=(shotTemplate.voice_profile_ids||[]).join(', ');
  $('shotEnvironment').value=shotTemplate.environment||'';
  $('shotAction').value=shotTemplate.action||'';
  $('shotCamera').value=shotTemplate.camera||'';
  $('shotLighting').value=shotTemplate.lighting||'';
  $('shotAudio').value=shotTemplate.audio||'';
  $('shotContinuity').value=shotTemplate.continuity||'';
  $('shotDuration').value=shotTemplate.duration||8;
  $('shotResolution').value=shotTemplate.resolution||'1440p';
  $('shotAspectRatio').value=shotTemplate.aspect_ratio||'16:9';
  $('shotFrameRate').value=shotTemplate.frame_rate||24;
  $('shotSeed').value=shotTemplate.seed===undefined?0:shotTemplate.seed;
  return true;
 }catch(e){
  $('realShotGateMessage').textContent='Shot template could not be loaded: '+e.message;
  return false;
 }
}
function renderGenerationGate(gate){
 generationGate=gate;
 $('realShotGate').textContent=gate.enabled?'T2V READY':'LOCKED';
 $('realShotGate').className='pill '+(gate.enabled?'ok':'warn');
 $('realShotGateMessage').textContent=gate.reason||'Preflight status unavailable.';
 const enabled=Boolean(gate.enabled&&shotTemplate);
 document.querySelectorAll('#realShotForm input,#realShotForm textarea,#realShotForm select').forEach(el=>{el.disabled=!enabled});
 $('submitRealShotButton').disabled=!enabled;
 if(gate.enabled&&gate.gpu_name){
  $('realShotGateMessage').textContent=gate.reason+' Detected: '+gate.gpu_name+' · '+gate.gpu_vram_gib+' GiB VRAM.';
 }
}
function buildShotSpecification(){
 if(!shotTemplate)throw Error('Shot template is not loaded.');
 const spec=JSON.parse(JSON.stringify(shotTemplate));
 spec.film_id=$('shotFilmId').value.trim().toUpperCase();
 spec.scene_id=$('shotSceneId').value.trim().toUpperCase();
 spec.shot_id=$('shotId').value.trim().toUpperCase();
 spec.shot_type='SINGLE-SHOT';
 spec.character_ids=csvIds($('shotCharacters').value);
 spec.voice_profile_ids=csvIds($('shotVoices').value);
 spec.environment=$('shotEnvironment').value.trim();
 spec.action=$('shotAction').value.trim();
 spec.camera=$('shotCamera').value.trim();
 spec.lighting=$('shotLighting').value.trim();
 spec.audio=$('shotAudio').value.trim();
 spec.continuity=$('shotContinuity').value.trim();
 spec.duration=Number($('shotDuration').value);
 spec.resolution=$('shotResolution').value;
 spec.aspect_ratio=$('shotAspectRatio').value.trim();
 spec.frame_rate=Number($('shotFrameRate').value);
 delete spec.quality_preset;
 spec.status='READY';
 spec.generation_mode='TEXT_TO_VIDEO';
 spec.reference_assets=Array.isArray(shotTemplate.reference_assets)?shotTemplate.reference_assets:[];
 delete spec.input_image;delete spec.frame_conditioning;delete spec.continuation_source;
 const seed=$('shotSeed').value.trim();
 if(seed==='')throw Error('A numeric seed is required for the approved T2V mapping.');
 spec.seed=Number(seed);
 return spec;
}
function newShotRequestId(){
 if(window.crypto&&typeof window.crypto.randomUUID==='function')return window.crypto.randomUUID();
 throw Error('This browser does not support secure UUID generation. Update the browser before submitting.');
}
async function submitRealShot(event){
 event.preventDefault();
 if(!generationGate||!generationGate.enabled){note('Real shot submission is locked by production preflight.');return}
 if(!$('confirmRealCost').checked){note('Confirm the real-generation cost acknowledgement first.');return}
 let spec,payload;
 try{spec=buildShotSpecification();payload=JSON.stringify(spec)}catch(e){note(e.message);return}
 if(!pendingShotRequestId||pendingShotPayload!==payload){
  try{pendingShotRequestId=newShotRequestId()}catch(e){note(e.message);return}
  pendingShotPayload=payload;
 }
 const button=$('submitRealShotButton');
 button.disabled=true;button.textContent='SUBMITTING…';
 $('realShotResult').textContent='Submitting through the secured controller…';
 try{
  const result=await api('/shots/generate',{method:'POST',body:JSON.stringify({request_id:pendingShotRequestId,specification:spec,cost_acknowledged:$('confirmRealCost').checked})});
  const take=result.take||{};
  $('realShotResult').textContent=(result.reused?'Existing submission returned: ':'Shot submitted: ')+(take.take_id||'take ID unavailable');
  note(result.message||'Shot submission accepted.');
  pendingShotRequestId=null;pendingShotPayload=null;$('confirmRealCost').checked=false;
  currentFilm=take.film_id||currentFilm;
  await refreshAll();
 }catch(e){
  $('realShotResult').textContent='Submission not confirmed: '+e.message+'. Retrying with the same request ID will not intentionally create a duplicate.';
  note(e.message);
 }finally{
  button.textContent='SUBMIT REAL SHOT';
  button.disabled=!(generationGate&&generationGate.enabled&&shotTemplate);
 }
}
'''
    patch_text(
        entries,
        "director_console.py",
        [(
            "function updateStatusLabel(result){\n",
            js_functions + "function updateStatusLabel(result){\n",
            "real shot form client handlers",
        )],
    )

    patch_text(
        entries,
        "director_console.py",
        [(
            " const s=await api('/status');\n",
            " const s=await api('/status');\n if(!shotTemplate)await loadShotTemplate();\n const gate=await api('/generation-readiness');renderGenerationGate(gate);\n",
            "dashboard real shot preflight refresh",
        )],
    )

    patch_text(
        entries,
        "director_console.py",
        [(
            '            if path == "/api/films":\n',
            """            if path == "/api/shot-template":
                self._json(200, {"ok": True, "data": self._console().shot_template()})
                return
            if path == "/api/generation-readiness":
                self._json(200, {"ok": True, "data": self._console().real_shot_readiness()})
                return
            if path == "/api/films":
""",
            "authenticated shot template and preflight GET routes",
        )],
    )

    patch_text(
        entries,
        "director_console.py",
        [(
            '            body = self._read_json()\n            if path == "/api/updates/check":\n',
            """            body = self._read_json()
            if path == "/api/shots/generate":
                # Browsers must send the same-origin Origin header for this
                # state-changing endpoint; SameSite=Strict is an additional layer.
                if not self.headers.get("Origin"):
                    self._json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "origin_required"})
                    return
                if not isinstance(body, dict) or set(body) != {"request_id", "specification", "cost_acknowledged"}:
                    raise ValueError("shot submission requires request_id, specification and cost_acknowledged")
                if body["cost_acknowledged"] is not True:
                    raise ValueError("director cost acknowledgement is required before real generation")
                if not isinstance(body["specification"], dict):
                    raise ValueError("specification must be a JSON object")
                result = self._console().submit_real_shot(body["specification"], body["request_id"])
                self._json(202, {"ok": True, "data": result})
                return
            if path == "/api/updates/check":
""",
            "authenticated, origin-checked real shot POST route",
        )],
    )

    patch_text(
        entries,
        "director_console.py",
        [(
            "        except RequestBodyError as exc:\n",
            """        except ValidationError as exc:
            self._json(422, {"ok": False, "error": "validation_error", "details": list(exc.errors)})
        except RequestBodyError as exc:
""",
            "real shot specification validation response",
        )],
    )

    info = zipfile.ZipInfo("tests/test_director_console_real_shots.py", date_time=(2026, 11, 7, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    entries["tests/test_director_console_real_shots.py"] = (info, _test_source().encode("utf-8"))

    idempotency_source = r'''from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
import uuid
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from config.bootstrap import build_controller


class DurableSubmissionIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="his-risen-durable-idempotency-")
        source = Path(__file__).resolve().parents[1]
        self.project = Path(self.temp.name) / "project"
        shutil.copytree(source, self.project, ignore=shutil.ignore_patterns("*.sqlite3", "__pycache__", "*.pyc"))
        self.spec = json.loads((self.project / "config" / "test_shot.json").read_text(encoding="utf-8"))
        self.spec["generation_mode"] = "TEXT_TO_VIDEO"
        self.request_id = str(uuid.uuid4())
        self.payload_hash = hashlib.sha256(
            json.dumps(self.spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def test_request_survives_controller_restart_and_never_reserves_second_take(self):
        first_controller = build_controller(self.project, backend="mock")
        try:
            first, created = first_controller.generate(
                self.spec,
                submission_request_id=self.request_id,
                submission_payload_hash=self.payload_hash,
                return_created=True,
            )
            self.assertTrue(created)
            first_id = first["take_id"]
        finally:
            first_controller.close()

        restarted_controller = build_controller(self.project, backend="mock")
        try:
            second, created = restarted_controller.generate(
                self.spec,
                submission_request_id=self.request_id,
                submission_payload_hash=self.payload_hash,
                return_created=True,
            )
            self.assertFalse(created)
            self.assertEqual(second["take_id"], first_id)
            self.assertEqual(len(restarted_controller.store.film_takes(self.spec["film_id"])), 1)
        finally:
            restarted_controller.close()

    def test_request_id_cannot_be_reused_for_changed_specification(self):
        controller = build_controller(self.project, backend="mock")
        try:
            controller.generate(
                self.spec,
                submission_request_id=self.request_id,
                submission_payload_hash=self.payload_hash,
                return_created=True,
            )
            changed = dict(self.spec)
            changed["action"] = "A different action."
            changed_hash = hashlib.sha256(
                json.dumps(changed, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            with self.assertRaisesRegex(ValueError, "different shot specification"):
                controller.generate(
                    changed,
                    submission_request_id=self.request_id,
                    submission_payload_hash=changed_hash,
                    return_created=True,
                )
        finally:
            controller.close()


if __name__ == "__main__":
    unittest.main()
'''
    idempotency_info = zipfile.ZipInfo("tests/test_controller_submission_idempotency.py", date_time=(2026, 11, 7, 0, 0, 0))
    idempotency_info.compress_type = zipfile.ZIP_DEFLATED
    idempotency_info.external_attr = 0o100644 << 16
    entries["tests/test_controller_submission_idempotency.py"] = (idempotency_info, idempotency_source.encode("utf-8"))

    console = entries["director_console.py"][1].decode("utf-8")
    required = [
        "def real_shot_readiness(",
        "def submit_real_shot(",
        'if path == "/api/generation-readiness":',
        'if path == "/api/shot-template":',
        'if path == "/api/shots/generate":',
        "New real shot submission",
        "confirmRealCost",
        "function submitRealShot(event)",
        "if(!generationGate||!generationGate.enabled)",
        "The verified LTX-2.5 T2V workflow is not installed and approved",
        "get_submission_request",
        "persistent_storage_ready",
        "A nonnegative integer seed is required by the approved T2V workflow mapping.",
        "HRF_DATA_DIR is not backed by a mounted persistent volume",
        "required_values = {",
        '"width": 2560',
        '"height": 1440',
        '"fps": 24',
    ]
    missing = [marker for marker in required if marker not in console]
    if missing:
        raise RuntimeError("Real-shot submission patch incomplete: " + ", ".join(missing))
    storage_source = entries["storage/sqlite_store.py"][1].decode("utf-8")
    if "submission_requests" not in storage_source or "get_submission_request" not in storage_source:
        raise RuntimeError("Durable submission idempotency schema or lookup is missing from SQLiteStore.")
    if "self.path=path.resolve()" not in storage_source:
        raise RuntimeError("SQLiteStore does not expose its resolved database path for persistent-volume verification.")
    print("SECURE_REAL_SHOT_SUBMISSION_PATCH_APPLIED")
