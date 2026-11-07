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
    import_anchor = "from config.data_paths import resolve_data_root\n"
    if "from studio_workspace import StudioWorkspace" not in console:
        if console.count(import_anchor) != 1:
            raise RuntimeError("Could not safely locate the controller data-path import")
        console = console.replace(import_anchor, import_anchor + "from studio_workspace import StudioWorkspace\n", 1)

    init_anchor = "        self.root = root.resolve()\n"
    init_replacement = init_anchor + "        self.workspace = StudioWorkspace(resolve_data_root(self.root))\n"
    if "self.workspace = StudioWorkspace(" not in console:
        if console.count(init_anchor) != 1:
            raise RuntimeError("Could not safely locate DirectorConsole initialization")
        console = console.replace(init_anchor, init_replacement, 1)

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
    get_start = console.index("    def do_GET(self) -> None:")
    get_end = console.index("    def do_POST(self) -> None:", get_start)
    get_block = console[get_start:get_end]
    if "/api/studio/overview" not in get_block:
        if marker not in get_block:
            raise RuntimeError("Could not safely locate authenticated GET API routes")
        get_block = get_block.replace(marker, get_routes + marker, 1)
        console = console[:get_start] + get_block + console[get_end:]

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
    if "/api/studio/projects" not in post_block:
        if post_marker not in post_block:
            raise RuntimeError("Could not safely locate authenticated POST API routes")
        post_block = post_block.replace(post_marker, post_routes + post_marker, 1)
        console = console[:post_start] + post_block

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
            required = {"director_console.py", "studio_workspace.py", "studio_control_room.html", "tests/test_studio_workspace.py", "docs/STUDIO_CONTROL_ROOM.md"}
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
