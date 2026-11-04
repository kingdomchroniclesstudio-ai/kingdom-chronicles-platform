from __future__ import annotations

import hashlib
import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "apps" / "his_risen_controller_ltx25_audited_update_2026-10-10 (2).zip"
MANIFEST = Path(str(ARCHIVE) + ".sha256")
BASE_SHA256 = "c92902ec951e25edbabfff93efff629330a2767d74263a6cd2d513c7d107aa5e"
TEST_ROOT = Path("/tmp/his-risen-production-readiness")
RECOVERY_MARKER = "if isinstance(history, dict) and isinstance(history.get(job_id), dict):"
FINAL_QUEUE_RECOVERY_MARKER = "if self._queue_contains_prompt(queue, job_id):"

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

def replace_once(value: str, old: str, new: str, label: str) -> str:
    count = value.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one {label} insertion point; found {count}")
    return value.replace(old, new, 1)


def main() -> None:
    current_sha = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    temp_root = Path(tempfile.mkdtemp(prefix="his-risen-recovery-combine-"))
    temp_zip = ARCHIVE.with_suffix(".recovery-combined.tmp.zip")
    try:
        with zipfile.ZipFile(ARCHIVE, "r") as source:
            files = {item.filename: source.read(item.filename) for item in source.infolist() if not item.is_dir()}
            dirs = [item for item in source.infolist() if item.is_dir()]

        adapter_text = files["comfyui/adapter.py"].decode("utf-8")
        test_text = files["tests/test_integration_layers.py"].decode("utf-8")

        if (RECOVERY_MARKER in adapter_text or FINAL_QUEUE_RECOVERY_MARKER in adapter_text) and "test_real_adapter_recovers_running_job_after_controller_restart" in test_text:
            manifest = MANIFEST.read_text(encoding="utf-8").strip()
            expected = f"{current_sha}  {ARCHIVE.name}"
            if manifest != expected:
                raise SystemExit("Combined recovery package does not match its checksum manifest")
            shutil.rmtree(TEST_ROOT, ignore_errors=True)
            TEST_ROOT.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(ARCHIVE, "r") as check:
                bad = check.testzip()
                if bad is not None:
                    raise SystemExit(f"Combined recovery ZIP failed integrity check: {bad}")
                check.extractall(TEST_ROOT)
            print("RECOVERY_PATCH_ALREADY_PRESENT", current_sha)
            print("TEST_ROOT", TEST_ROOT)
            return

        if current_sha != BASE_SHA256:
            raise SystemExit(f"Unexpected base package digest for recovery consolidation: {current_sha}")

        adapter_text = replace_once(adapter_text, ADAPTER_OLD, ADAPTER_NEW, "ComfyUI adapter restart recovery")
        test_text = replace_once(
            test_text,
            "    def test_real_adapter_blocks_until_real_workflow_is_supplied(self):\n",
            TEST_METHOD + "    def test_real_adapter_blocks_until_real_workflow_is_supplied(self):\n",
            "fake-ComfyUI restart recovery regression test",
        )
        files["comfyui/adapter.py"] = adapter_text.encode("utf-8")
        files["tests/test_integration_layers.py"] = test_text.encode("utf-8")

        with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED) as target:
            with zipfile.ZipFile(ARCHIVE, "r") as source:
                for info in source.infolist():
                    if info.is_dir():
                        target.writestr(info, b"")
                    else:
                        target.writestr(info, files[info.filename])

        with zipfile.ZipFile(temp_zip, "r") as check:
            bad = check.testzip()
            if bad is not None:
                raise SystemExit(f"Combined recovery ZIP failed integrity check: {bad}")
            check.extractall(TEST_ROOT)

        shutil.move(temp_zip, ARCHIVE)
        digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
        MANIFEST.write_text(f"{digest}  {ARCHIVE.name}\n", encoding="utf-8")
        print("RECOVERY_PATCHED_FILES comfyui/adapter.py, tests/test_integration_layers.py")
        print("PACKAGE_BYTES", ARCHIVE.stat().st_size)
        print("PACKAGE_SHA256", digest)
        print("MANIFEST", MANIFEST.read_text(encoding="utf-8").strip())
        print("TEST_ROOT", TEST_ROOT)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
        temp_zip.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
