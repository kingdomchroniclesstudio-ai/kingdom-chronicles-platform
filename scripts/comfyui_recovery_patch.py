from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "apps" / "his_risen_controller_ltx25_audited_update_2026-10-10 (2).zip"
MANIFEST = Path(str(ARCHIVE) + ".sha256")
ORIGINAL_SHA256 = "df2592a2527f74f6d603357f33f56ad16287bed7f516f4f0a2af993b947d14d9"
TEST_ROOT = Path("/tmp/his-risen-recovery-test")

ADAPTER_OLD = """        if job is None:
            history = self.http.history(job_id)
            result = self._completed_from_history(job_id, history)
            if result:
                return result
            raise ComfyUIError(f"unknown or unavailable ComfyUI prompt_id: {job_id}")
"""
ADAPTER_NEW = """        if job is None:
            # The controller can restart while ComfyUI continues running a queued job.
            # The prompt_id is persisted by the controller, but this adapter's in-memory
            # submission timestamp is not. Recover any still-present history record and
            # continue polling instead of incorrectly treating the active job as unknown.
            history = self.http.history(job_id)
            result = self._completed_from_history(job_id, history)
            if result:
                return result
            if isinstance(history, dict) and isinstance(history.get(job_id), dict):
                return GenerationUpdate(state="RUNNING", progress=50)
            raise ComfyUIError(f"unknown or unavailable ComfyUI prompt_id: {job_id}")
"""

TEST_ANCHOR = """    def test_real_adapter_blocks_until_real_workflow_is_supplied(self):
"""
TEST_METHOD = """    def test_real_adapter_recovers_running_job_after_controller_restart(self):
        from dev.fake_comfyui import FakeComfyUI
        root = Path(__file__).resolve().parents[1]
        work = Path(tempfile.mkdtemp(prefix="his-risen-recovery-")) / "project"
        shutil.copytree(root, work, ignore=shutil.ignore_patterns("*.sqlite3", "__pycache__"))
        cfg_path = work / "workflows" / "real_presets.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["L25-T2V-SINGLE"]["ready"] = True
        cfg_path.write_text(json.dumps(cfg))
        fake = FakeComfyUI()
        fake.start()
        try:
            request = {
                "workflow": {"preset_id": "L25-T2V-SINGLE"},
                "specification": {"duration": 8},
                "prompt": "RESTART RECOVERY TEST",
                "profiles": {"reference_assets": []},
            }
            original_adapter = RealComfyUIAdapter(work, fake.base_url, timeout=2, job_timeout=10)
            job_id = original_adapter.submit(request, "TAKE-RESTART-RECOVERY")

            # A new adapter instance simulates the controller process restarting.
            restarted_adapter = RealComfyUIAdapter(work, fake.base_url, timeout=2, job_timeout=10)
            resumed = restarted_adapter.poll(job_id)
            self.assertEqual(resumed.state, "RUNNING")
            self.assertEqual(resumed.progress, 50)

            completed = restarted_adapter.poll(job_id)
            self.assertEqual(completed.state, "COMPLETED")
            self.assertFalse(completed.output_metadata["is_mock"])
        finally:
            fake.stop()

"""
def replace_once(data: str, old: str, new: str, label: str) -> str:
    count = data.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one {label} insertion point; found {count}")
    return data.replace(old, new, 1)


def main() -> None:
    original_digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    if original_digest != ORIGINAL_SHA256:
        raise SystemExit(f"Unexpected starting package digest: {original_digest}")

    temp_zip = ARCHIVE.with_suffix(".recovery.tmp.zip")
    temp_app = Path(tempfile.mkdtemp(prefix="his-risen-recovery-build-"))
    patched: set[str] = set()
    try:
        with zipfile.ZipFile(ARCHIVE, "r") as source, zipfile.ZipFile(temp_zip, "w") as target:
            for info in source.infolist():
                data = source.read(info.filename)
                if info.filename == "comfyui/adapter.py":
                    text = data.decode("utf-8")
                    text = replace_once(text, ADAPTER_OLD, ADAPTER_NEW, "adapter recovery block")
                    data = text.encode("utf-8")
                    patched.add(info.filename)
                elif info.filename == "tests/test_integration_layers.py":
                    text = data.decode("utf-8")
                    text = replace_once(text, TEST_ANCHOR, TEST_METHOD + TEST_ANCHOR, "adapter recovery regression test")
                    data = text.encode("utf-8")
                    patched.add(info.filename)
                target.writestr(info, data)
        if patched != {"comfyui/adapter.py", "tests/test_integration_layers.py"}:
            raise SystemExit(f"Not all expected package files were patched: {sorted(patched)}")

        with zipfile.ZipFile(temp_zip, "r") as check:
            bad = check.testzip()
            if bad is not None:
                raise SystemExit(f"Rebuilt ZIP failed integrity check at {bad}")
            check.extractall(temp_app)

        # Preserve the exact deployed archive name and update its adjacent checksum.
        shutil.move(temp_zip, ARCHIVE)
        digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
        MANIFEST.write_text(f"{digest}  {ARCHIVE.name}\n", encoding="utf-8")

        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        # Extract again to the known CI test path after building the patched archive.
        with zipfile.ZipFile(ARCHIVE, "r") as package:
            package.extractall(TEST_ROOT)

        print("PATCHED_FILES", ", ".join(sorted(patched)))
        print("PACKAGE_BYTES", ARCHIVE.stat().st_size)
        print("PACKAGE_SHA256", digest)
        print("MANIFEST", MANIFEST.read_text(encoding="utf-8").strip())
        print("TEST_ROOT", TEST_ROOT)
    finally:
        shutil.rmtree(temp_app, ignore_errors=True)
        temp_zip.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
