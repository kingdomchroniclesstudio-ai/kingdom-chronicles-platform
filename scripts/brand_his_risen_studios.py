#!/usr/bin/env python3
"""Build the branded HIS RISEN STUDIOS controller package with a guarded T2V submission path.

The package adds an authenticated, director-confirmed text-to-video submission
form. Mock Mode remains unchanged and all real workflows remain disabled until
a real ComfyUI API workflow, node set and CUDA GPU pass preflight. This script
does not provision infrastructure, change Render settings, download models, or
start a generation job.
"""
from __future__ import annotations

import argparse
import hashlib
import tempfile
import zipfile
from pathlib import Path

import secure_real_shot_submission_patch

DEFAULT_ARCHIVE = Path("apps/his_risen_controller_ltx25_audited_update_2026-10-10 (2).zip")

BRANDING_TEST = '''import unittest

from director_console import APP_NAME, INDEX_HTML


class StudioBrandingTests(unittest.TestCase):
    def test_application_identity_and_control_room_labels(self):
        self.assertEqual(APP_NAME, "HIS RISEN STUDIOS")
        self.assertIn("<title>HIS RISEN STUDIOS</title>", INDEX_HTML)
        self.assertIn("Film Production Control Room", INDEX_HTML)
        self.assertIn("Secure access to the HIS RISEN STUDIOS production workspace.", INDEX_HTML)

    def test_existing_director_controls_are_preserved(self):
        for marker in (
            "Refresh",
            "LTX Update Monitor",
            "RUN ONE MOCK SHOT",
            "Director Command",
            "<video class=\\"video\\"",
            "APPROVE",
            "REJECT",
            "async function approve(",
            "async function reject(",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, INDEX_HTML)


if __name__ == "__main__":
    unittest.main()
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 1:
        return text.replace(old, new, 1)
    if count == 0 and new in text:
        return text  # idempotent re-run
    raise RuntimeError(f"Expected exactly one occurrence for {label}; found {count}.")


def update_text(entries: dict[str, tuple[zipfile.ZipInfo, bytes]], path: str,
                replacements: list[tuple[str, str, str]]) -> None:
    if path not in entries:
        raise RuntimeError(f"Required package file is missing: {path}")
    info, raw = entries[path]
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"Expected UTF-8 text in {path}") from exc
    for old, new, label in replacements:
        content = replace_once(content, old, new, label)
    entries[path] = (info, content.encode("utf-8"))


def build_branding(archive: Path) -> None:
    if not archive.is_file():
        raise FileNotFoundError(f"Controller archive not found: {archive}")
    with zipfile.ZipFile(archive, "r") as source:
        bad_member = source.testzip()
        if bad_member:
            raise RuntimeError(f"Input archive failed ZIP integrity check at: {bad_member}")
        archive_comment = source.comment
        entries = {
            info.filename: (info, source.read(info.filename))
            for info in source.infolist()
            if not info.is_dir()
        }

    update_text(
        entries,
        "director_console.py",
        [
            ('APP_NAME = "HIS RISEN Director Console"', 'APP_NAME = "HIS RISEN STUDIOS"', "application and health identity"),
            ('<meta name="description" content="Private HIS RISEN FILMS production director console.">', '<meta name="description" content="HIS RISEN STUDIOS — secure film production control room for HIS RISEN FILMS.">', "browser description"),
            ('<title>HIS RISEN Director Console</title>', '<title>HIS RISEN STUDIOS</title>', "browser tab title"),
            ('<div class="brand">HIS RISEN FILMS</div><h1>Director Console</h1>', '<div class="brand">HIS RISEN STUDIOS</div><h1>Film Production Control Room</h1>', "login screen branding"),
            ('<p class="muted">Secure access to your production controller.</p>', '<p class="muted">Secure access to the HIS RISEN STUDIOS production workspace.</p>', "login description"),
            ('onclick="login()">ENTER CONSOLE</button>', 'onclick="login()">ENTER STUDIO</button>', "login action label"),
            ('<div><div class="brand">HIS RISEN FILMS</div><div class="muted small">Director Console</div></div>', '<div><div class="brand">HIS RISEN STUDIOS</div><div class="muted small">Film Production Control Room</div></div>', "signed-in header branding"),
        ],
    )
    update_text(
        entries,
        "DIRECTOR_CONSOLE.md",
        [
            ("# HIS RISEN Director Console", "# HIS RISEN STUDIOS — Film Production Control Room", "interface documentation heading"),
        ],
    )
    update_text(
        entries,
        "DEPLOY_RENDER.md",
        [
            ("# HIS RISEN Director Console — Render Free Deployment", "# HIS RISEN STUDIOS — Render Deployment", "deployment documentation heading"),
        ],
    )

    test_info = zipfile.ZipInfo("tests/test_director_console_branding.py", date_time=(2026, 11, 6, 0, 0, 0))
    test_info.compress_type = zipfile.ZIP_DEFLATED
    test_info.external_attr = 0o100644 << 16
    entries["tests/test_director_console_branding.py"] = (test_info, BRANDING_TEST.encode("utf-8"))

    # Build and validate the secure, cost-confirmed, restart-safe T2V submission path.
    secure_real_shot_submission_patch.apply(entries)

    # Guard the exact retained UI behavior before writing the updated archive.
    console = entries["director_console.py"][1].decode("utf-8")
    required = [
        'APP_NAME = "HIS RISEN STUDIOS"',
        '<title>HIS RISEN STUDIOS</title>',
        "Film Production Control Room",
        "Refresh",
        "LTX Update Monitor",
        "RUN ONE MOCK SHOT",
        "Director Command",
        '<video class="video"',
        "async function approve(",
        "async function reject(",
    ]
    missing = [item for item in required if item not in console]
    if missing:
        raise RuntimeError(f"Post-branding UI safety checks failed: {missing}")

    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=f"{archive.stem}-", suffix=".zip", dir=archive.parent, delete=False) as tmp:
        temp_path = Path(tmp.name)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as target:
            target.comment = archive_comment
            for name, (info, payload) in entries.items():
                target.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        with zipfile.ZipFile(temp_path, "r") as check:
            bad_member = check.testzip()
            if bad_member:
                raise RuntimeError(f"Output archive failed ZIP integrity check at: {bad_member}")
            required_tests = {
                "tests/test_director_console_branding.py",
                "tests/test_director_console_real_shots.py",
                "tests/test_controller_submission_idempotency.py",
            }
            missing_tests = required_tests - set(check.namelist())
            if missing_tests:
                raise RuntimeError(f"Required controller regression tests are missing: {sorted(missing_tests)}")
        temp_path.replace(archive)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest = Path(str(archive) + ".sha256")
    manifest.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    # A separate package pin lets CI verify the generated archive without a
    # stale hard-coded digest in the workflow YAML.
    pin = Path("apps/controller-package.sha256")
    pin.write_text(f"{digest}\n", encoding="utf-8")
    print(f"Branded archive: {archive}")
    print(f"Archive size: {archive.stat().st_size} bytes")
    print(f"SHA-256: {digest}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    args = parser.parse_args()
    build_branding(args.archive)


if __name__ == "__main__":
    main()
