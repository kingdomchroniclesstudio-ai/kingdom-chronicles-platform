#!/usr/bin/env python3
"""Patch the staged HIS RISEN ZIP, seed a metadata-only baseline, and refresh its checksum."""
from __future__ import annotations
import hashlib, json, tempfile, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "apps" / "his_risen_controller_ltx25_audited_update_2026-10-10 (2).zip"
CHECKSUM = Path(str(ARCHIVE) + ".sha256")
WORKFLOW = ROOT / ".github/workflows/his-risen-updater-validation.yml"
REV = "4791a1100e0cf97f7ed5c55c12dd71dce13f9dd3"
MODIFIED = "2026-10-22T08:58:38.000Z"
TAG = "v1.5.0"
PUBLISHED = "2026-10-18T17:41:36Z"

REQUEST_OLD = '''def _request(url: str, timeout: float) -> tuple[int, bytes, str | None]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9, */*;q=0.8"}
    if "api.github.com" in url:
        headers["Accept"] = "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.status, response.read(MAX_RESPONSE_BYTES), response.headers.get("Content-Type")
'''

REQUEST_NEW = '''def _request(url: str, timeout: float) -> tuple[int, bytes, str | None]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9, */*;q=0.8"}
    if url == RELEASE_FEED_URL:
        headers["Accept"] = "application/atom+xml, application/xml;q=0.9, */*;q=0.8"
    if "api.github.com" in url:
        headers["Accept"] = "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read(MAX_RESPONSE_BYTES), response.headers.get("Content-Type")
    except urllib.error.HTTPError as api_error:
        if url != SOURCES["ltx_github_releases"] or api_error.code not in {403, 429}:
            raise
        try:
            feed_req = urllib.request.Request(RELEASE_FEED_URL, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.8",
            })
            with urllib.request.urlopen(feed_req, timeout=timeout) as response:
                feed_body = response.read(MAX_RESPONSE_BYTES)
                feed_type = response.headers.get("Content-Type")
            metadata = _parse_release_atom(feed_body)
        except Exception as fallback_error:
            raise RuntimeError(
                f"GitHub Releases API returned HTTP {api_error.code}; official Atom-feed fallback failed: "
                f"{type(fallback_error).__name__}: {fallback_error}"
            ) from fallback_error
        return 200, json.dumps(metadata).encode("utf-8"), "application/json; fallback=official-atom-feed"


def _parse_release_atom(body: bytes) -> dict[str, Any]:
    namespace = "{http://www.w3.org/2005/Atom}"
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise ValueError(f"GitHub releases Atom feed was not valid XML: {exc}") from exc
    entry = root.find(f"{namespace}entry")
    if entry is None:
        raise ValueError("GitHub releases Atom feed contains no release entry")
    title = (entry.findtext(f"{namespace}title") or "").strip()
    entry_id = (entry.findtext(f"{namespace}id") or "").strip()
    published = (entry.findtext(f"{namespace}published") or entry.findtext(f"{namespace}updated") or "").strip()
    links = entry.findall(f"{namespace}link")
    release_url = next((item.get("href", "").strip() for item in links
                        if item.get("href") and item.get("rel", "alternate") == "alternate"), "")
    release_url = release_url or entry_id
    tag = title.split()[-1] if title else ""
    if not tag or not re.fullmatch(r"v?\\d[\\w.+-]*", tag):
        for candidate in (release_url, entry_id):
            match = re.search(r"/tag/([^/?#]+)", candidate)
            if match:
                tag = match.group(1)
                break
    if not tag:
        raise ValueError("GitHub releases Atom feed entry did not expose a release tag")
    return {"tag_name": tag, "published_at": published or None,
            "html_url": release_url or "https://github.com/Lightricks/LTX-2/releases", "body": ""}
'''

