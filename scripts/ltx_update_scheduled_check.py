#!/usr/bin/env python3
"""Scheduled read-only LTX ecosystem discovery; never downloads or installs assets."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

STATE_SCHEMA = 1
MAX_BYTES = 2_000_000
USER_AGENT = "HIS-RISEN-LTX-Update-Manager/1.0"
SOURCES: dict[str, dict[str, str]] = {
    "ltx_core_release": {"kind": "release", "url": "https://api.github.com/repos/Lightricks/LTX-2/releases/latest", "label": "Lightricks LTX core release", "components": "LTX pipeline code, chunking and decoder"},
    "comfyui_ltxvideo_release": {"kind": "release", "url": "https://api.github.com/repos/Lightricks/ComfyUI-LTXVideo/releases/latest", "label": "Official ComfyUI-LTXVideo custom nodes", "components": "ComfyUI LTXVideo nodes and workflows"},
    "comfyui_ltx25_workflows": {"kind": "contents", "url": "https://api.github.com/repos/Lightricks/ComfyUI-LTXVideo/contents/example_workflows/2.5", "label": "Official LTX-2.5 ComfyUI workflow catalog", "components": "T2V, I2V, A2V, IC-LoRA, tiled fusion and HDR workflows"},
    "hf_ltx25_diffusers": {"kind": "hf_model", "url": "https://huggingface.co/api/models/Lightricks/LTX-2.5-Diffusers?blobs=true", "label": "LTX-2.5 Diffusers model revision", "components": "Diffusers checkpoint metadata and file manifest"},
    "hf_ltx25_comfyui_stack": {"kind": "hf_model", "url": "https://huggingface.co/api/models/Lightricks/LTX-2.5?blobs=true", "label": "Official LTX-2.5 ComfyUI split model pack", "components": "Distilled transformer, Gemma 4 12B encoder, video/audio VAEs, duration head, spatial and temporal upscalers"},
    "hf_ltx25_pixel_spatial_iclora": {"kind": "hf_model", "url": "https://huggingface.co/api/models/Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler?blobs=true", "label": "LTX-2.5 Pixel Spatial Upscaler IC-LoRA", "components": "Detailing/upscaling IC-LoRA adapter"},
    "hf_gemma4_prompt_enhancer": {"kind": "hf_model", "url": "https://huggingface.co/api/models/Comfy-Org/gemma-4?blobs=true", "label": "Comfy-Org Gemma 4 prompt-enhancer model repository", "components": "Optional Gemma 4 E2B local prompt-enhancer asset"},
    "hf_lightricks_ltx25_catalog": {"kind": "hf_catalog", "url": "https://huggingface.co/api/models?author=Lightricks&search=LTX-2.5&limit=100", "label": "Official Lightricks LTX-2.5 model and adapter catalog", "components": "IC-LoRAs, adapters, VAEs, encoders, decoders and workflow-specific assets"},
    "ltx_source_changelog": {"kind": "text", "url": "https://raw.githubusercontent.com/Lightricks/LTX-2/main/CHANGELOG.md", "label": "LTX source changelog", "components": "LTX pipeline APIs and release features"},
    "ltx_comfyui_workflow_guide": {"kind": "text", "url": "https://raw.githubusercontent.com/Lightricks/ComfyUI-LTXVideo/master/example_workflows/2.5/README.md", "label": "LTX-2.5 workflow guide", "components": "Local ComfyUI workflows and dependencies"},
    "ltx_open_source_comfyui_docs": {"kind": "html", "url": "https://docs.ltx.io/open-source-model/integration-tools/comfy-ui", "label": "LTX official open-source ComfyUI documentation", "components": "Local model files and ComfyUI usage"},
    "ltx_prompting_docs": {"kind": "html", "url": "https://docs.ltx.io/open-source-model/usage-guides/prompting-guide", "label": "LTX official prompting guide", "components": "Gemma prompt enhancement, multi-shot and duration"},
    "ltx_api_changelog_docs": {"kind": "html", "url": "https://docs.ltx.io/api-changelog", "label": "LTX hosted API changelog", "components": "Hosted API only; not assumed to be local ComfyUI"},
}
FEATURES = {
    "prompt_enhancement": ("gemma 4", "gemma4_e2b", "prompt enhancer", "enhance-prompt"),
    "gemma4_text_encoder": ("gemma4-12b", "gemma 4 12b", "text encoder"),
    "multi_shot": ("multi-shot", "multishot", "multiple shots", "connected scenes"),
    "duration_prediction": ("auto-duration", "duration prediction", "duration-head"),
    "diffusion_fidelity_rendering": ("diffusion fidelity rendering", "dynamic compute by scene"),
    "diffusion_video_decoder": ("diffusion video decoder", "new video decoder", "diffvae"),
    "video_vae": ("video-vae", "conv vae", "diffvae"),
    "audio_vae": ("audio-vae", "audio vae", "vocoder"),
    "refine_details": ("refine details", "refine-details", "pixel-spatial-upscaler"),
    "native_resolution": ("native 4k", "native 8k", "native resolution"),
    "tiled_fusion": ("tiled fusion", "tiledfusion"),
    "spatial_upscaling": ("spatial upscaler", "spatial-upscaler"),
    "temporal_upscaling": ("temporal upscaler", "temporal-upscaler"),
    "hdr": ("hdr", "acescct", "hlg", "exr"),
    "ic_lora": ("ic-lora", "ic lora", "ingredients", "motion control"),
    "consistency": ("character consistency", "identity consistency", "layout", "motion track"),
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def stamp(value: datetime | None = None) -> str:
    return (value or now_utc()).isoformat().replace("+00:00", "Z")


def parse_stamp(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc) if value else None
    except (TypeError, ValueError):
        return None


def digest(value: Any) -> str:
    packed = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


def fetch(url: str, timeout: float) -> tuple[bytes, str | None]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, text/html;q=0.9, */*;q=0.8"}
    if "api.github.com" in url:
        headers.update({"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError("upstream response exceeded safe size limit")
        return body, response.headers.get("Content-Type")


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            text = " ".join(html.unescape(data).split())
            if text:
                self.parts.append(text)


def parse_atom(body: bytes) -> dict[str, Any]:
    ns = "{http://www.w3.org/2005/Atom}"
    entry = ET.fromstring(body).find(f"{ns}entry")
    if entry is None:
        raise ValueError("GitHub release Atom feed has no entry")
    title = (entry.findtext(f"{ns}title") or "").strip()
    entry_id = (entry.findtext(f"{ns}id") or "").strip()
    published = (entry.findtext(f"{ns}published") or entry.findtext(f"{ns}updated") or "").strip()
    link = next((item.get("href") for item in entry.findall(f"{ns}link") if item.get("href") and item.get("rel", "alternate") == "alternate"), None)
    url = link or entry_id
    tag = title.split()[-1] if title else ""
    if not re.fullmatch(r"v?\d[\w.+-]*", tag):
        match = re.search(r"/tag/([^/?#]+)", url)
        tag = match.group(1) if match else ""
    if not tag:
        raise ValueError("release tag missing from Atom feed")
    return {"tag_name": tag, "published_at": published, "html_url": url, "body": ""}


def observe(source_id: str, cfg: dict[str, str], timeout: float) -> dict[str, Any]:
    url = cfg["url"]
    try:
        try:
            body, content_type = fetch(url, timeout)
        except urllib.error.HTTPError as exc:
            if cfg["kind"] != "release" or exc.code not in {403, 429}:
                raise
            feed_url = url.replace("https://api.github.com/repos/", "https://github.com/").replace("/releases/latest", "/releases.atom")
            body, content_type = fetch(feed_url, timeout)
            release = parse_atom(body)
            metadata = {"tag_name": release["tag_name"], "published_at": release["published_at"], "html_url": release["html_url"]}
            return {"source": source_id, "label": cfg["label"], "kind": cfg["kind"], "url": feed_url, "canonical_url": release["html_url"], "metadata": metadata, "fingerprint": digest(metadata), "version": release["tag_name"], "published_at": release["published_at"], "summary": f"{release['tag_name']} from official GitHub Atom feed; release notes unavailable in fallback.", "components": cfg["components"], "status": "OBSERVED", "fallback_used": "official GitHub release Atom feed"}

        if cfg["kind"] == "release":
            data = json.loads(body.decode("utf-8"))
            metadata = {"tag_name": data.get("tag_name"), "published_at": data.get("published_at"), "html_url": data.get("html_url"), "notes_sha256": digest(data.get("body") or "")}
            summary = re.sub(r"\s+", " ", data.get("body") or "").strip()[:1200] or "Release published; no notes supplied."
            return {"source": source_id, "label": cfg["label"], "kind": cfg["kind"], "url": url, "canonical_url": data.get("html_url") or url, "metadata": metadata, "fingerprint": digest(metadata), "version": data.get("tag_name"), "published_at": data.get("published_at"), "summary": summary, "components": cfg["components"], "status": "OBSERVED"}
        if cfg["kind"] == "contents":
            data = json.loads(body.decode("utf-8"))
            if not isinstance(data, list):
                raise ValueError("GitHub contents response was not a list")
            metadata = sorted([{"name": row.get("name"), "path": row.get("path"), "sha": row.get("sha"), "type": row.get("type")} for row in data if isinstance(row, dict)], key=lambda item: str(item.get("path")))
            return {"source": source_id, "label": cfg["label"], "kind": cfg["kind"], "url": url, "canonical_url": "https://github.com/Lightricks/ComfyUI-LTXVideo/tree/master/example_workflows/2.5", "metadata": metadata, "fingerprint": digest(metadata), "summary": f"Official LTX-2.5 workflow catalog contains {len(metadata)} entries; file names and Git object IDs tracked.", "components": cfg["components"], "status": "OBSERVED"}
        if cfg["kind"] == "hf_model":
            data = json.loads(body.decode("utf-8"))
            siblings = data.get("siblings") or []
            file_manifest = []
            for item in siblings:
                if not isinstance(item, dict) or not item.get("rfilename"):
                    continue
                lfs = item.get("lfs") if isinstance(item.get("lfs"), dict) else {}
                file_manifest.append({
                    "name": item.get("rfilename"),
                    "size_bytes": item.get("size") or lfs.get("size"),
                    "sha256_or_lfs_oid": lfs.get("oid"),
                })
            file_manifest.sort(key=lambda item: item["name"])
            metadata = {
                "id": data.get("id"), "sha": data.get("sha"),
                "lastModified": data.get("lastModified"), "license": data.get("license"),
                "gated": data.get("gated"), "files": file_manifest,
            }
            model_id = data.get("id") or "unknown model"
            file_names = " ".join(str(item["name"]) for item in file_manifest)
            combined = (cfg["label"] + " " + file_names).lower()
            feature_tags = [name for name, phrases in FEATURES.items() if any(phrase in combined for phrase in phrases)]
            return {
                "source": source_id, "label": cfg["label"], "kind": cfg["kind"], "url": url,
                "canonical_url": f"https://huggingface.co/{model_id}",
                "metadata": metadata, "fingerprint": digest(metadata),
                "version": data.get("sha"),
                "summary": f"Model repo {model_id}, revision {data.get('sha') or 'unknown'}, {len(file_manifest)} file metadata entries; no weights downloaded.",
                "feature_tags": feature_tags, "components": cfg["components"], "status": "OBSERVED",
            }
        if cfg["kind"] == "hf_catalog":
            data = json.loads(body.decode("utf-8"))
            if not isinstance(data, list):
                raise ValueError("Hugging Face model catalog was not a list")
            metadata = sorted([{"id": row.get("id"), "sha": row.get("sha"), "lastModified": row.get("lastModified"), "tags": sorted(row.get("tags") or [])} for row in data if isinstance(row, dict) and row.get("id")], key=lambda item: item["id"])
            return {"source": source_id, "label": cfg["label"], "kind": cfg["kind"], "url": url, "canonical_url": "https://huggingface.co/models?search=LTX-2.5&author=Lightricks", "metadata": metadata, "fingerprint": digest(metadata), "summary": f"Official Lightricks catalog lists {len(metadata)} matching LTX-2.5 repositories; no weights downloaded.", "components": cfg["components"], "status": "OBSERVED"}
        decoded = body.decode("utf-8", errors="replace")
        if cfg["kind"] == "html":
            parser = VisibleText()
            parser.feed(decoded)
            decoded = " ".join(parser.parts)
        else:
            decoded = " ".join(decoded.split())
        metadata = {"text_sha256": digest(decoded), "characters": len(decoded)}
        return {"source": source_id, "label": cfg["label"], "kind": cfg["kind"], "url": url, "canonical_url": url, "metadata": metadata, "fingerprint": digest(metadata), "summary": decoded[:480], "components": cfg["components"], "status": "OBSERVED"}
    except Exception as exc:
        return {"source": source_id, "label": cfg["label"], "kind": cfg["kind"], "url": url, "components": cfg["components"], "status": "SOURCE_ERROR", "error": f"{type(exc).__name__}: {str(exc)[:400]}"}


def classify_compatibility(candidate: dict[str, Any], inventory: dict[str, Any] | None) -> dict[str, Any]:
    if inventory and isinstance(inventory, dict):
        installed = inventory.get("installed_sources", {})
        current = installed.get(candidate["source"]) if isinstance(installed, dict) else None
        version = candidate.get("version")
        if current and version and current == version:
            return {"status": "ALREADY_INSTALLED", "reason": "The registered environment records this exact source version."}
    return {
        "status": "REQUIRES_MANUAL_APPROVAL",
        "reason": "No verified production ComfyUI endpoint, installed-node inventory, model-file hashes, GPU/VRAM report or staging backup is registered. Upstream metadata alone cannot prove local compatibility.",
    }


def initial_state(interval: int) -> dict[str, Any]:
    # Existing observation baselines: LTX core v1.5.0, ComfyUI-LTXVideo v1.1.0,
    # and the previously recorded Hugging Face Diffusers revision.
    ltx = {"tag_name": "v1.5.0", "published_at": "2026-10-18T17:41:36Z", "html_url": "https://github.com/Lightricks/LTX-2/releases/tag/v1.5.0", "notes_sha256": digest("")}
    nodes = {"tag_name": "v1.1.0", "published_at": "2026-10-20T06:57:37Z", "html_url": "https://github.com/Lightricks/ComfyUI-LTXVideo/releases/tag/v1.1.0", "notes_sha256": digest("Initial release.")}
    hf = {"id": "Lightricks/LTX-2.5-Diffusers", "sha": "4791a1100e0cf97f7ed5c55c12dd71dce13f9dd3", "lastModified": "2026-10-22T08:58:38.000Z"}
    baselines = {}
    for key, meta, label, url in (
        ("ltx_core_release", ltx, "Lightricks LTX core release", SOURCES["ltx_core_release"]["url"]),
        ("comfyui_ltxvideo_release", nodes, "Official ComfyUI-LTXVideo custom nodes", SOURCES["comfyui_ltxvideo_release"]["url"]),
        ("hf_ltx25_diffusers", hf, "LTX-2.5 Diffusers model revision", SOURCES["hf_ltx25_diffusers"]["url"]),
    ):
        baselines[key] = {"fingerprint": digest(meta), "metadata": meta, "last_seen_at": "2026-10-27T17:35:37Z", "label": label, "url": url}
    return {
        "schema_version": STATE_SCHEMA, "manager": "HIS RISEN LTX Update and Integration Manager",
        "model_policy": {"primary_model": "LTX-2.5", "model_switching": False},
        "schedule": {"enabled": True, "interval_hours": interval, "scheduler": "GitHub Actions standard hosted runner", "timezone": "UTC"},
        "last_check_at": None, "last_successful_check_at": None, "next_check_due_at": None,
        "source_observations": baselines, "source_errors": {}, "candidates": [], "notifications": [], "activity": [],
        "environment": {"status": "NOT_CONNECTED", "comfyui_version": None, "installed_ltx_version": None, "gpu": None, "storage_root": None},
        "capabilities": {"detected": [], "registered": [], "installed": [], "verified": []},
        "safety": {"automatic_install": False, "downloads_enabled": False, "workflow_activation_enabled": False, "gpu_jobs_enabled": False, "director_approval_required": True},
    }


def add_event(state: dict[str, Any], kind: str, message: str, *, candidate_id: str | None = None, details: dict[str, Any] | None = None, when: datetime | None = None) -> None:
    item = {"id": digest([kind, message, stamp(when), candidate_id])[:20], "timestamp": stamp(when), "type": kind, "message": message, "candidate_id": candidate_id, "details": details or {}}
    state.setdefault("activity", []).append(item)
    state["activity"] = state["activity"][-250:]
    if kind in {"NEW_UPDATE_DETECTED", "MANUAL_ACTION_REQUIRED", "SOURCE_CHECK_FAILED", "SOURCE_RECOVERED"}:
        state.setdefault("notifications", []).append({**item, "read": False})
        state["notifications"] = state["notifications"][-250:]


def monitor_once(state: dict[str, Any] | None = None, *, interval_hours: int = 6, timeout: float = 15.0, force: bool = False, inventory: dict[str, Any] | None = None, now: datetime | None = None) -> dict[str, Any]:
    if not 1 <= int(interval_hours) <= 24:
        raise ValueError("interval_hours must be between 1 and 24")
    now = (now or now_utc()).astimezone(timezone.utc).replace(microsecond=0)
    current = json.loads(json.dumps(state or initial_state(interval_hours)))
    current.setdefault("schedule", {})["interval_hours"] = interval_hours
    last = parse_stamp(current.get("last_successful_check_at"))
    if not force and last is not None and now < last + timedelta(hours=interval_hours):
        current["skipped"] = True
        current["next_check_due_at"] = stamp(last + timedelta(hours=interval_hours))
        return current

    add_event(current, "COMPATIBILITY_CHECK_IN_PROGRESS", "Scheduled metadata discovery started; no production files or GPU environment are modified.", when=now)
    previous = current.get("source_observations", {})
    prior_errors = current.get("source_errors", {})
    observations = dict(previous)
    errors: dict[str, str] = {}
    candidates = list(current.get("candidates", []))
    candidate_ids = {row.get("id") for row in candidates}

    successful_sources = 0
    for source_id, cfg in SOURCES.items():
        seen = observe(source_id, cfg, timeout)
        if seen["status"] == "SOURCE_ERROR":
            errors[source_id] = seen["error"]
            if prior_errors.get(source_id) != seen["error"]:
                add_event(current, "SOURCE_CHECK_FAILED", f"{cfg['label']} check failed: {seen['error']}", details={"source": source_id}, when=now)
            continue
        successful_sources += 1
        if source_id in prior_errors:
            add_event(current, "SOURCE_RECOVERED", f"{cfg['label']} monitoring source recovered.", details={"source": source_id}, when=now)
        old = previous.get(source_id)
        observations[source_id] = {"fingerprint": seen["fingerprint"], "metadata": seen["metadata"], "last_seen_at": stamp(now), "label": seen["label"], "url": seen["url"]}
        if old is None:
            add_event(current, "SOURCE_BASELINED", f"Initial baseline recorded for {cfg['label']}; no update is inferred from a first observation.", details={"source": source_id}, when=now)
            continue
        if old.get("fingerprint") == seen["fingerprint"]:
            continue
        candidate_id = digest([source_id, seen["fingerprint"]])[:24]
        if candidate_id in candidate_ids:
            continue
        text_to_scan = (seen.get("summary", "") + " " + json.dumps(seen.get("metadata", {}))).lower()
        feature_tags = sorted(set(seen.get("feature_tags", [])) | {name for name, phrases in FEATURES.items() if any(phrase in text_to_scan for phrase in phrases)})
        compatibility = classify_compatibility({"source": source_id, "version": seen.get("version")}, inventory)
        if seen["kind"] in {"text", "html"}:
            compatibility = {"status": "REQUIRES_MANUAL_APPROVAL", "reason": "Documentation/changelog content changed; confirm the feature exists in the local open-weight ComfyUI workflow rather than assuming hosted API parity."}
        candidate = {
            "id": candidate_id, "source": source_id, "name": cfg["label"], "version": seen.get("version"),
            "release_date": seen.get("published_at"), "source_url": seen.get("canonical_url") or seen["url"],
            "summary": seen.get("summary", "Upstream metadata changed."), "affected_components": cfg["components"],
            "feature_tags": feature_tags, "change_fingerprint": seen["fingerprint"], "status": "DETECTED",
            "compatibility": compatibility, "installation_status": "NOT_INSTALLED",
            "verification_status": "NOT_TESTED", "detected_at": stamp(now), "director_action_required": True,
        }
        candidate["change_type"] = "SOURCE_CONTENT_CHANGE" if seen["kind"] in {"text", "html"} else "VERSION_OR_CATALOG_CHANGE"
        candidates.append(candidate)
        candidate_ids.add(candidate_id)
        add_event(current, "NEW_UPDATE_DETECTED", f"New upstream change detected: {candidate['name']} {candidate.get('version') or ''}".strip(), candidate_id=candidate_id, details={"source": source_id, "source_url": candidate["source_url"]}, when=now)
        add_event(current, "COMPATIBILITY_CHECK_IN_PROGRESS", f"Compatibility review queued for {candidate['name']}; no environment changes made.", candidate_id=candidate_id, details={"compatibility": compatibility}, when=now)
        add_event(current, "MANUAL_ACTION_REQUIRED", f"Director review required for {candidate['name']}; installation remains locked.", candidate_id=candidate_id, details={"reason": compatibility["reason"]}, when=now)

    current["source_observations"] = observations
    current["source_errors"] = errors
    current["candidates"] = candidates[-250:]
    current["last_check_at"] = stamp(now)
    current["successful_source_count"] = successful_sources
    current["failed_source_count"] = len(errors)
    if current["successful_source_count"]:
        current["last_successful_check_at"] = stamp(now)
        current["next_check_due_at"] = stamp(now + timedelta(hours=interval_hours))
    current["schedule"]["interval_hours"] = interval_hours
    current["schedule"]["scheduler"] = "GitHub Actions scheduled workflow"
    current["environment"].setdefault("status", "NOT_CONNECTED")
    current["safety"] = {"automatic_install": False, "downloads_enabled": False, "workflow_activation_enabled": False, "gpu_jobs_enabled": False, "director_approval_required": True, "reason": "Real ComfyUI, persistent GPU storage, staging backup and compatibility tests remain unconfigured."}
    current.pop("skipped", None)
    return current


def read_state(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else initial_state(6)
    except (OSError, json.JSONDecodeError):
        return initial_state(6)


def write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path, default=Path("state/ltx_update_manager.json"))
    parser.add_argument("--interval-hours", type=int, default=int(os.environ.get("LTX_UPDATE_INTERVAL_HOURS", "6")))
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    state = read_state(args.state_file)
    updated = monitor_once(state, interval_hours=args.interval_hours, timeout=args.timeout, force=args.force)
    if updated.get("skipped"):
        print(f"Skipped until {updated.get('next_check_due_at')}")
        return 0
    write_state(args.state_file, updated)
    print(json.dumps({key: updated.get(key) for key in ("last_check_at", "successful_source_count", "failed_source_count", "next_check_due_at")}, indent=2))
    print(f"Detected candidates: {sum(1 for row in updated.get('candidates', []) if row.get('status') == 'DETECTED')}")
    return 0  # Persist source failures and their notifications; network errors are not a worker crash.


if __name__ == "__main__":
    raise SystemExit(main())
