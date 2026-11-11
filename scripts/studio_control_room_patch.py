#!/usr/bin/env python3
"""Apply the pre-GPU HIS RISEN production-room UI and data layer to the deployable ZIP."""
from __future__ import annotations

import argparse
import re
import tempfile
import zipfile
from pathlib import Path

ARCHIVE = Path("apps/his_risen_controller_ltx25_audited_update_2026-10-10 (2).zip")


def put(entries, name: str, payload: bytes) -> None:
    if name in entries:
        info = entries[name][0]
    else:
        info = zipfile.ZipInfo(name, date_time=(2026, 11, 7, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
    entries[name] = (info, payload)


def require_file(path: Path) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(f"Required studio workspace source is missing: {path}")
    return path.read_bytes()


def patch_archive(archive: Path) -> str:
    if not archive.is_file():
        raise FileNotFoundError(f"Controller package not found: {archive}")
    source_root = Path(__file__).resolve().parents[1]
    workspace = require_file(source_root / "studio" / "studio_workspace.py")
    html = require_file(source_root / "studio" / "studio_control_room.html")
    test_source = require_file(source_root / "studio" / "test_studio_workspace.py")
    guide = require_file(source_root / "docs" / "STUDIO_CONTROL_ROOM.md")
    mira_guide = require_file(source_root / "docs" / "MIRA_STUDIO_INTELLIGENCE.md")
    mira_assistant = require_file(source_root / "studio" / "mira_assistant.py")
    mira_test_source = require_file(source_root / "studio" / "test_mira_assistant.py")
    html_text = html.decode("utf-8")
    if html_text.count("<script>") != 1 or html_text.count("</script>") != 1:
        raise RuntimeError("Control-room HTML must contain exactly one complete application script")
    if html_text.count("</html>") != 1 or not html_text.rstrip().endswith("</html>"):
        raise RuntimeError("Control-room HTML contains visible content after the closing </html> tag")

    with zipfile.ZipFile(archive, "r") as incoming:
        bad = incoming.testzip()
        if bad:
            raise RuntimeError(f"Input controller ZIP failed integrity check at {bad}")
        comment = incoming.comment
        entries = {info.filename: (info, incoming.read(info.filename)) for info in incoming.infolist() if not info.is_dir()}

    if "director_console.py" not in entries:
        raise RuntimeError("Controller package does not contain director_console.py")
    info, raw = entries["director_console.py"]
    console = raw.decode("utf-8")

    def validate_console(source: str, stage: str) -> None:
        try:
            compile(source, "director_console.py", "exec")
        except SyntaxError as exc:
            lines = source.splitlines()
            first = max(1, (exc.lineno or 1) - 2)
            last = min(len(lines), (exc.lineno or 1) + 2)
            excerpt = "\\n".join(f"{number}: {lines[number - 1]}" for number in range(first, last + 1))
            raise RuntimeError(f"Controller syntax failed at {stage}: {exc}\\n{excerpt}") from exc

    validate_console(console, "input controller ZIP")
    import_anchor = "from config.data_paths import resolve_data_root\n"
    if "from studio_workspace import StudioWorkspace" not in console:
        if console.count(import_anchor) != 1:
            raise RuntimeError("Could not safely locate the controller data-path import")
        console = console.replace(import_anchor, import_anchor + "from studio_workspace import StudioWorkspace\n", 1)
    if "from mira_assistant import MiraAssistant" not in console:
        console = console.replace(import_anchor, import_anchor + "from mira_assistant import MiraAssistant, MiraConfigurationError, MiraProviderError, MiraRateLimitError\n", 1)

    init_anchor = "        self.root = root.resolve()\n"
    init_replacement = init_anchor + "        self.workspace = StudioWorkspace(resolve_data_root(self.root))\n"
    if "self.workspace = StudioWorkspace(" not in console:
        if console.count(init_anchor) != 1:
            raise RuntimeError("Could not safely locate DirectorConsole initialization")
        console = console.replace(init_anchor, init_replacement, 1)
    workspace_init = "        self.workspace = StudioWorkspace(resolve_data_root(self.root))\n"
    if "self.mira = MiraAssistant()" not in console:
        if console.count(workspace_init) != 1:
            raise RuntimeError("Could not safely locate the studio workspace initialization for Mira")
        console = console.replace(workspace_init, workspace_init + "        self.mira = MiraAssistant()\n", 1)

    validate_console(console, "after Mira import and initialization")

    marker = '            if path == "/api/shot-template":\n'
    get_routes = '''            if path == "/api/studio/overview":
                self._json(200, {"ok": True, "data": self._console().workspace.overview()})
                return
            if path == "/api/studio/projects":
                self._json(200, {"ok": True, "data": self._console().workspace.list_projects()})
                return
            if path == "/api/studio/scenes":
                q = parse_qs(urlparse(self.path).query)
                project_id = q.get("project_id", [""])[0]
                self._json(200, {"ok": True, "data": self._console().workspace.list_scenes(project_id)})
                return
            if path == "/api/studio/shots":
                q = parse_qs(urlparse(self.path).query)
                project_id = q.get("project_id", [""])[0]
                scene_id = q.get("scene_id", [""])[0]
                self._json(200, {"ok": True, "data": self._console().workspace.list_shots(project_id, scene_id)})
                return
            if path == "/api/studio/tests":
                q = parse_qs(urlparse(self.path).query)
                project_id = q.get("project_id", [""])[0]
                self._json(200, {"ok": True, "data": self._console().workspace.list_tests(project_id)})
                return
            if path == "/api/studio/assets":
                q = parse_qs(urlparse(self.path).query)
                project_id = q.get("project_id", [""])[0]
                category = q.get("category", [""])[0]
                self._json(200, {"ok": True, "data": self._console().workspace.list_assets(project_id, category)})
                return
            if path == "/api/studio/reviews":
                q = parse_qs(urlparse(self.path).query)
                take_id = q.get("take_id", [""])[0]
                self._json(200, {"ok": True, "data": self._console().workspace.list_reviews(take_id)})
                return
            if path == "/api/studio/reports":
                self._json(200, {"ok": True, "data": self._console().workspace.reports()})
                return
'''
    mira_get_route = '''            if path == "/api/mira/status":
                self._json(200, {"ok": True, "data": self._console().mira.status()})
                return
'''
    get_start = console.index("    def do_GET(self) -> None:")
    get_end = console.index("    def do_POST(self) -> None:", get_start)
    get_block = console[get_start:get_end]
    if "/api/mira/status" not in get_block:
        marker_mira = '            if path == "/api/shot-template":\n'
        if marker_mira not in get_block:
            raise RuntimeError("Could not safely locate authenticated Mira GET route")
        get_block = get_block.replace(marker_mira, mira_get_route + marker_mira, 1)
        console = console[:get_start] + get_block + console[get_end:]
        get_end = console.index("    def do_POST(self) -> None:", get_start)
        get_block = console[get_start:get_end]
    if "/api/studio/overview" not in get_block:
        if marker not in get_block:
            raise RuntimeError("Could not safely locate authenticated GET API routes")
        get_block = get_block.replace(marker, get_routes + marker, 1)
        console = console[:get_start] + get_block + console[get_end:]

    validate_console(console, "after authenticated GET route changes")

    post_start = console.index("    def do_POST(self) -> None:")
    post_block = console[post_start:]
    post_marker = '            if path == "/api/shots/generate":\n'
    post_routes = '''            if path.startswith("/api/studio/") and not self.headers.get("Origin"):
                self._json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "origin_required"})
                return
            if path == "/api/studio/projects":
                if not isinstance(body, dict):
                    raise ValueError("request body must be an object")
                self._json(201, {"ok": True, "data": self._console().workspace.create_project(body)})
                return
            if path == "/api/studio/scenes":
                if not isinstance(body, dict):
                    raise ValueError("request body must be an object")
                self._json(201, {"ok": True, "data": self._console().workspace.create_scene(body)})
                return
            if path == "/api/studio/shots":
                if not isinstance(body, dict):
                    raise ValueError("request body must be an object")
                self._json(201, {"ok": True, "data": self._console().workspace.create_shot(body)})
                return
            if path == "/api/studio/tests":
                if not isinstance(body, dict):
                    raise ValueError("request body must be an object")
                self._json(201, {"ok": True, "data": self._console().workspace.create_test(body)})
                return
            if path == "/api/studio/assets":
                if not isinstance(body, dict):
                    raise ValueError("request body must be an object")
                self._json(201, {"ok": True, "data": self._console().workspace.create_asset(body)})
                return
            if path == "/api/studio/reviews":
                if not isinstance(body, dict):
                    raise ValueError("request body must be an object")
                take_id = str(body.get("take_id", "")).strip()
                if not take_id:
                    raise ValueError("take_id is required")
                self._console().controller.get_take(take_id)
                self._json(201, {"ok": True, "data": self._console().workspace.create_review(body)})
                return
            status_parts = path.split("/")
            if len(status_parts) == 6 and status_parts[1:3] == ["api", "studio"] and status_parts[5] == "status" and status_parts[3] in {"projects", "scenes", "shots", "tests"}:
                resource = {"projects": "project", "scenes": "scene", "shots": "shot", "tests": "test"}[status_parts[3]]
                if not isinstance(body, dict):
                    raise ValueError("request body must be an object")
                result = self._console().workspace.update_status(resource, unquote(status_parts[4]), body.get("status"))
                self._json(200, {"ok": True, "data": result})
                return
'''
    mira_post_route = '''            if path == "/api/mira/chat":
                if not self.headers.get("Origin"):
                    self._json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "origin_required", "message": "A same-origin browser request is required."})
                    return
                if not isinstance(body, dict):
                    raise ValueError("request body must be an object")
                if body.get("data_use_acknowledged") is not True:
                    self._json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "data_use_consent_required", "message": "Please acknowledge the Gemini free-tier data-use notice before chatting."})
                    return
                try:
                    result = self._console().mira.chat(
                        message=body.get("message"),
                        studio_context=self._console().mira_briefing_context(),
                        session_id=self._cookie_token() or "",
                    )
                except MiraConfigurationError as exc:
                    self._json(503, {"ok": False, "error": "mira_not_configured", "message": str(exc)})
                    return
                except MiraRateLimitError as exc:
                    self._json(429, {"ok": False, "error": "mira_rate_limited", "message": str(exc)})
                    return
                except MiraProviderError as exc:
                    self._json(502, {"ok": False, "error": "mira_provider_unavailable", "message": str(exc)})
                    return
                self._json(200, {"ok": True, "data": result})
                return
'''
    if "/api/mira/chat" not in post_block:
        if post_marker not in post_block:
            raise RuntimeError("Could not safely locate authenticated Mira POST route")
        post_block = post_block.replace(post_marker, mira_post_route + post_marker, 1)
        console = console[:post_start] + post_block
        post_block = console[post_start:]
    logout_route = '''            if path == "/api/logout":
                self._console().sessions.revoke(self._cookie_token())
'''
    logout_route_with_mira = logout_route + '''                self._console().mira.clear_session(self._cookie_token() or "")
'''
    if "self._console().mira.clear_session" not in post_block:
        if post_block.count(logout_route) != 1:
            raise RuntimeError("Could not safely locate logout route to clear Mira's session memory")
        post_block = post_block.replace(logout_route, logout_route_with_mira, 1)
        console = console[:post_start] + post_block
    if "/api/studio/projects" not in post_block:
        if post_marker not in post_block:
            raise RuntimeError("Could not safely locate authenticated POST API routes")
        post_block = post_block.replace(post_marker, post_routes + post_marker, 1)
        console = console[:post_start] + post_block

    if "def mira_briefing_context(self)" not in console:
        context_method = '''    def mira_briefing_context(self) -> dict[str, Any]:
        """Return only aggregate studio counts and safe status labels for Mira."""
        overview = self.workspace.overview()
        projects = self.workspace.list_projects()
        tests = self.workspace.list_tests()
        project_states: dict[str, int] = {}
        for project in projects:
            state = str(project.get("status", "UNKNOWN"))
            project_states[state] = project_states.get(state, 0) + 1
        test_states: dict[str, int] = {}
        for test in tests:
            state = str(test.get("result_status", "UNKNOWN"))
            test_states[state] = test_states.get(state, 0) + 1
        status = self.status()
        allowed_totals = ("projects", "scenes", "shots", "tests", "assets", "reviews", "tests_passed", "tests_failed")
        return {
            "controller": {
                "online": True,
                "backend_adapter": status.get("backend_adapter", "unknown"),
                "mock_mode": status.get("mock_mode", True),
                "approval_required": status.get("approval_required", True),
            },
            "workspace": {key: int(overview.get(key, 0) or 0) for key in allowed_totals},
            "project_status_counts": project_states,
            "test_status_counts": test_states,
            "persistent_data_root_configured": bool((overview.get("storage") or {}).get("data_root_configured", False)),
        }

'''
        context_anchor = "    def check_for_updates(self) -> dict[str, Any]:\n"
        if console.count(context_anchor) != 1:
            raise RuntimeError("Could not safely locate DirectorConsole methods for Mira context")
        console = console.replace(context_anchor, context_method + context_anchor, 1)

    # The DirectorConsole helper is inserted before Handler, so recalculate the
    # POST slice boundary before splicing the already-patched handler block back.
    post_start = console.index("    def do_POST(self) -> None:")

    validate_console(console, "before final POST handler splice")

    if "/api/studio/reviews" in post_block:
        legacy_review = """            if path == "/api/studio/reviews":
                if not isinstance(body, dict):
                    raise ValueError("request body must be an object")
                self._json(201, {"ok": True, "data": self._console().workspace.create_review(body)})
                return
"""
        guarded_review = """            if path == "/api/studio/reviews":
                if not isinstance(body, dict):
                    raise ValueError("request body must be an object")
                take_id = str(body.get("take_id", "")).strip()
                if not take_id:
                    raise ValueError("take_id is required")
                self._console().controller.get_take(take_id)
                self._json(201, {"ok": True, "data": self._console().workspace.create_review(body)})
                return
"""
        if legacy_review in post_block:
            post_block = post_block.replace(legacy_review, guarded_review, 1)
        if "self._console().controller.get_take(take_id)" not in post_block:
            raise RuntimeError("Director review route must verify the referenced take before saving notes")
        console = console[:post_start] + post_block

    validate_console(console, "after authenticated POST route splice")

    # Replace the duplicated legacy inline page with one clean, accessible workspace.
    if 'INDEX_HTML = Path(__file__).with_name("studio_control_room.html").read_text(encoding="utf-8")' not in console:
        pattern = re.compile(r"INDEX_HTML = r'''[\s\S]*?'''(?=\n\n\nclass Handler)")
        replacement = 'INDEX_HTML = Path(__file__).with_name("studio_control_room.html").read_text(encoding="utf-8")'
        console, replacements = pattern.subn(replacement, console, count=1)
        if replacements != 1:
            raise RuntimeError(f"Expected one embedded INDEX_HTML block; found {replacements}")

    put(entries, "director_console.py", console.encode("utf-8"))
    put(entries, "studio_workspace.py", workspace)
    put(entries, "studio_control_room.html", html)
    put(entries, "tests/test_studio_workspace.py", test_source)
    put(entries, "docs/STUDIO_CONTROL_ROOM.md", guide)
    put(entries, "docs/MIRA_STUDIO_INTELLIGENCE.md", mira_guide)
    put(entries, "mira_assistant.py", mira_assistant)
    put(entries, "tests/test_mira_assistant.py", mira_test_source)

    with tempfile.NamedTemporaryFile(prefix="hrf-studio-rooms-", suffix=".zip", dir=archive.parent, delete=False) as tmp:
        temp_path = Path(tmp.name)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
            output.comment = comment
            for name, (entry_info, payload) in entries.items():
                output.writestr(entry_info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        with zipfile.ZipFile(temp_path, "r") as validation:
            bad = validation.testzip()
            if bad:
                raise RuntimeError(f"Output controller ZIP failed integrity check at {bad}")
            required = {"director_console.py", "studio_workspace.py", "studio_control_room.html", "tests/test_studio_workspace.py", "tests/test_mira_assistant.py", "mira_assistant.py", "docs/STUDIO_CONTROL_ROOM.md", "docs/MIRA_STUDIO_INTELLIGENCE.md"}
            compile(validation.read("mira_assistant.py").decode("utf-8"), "mira_assistant.py", "exec")
            missing = required - set(validation.namelist())
            if missing:
                raise RuntimeError(f"Output package is missing required studio room files: {sorted(missing)}")
            extracted = validation.read("director_console.py").decode("utf-8")
            compile(extracted, "director_console.py", "exec")
            if "StudioWorkspace(resolve_data_root(self.root))" not in extracted:
                raise RuntimeError("Studio workspace database was not wired into the controller")
        temp_path.replace(archive)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    import hashlib
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    Path(str(archive) + ".sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    Path("apps/controller-package.sha256").write_text(digest + "\n", encoding="utf-8")
    print(f"Studio workspace package: {archive} ({archive.stat().st_size} bytes)")
    print(f"SHA-256: {digest}")
    return digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    args = parser.parse_args()
    patch_archive(args.archive)


if __name__ == "__main__":
    main()