TESTS = r'''

class ReleaseFallbackAndBaselineTests(unittest.TestCase):
    def test_seed_baseline_matches_observed_metadata(self):
        import hashlib
        state = json.loads((ROOT / "storage" / "update_check_state.json").read_text(encoding="utf-8"))
        release = state["sources"]["ltx_github_releases"]
        model = state["sources"]["ltx_diffusers_model"]
        self.assertEqual(release["tag_name"], "v1.5.0")
        self.assertEqual(release["fingerprint"], hashlib.sha256(b"v1.5.0").hexdigest())
        self.assertEqual(model["revision"], "4791a1100e0cf97f7ed5c55c12dd71dce13f9dd3")
        self.assertEqual(model["last_modified"], "2026-10-22T08:58:38.000Z")
        self.assertIn("metadata baseline only", state["note"].lower())

    def test_rate_limit_uses_official_atom_fallback_without_false_update(self):
        import shutil
        import urllib.error
        root = Path(tempfile.mkdtemp())
        (root / "workflows").mkdir()
        shutil.copyfile(ROOT / "workflows" / "ltx25_capabilities.json", root / "workflows" / "ltx25_capabilities.json")
        (root / "storage").mkdir()
        shutil.copyfile(ROOT / "storage" / "update_check_state.json", root / "storage" / "update_check_state.json")
        feed = (
            b'<?xml version="1.0" encoding="utf-8"?>'
            b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>v1.5.0</title>'
            b'<id>https://github.com/Lightricks/LTX-2/releases/tag/v1.5.0</id>'
            b'<published>2026-10-18T17:41:36Z</published>'
            b'<link rel="alternate" href="https://github.com/Lightricks/LTX-2/releases/tag/v1.5.0"/>'
            b'</entry></feed>'
        )
        hf = json.dumps({"sha": "4791a1100e0cf97f7ed5c55c12dd71dce13f9dd3",
                         "lastModified": "2026-10-22T08:58:38.000Z"}).encode()
        def fake_request(url, timeout):
            if url == SOURCES["ltx_github_releases"]:
                raise urllib.error.HTTPError(url, 403, "rate limit exceeded", None, None)
            if url == "https://github.com/Lightricks/LTX-2/releases.atom":
                return 200, feed, "application/atom+xml"
            if url == SOURCES["ltx_diffusers_model"]:
                return 200, hf, "application/json"
            return 200, b"official docs", "text/html"
        with patch("updates.check._request", side_effect=fake_request):
            result = check_updates(root)
        release = next(x for x in result["sources"] if x["source"] == "ltx_github_releases")
        model = next(x for x in result["sources"] if x["source"] == "ltx_diffusers_model")
        self.assertTrue(release["reachable"])
        self.assertEqual(release["fallback_used"], "official GitHub releases Atom feed")
        self.assertEqual(release["change_status"], "no_change_since_last_check")
        self.assertEqual(model["change_status"], "no_change_since_last_check")
        self.assertEqual(result["change_candidates_requiring_manual_review"], 0)
        self.assertFalse(result["automatic_install"])
        self.assertFalse(result["downloads_started"])
        self.assertFalse(result["gpu_jobs_started"])
'''

def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def baseline() -> dict:
    model_fp = sha(json.dumps({"sha": REV, "lastModified": MODIFIED}, sort_keys=True))
    return {
        "schema_version": 1,
        "last_checked_at": "2026-10-27T17:35:37Z",
        "sources": {
            "ltx_github_releases": {
                "tag_name": TAG, "published_at": PUBLISHED,
                "html_url": f"https://github.com/Lightricks/LTX-2/releases/tag/{TAG}",
                "fingerprint": sha(TAG),
            },
            "ltx_diffusers_model": {
                "revision": REV, "last_modified": MODIFIED, "fingerprint": model_fp,
            },
        },
        "note": "Metadata baseline only, recorded from read-only official-source observations on 2026-10-27; not an installed-version manifest and not compatibility approval.",
    }

