#!/usr/bin/env python3
"""Add the LTX scheduled-state bridge to the existing deployable console ZIP."""
from __future__ import annotations

import hashlib
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "apps" / "his_risen_controller_ltx25_audited_update_2026-10-10 (2).zip"


def main() -> None:
    if not ARCHIVE.is_file():
        raise SystemExit(f"Missing controller archive: {ARCHIVE}")
    manager_module = (ROOT / "studio" / "ltx_update_manager.py").read_bytes()
    manager_tests = (ROOT / "studio" / "test_ltx_update_manager.py").read_bytes()
    with zipfile.ZipFile(ARCHIVE, "r") as incoming:
        bad = incoming.testzip()
        if bad:
            raise SystemExit(f"Input ZIP integrity error: {bad}")
        comment = incoming.comment
        infos = incoming.infolist()
        files = {info.filename: (info, incoming.read(info.filename)) for info in infos if not info.is_dir()}

    required = {"director_console.py", "studio_control_room.html", "tests/test_director_console.py"}
    missing = required - set(files)
    if missing:
        raise SystemExit(f"Input archive is missing required files: {sorted(missing)}")
    console = files["director_console.py"][1].decode("utf-8")
    import_anchor = "from config.data_paths import resolve_data_root\n"
    import_line = "from ltx_update_manager import LTXUpdateManager\n"
    if import_line not in console:
        if console.count(import_anchor) != 1:
            raise SystemExit("Could not safely locate existing data-root import")
        console = console.replace(import_anchor, import_anchor + import_line, 1)

    mira_init = "        self.mira = MiraAssistant()\n"
    manager_init = "        self.update_manager = LTXUpdateManager(resolve_data_root(self.root))\n"
    if manager_init not in console:
        if console.count(mira_init) != 1:
            raise SystemExit("Could not safely locate existing Mira initialization")
        console = console.replace(mira_init, mira_init + manager_init, 1)

    method_anchor = "    def check_for_updates(self) -> dict[str, Any]:\n"
    method = '''    def update_manager_status(self) -> dict[str, Any]:
        """Return the latest durable scheduled LTX monitor state."""
        return self.update_manager.status()

'''
    if "def update_manager_status(self)" not in console:
        if console.count(method_anchor) != 1:
            raise SystemExit("Could not safely locate existing updater method")
        console = console.replace(method_anchor, method + method_anchor, 1)

    get_start = console.index("    def do_GET(self) -> None:")
    get_end = console.index("    def do_POST(self) -> None:", get_start)
    get_block = console[get_start:get_end]
    route = '''            if path == "/api/updates/manager":
                self._json(200, {"ok": True, "data": self._console().update_manager_status()})
                return
'''
    if 'if path == "/api/updates/manager":' not in get_block:
        marker = '            if path == "/api/mira/status":\n'
        if marker not in get_block:
            marker = '            if path == "/api/shot-template":\n'
        if marker not in get_block:
            raise SystemExit("Could not safely locate authenticated GET routes")
        get_block = get_block.replace(marker, route + marker, 1)
        console = console[:get_start] + get_block + console[get_end:]

    compile(console, "director_console.py", "exec")
    files["director_console.py"] = (files["director_console.py"][0], console.encode("utf-8"))

    def put(path: str, payload: bytes) -> None:
        if path in files:
            info = files[path][0]
        else:
            info = zipfile.ZipInfo(path, date_time=(2026, 11, 21, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
        files[path] = (info, payload)

    put("ltx_update_manager.py", manager_module)
    put("tests/test_ltx_update_manager.py", manager_tests)

    with tempfile.NamedTemporaryFile(prefix="hrf-ltx-manager-", suffix=".zip", dir=ARCHIVE.parent, delete=False) as temp:
        temporary = Path(temp.name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
            output.comment = comment
            for name, (info, payload) in files.items():
                output.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        with zipfile.ZipFile(temporary, "r") as check:
            bad = check.testzip()
            if bad:
                raise SystemExit(f"Output ZIP integrity error: {bad}")
            for path in ("ltx_update_manager.py", "tests/test_ltx_update_manager.py", "director_console.py"):
                if path not in check.namelist():
                    raise SystemExit(f"Output ZIP is missing {path}")
            compile(check.read("ltx_update_manager.py").decode("utf-8"), "ltx_update_manager.py", "exec")
            compile(check.read("director_console.py").decode("utf-8"), "director_console.py", "exec")
        temporary.replace(ARCHIVE)
    finally:
        temporary.unlink(missing_ok=True)

    digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    (ROOT / "apps" / (ARCHIVE.name + ".sha256")).write_text(f"{digest}  {ARCHIVE.name}\n", encoding="utf-8")
    (ROOT / "apps" / "controller-package.sha256").write_text(digest + "\n", encoding="utf-8")
    print(f"LTX manager bridge packaged: {ARCHIVE.stat().st_size} bytes")
    print(f"SHA-256: {digest}")


if __name__ == "__main__":
    main()