def main() -> None:
    if not ARCHIVE.is_file():
        raise SystemExit(f"Missing archive: {ARCHIVE}")
    with zipfile.ZipFile(ARCHIVE, "r") as z:
        entries = {info.filename: (info, z.read(info.filename)) for info in z.infolist() if not info.is_dir()}
    source = entries["updates/check.py"][1].decode("utf-8")
    if "fallback=official-atom-feed" not in source:
        if REQUEST_OLD not in source:
            raise SystemExit("Could not locate the exact existing _request implementation; no ZIP changes made.")
        source = source.replace("import urllib.request\n", "import urllib.error\nimport urllib.request\nimport re\nimport xml.etree.ElementTree as ET\n", 1)
        source = source.replace("\n\nUSER_AGENT =", '\n\nRELEASE_FEED_URL = "https://github.com/Lightricks/LTX-2/releases.atom"\n\nUSER_AGENT =', 1)
        source = source.replace(REQUEST_OLD, REQUEST_NEW, 1)
        source = source.replace(
            'result.update({"reachable": True, "http_status": status, "content_type": content_type, "bytes_sampled": len(body)})',
            'result.update({"reachable": True, "http_status": status, "content_type": content_type, "bytes_sampled": len(body)})\n'
            '            if content_type and "fallback=official-atom-feed" in content_type:\n'
            '                result["url"] = RELEASE_FEED_URL\n'
            '                result["fallback_used"] = "official GitHub releases Atom feed"\n'
            '                result["note"] = "Used the official public releases Atom feed because the API was rate-limited; comparing release tags only."',
            1,
        )
        source = source.replace(
            'fingerprint = _sha256(json.dumps({"tag_name": tag, "published_at": published, "body": body_text}, sort_keys=True))',
            'fingerprint = _sha256(str(tag))',
            1,
        )
    entries["updates/check.py"] = (entries["updates/check.py"][0], source.encode("utf-8"))

    tests = entries["tests/test_update_checker.py"][1].decode("utf-8")
    if "class ReleaseFallbackAndBaselineTests" not in tests:
        marker = "\n\nif __name__ == \"__main__\":\n"
        if marker not in tests:
            raise SystemExit("Could not find test module footer; no ZIP changes made.")
        tests = tests.replace(marker, TESTS + marker, 1)
    entries["tests/test_update_checker.py"] = (entries["tests/test_update_checker.py"][0], tests.encode("utf-8"))

    info = zipfile.ZipInfo("storage/update_check_state.json")
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    entries["storage/update_check_state.json"] = (info, (json.dumps(baseline(), indent=2, sort_keys=True) + "\n").encode())

    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    expected_line = '          expected_sha256="77c74f84e1e94e356ac818d6aff92117db10470908963186138f98ca8bf65229"\n'
    checksum_block = (
        '          checksum_file="$archive.sha256"\n'
        '          test -s "$checksum_file"\n'
        '          expected_sha256="$(awk \'NF {print $1; exit}\' "$checksum_file")"\n'
        '          test -n "$expected_sha256"\n'
    )
    if expected_line in workflow_text:
        WORKFLOW.write_text(workflow_text.replace(expected_line, checksum_block, 1), encoding="utf-8")
    elif 'checksum_file="$archive.sha256"' not in workflow_text:
        raise SystemExit("Could not safely update validation workflow checksum guard.")

    with tempfile.TemporaryDirectory(prefix="hrf-updater-") as td:
        rebuilt = Path(td) / ARCHIVE.name
        with zipfile.ZipFile(rebuilt, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for name in sorted(entries):
                item, data = entries[name]
                item.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(item, data)
        with zipfile.ZipFile(rebuilt, "r") as z:
            bad = z.testzip()
            if bad:
                raise SystemExit(f"ZIP integrity failure: {bad}")
            if "storage/update_check_state.json" not in z.namelist():
                raise SystemExit("Seed baseline missing from rebuilt ZIP.")
        ARCHIVE.write_bytes(rebuilt.read_bytes())

    digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    CHECKSUM.write_text(f"{digest}  {ARCHIVE.name}\n", encoding="utf-8")
    print("Repacked updater ZIP and recorded SHA-256:", digest)

if __name__ == "__main__":
    main()
