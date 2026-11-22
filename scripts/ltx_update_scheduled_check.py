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
from urllib.parse import quote

STATE_SCHEMA = 1
MAX_BYTES = 2_000_000
USER_AGENT = "HIS-RISEN-LTX-Update-Manager/1.0"
SOURCES: dict[str, dict[str, str]] = {
    "ltx_core_release": {"kind": "release", "url": "https://api.github.com/repos/Lightricks/LTX-2/releases/latest", "label": "Lightricks LTX core release", "components": "LTX pipeline code, chunking and decoder"},
    "comfyui_ltxvideo_release": {"kind": "release", "url": "https://api.github.com/repos/Lightricks/ComfyUI-LTXVideo/releases/latest", "label": "Official ComfyUI-LTXVideo custom nodes", "components": "ComfyUI LTXVideo nodes and workflows"},
    "comfyui_ltx25_workflows": {"kind": "workflow_graphs", "url": "https://api.github.com/repos/Lightricks/ComfyUI-LTXVideo/contents/example_workflows/2.5", "label": "Official LTX-2.5 ComfyUI workflow graphs", "components": "T2V, I2V, A2V, IC-LoRA, tiled fusion and HDR workflows"},
    "hf_ltx25_diffusers": {"kind": "hf_model", "url": "https://huggingface.co/api/models/Lightricks/LTX-2.5-Diffusers?blobs=true", "label": "LTX-2.5 Diffusers model revision", "components": "Diffusers checkpoint metadata and file manifest"},
    "hf_ltx25_comfyui_stack": {"kind": "hf_model", "url": "https://huggingface.co/api/models/Lightricks/LTX-2.5?blobs=true", "label": "Official LTX-2.5 ComfyUI split model pack", "components": "Distilled transformer, Gemma 4 12B encoder, video/audio VAEs, duration head, spatial and temporal upscalers"},
    "hf_ltx25_pixel_spatial_iclora": {"kind": "hf_model", "url": "https://huggingface.co/api/models/Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler?blobs=true", "label": "LTX-2.5 Pixel Spatial Upscaler IC-LoRA", "components": "Detailing/upscaling IC-LoRA adapter"},
    "hf_gemma4_prompt_enhancer": {"kind": "hf_model", "url": "https://huggingface.co/api/models/Comfy-Org/gemma-4?blobs=true", "label": "Comfy-Org Gemma 4 prompt-enhancer model repository", "components": "Optional Gemma 4 E2B local prompt-enhancer asset"},
    "ltx25_model_card": {"kind": "html", "url": "https://huggingface.co/Lightricks/LTX-2.5", "label": "Official LTX-2.5 model card and capability notes", "components": "Native multi-shot generation, diffusion fidelity rendering, decoder and text encoder updates"},
    "hf_lightricks_ltx25_catalog": {"kind": "hf_catalog", "url": "https://huggingface.co/api/models?author=Lightricks&search=LTX-2.5&limit=100", "label": "Official Lightricks LTX-2.5 model and adapter catalog", "components": "IC-LoRAs, adapters, VAEs, encoders, decoders and workflow-specific assets"},
    "ltx_source_changelog": {"kind": "text", "url": "https://raw.githubusercontent.com/Lightricks/LTX-2/main/CHANGELOG.md", "label": "LTX source changelog", "components": "LTX pipeline APIs and release features"},
    "ltx_comfyui_workflow_guide": {"kind": "text", "url": "https://raw.githubusercontent.com/Lightricks/ComfyUI-LTXVideo/master/example_workflows/2.5/README.md", "label": "LTX-2.5 workflow guide", "components": "Local ComfyUI workflows and dependencies"},
    "ltx_open_source_comfyui_docs": {"kind": "html", "url": "https://docs.ltx.io/open-source-model/integration-tools/comfy-ui", "label": "LTX official open-source ComfyUI documentation", "components": "Local model files and ComfyUI usage"},
    "ltx_prompting_docs": {"kind": "html", "url": "https://docs.ltx.io/api-documentation/implementation-guides/prompting-guide", "label": "LTX official prompting and enhancement guide", "components": "Gemma prompt enhancement, duration and multi-shot guidance"},
    "ltx_workflow_compatibility_docs": {"kind": "html", "url": "https://docs.ltx.io/open-source-model/reference/workflow-asset-compatibility", "label": "LTX official workflow and asset compatibility matrix", "components": "LTX-2.5 vs LTX-2.3 workflow, adapter, model and node constraints"},
    "ltx_api_changelog_docs": {"kind": "html", "url": "https://docs.ltx.io/api-changelog", "label": "LTX hosted API changelog", "components": "Hosted API only; not assumed to be local ComfyUI"},
}
FEATURES = {
    "distilled_generation": ("distilled-transformer", "distilled model", "fast iteration"),
    "prompt_enhancement": ("gemma 4", "gemma4_e2b", "prompt enhancer", "enhance-prompt"),
    "gemma4_text_encoder": ("gemma4-12b", "gemma 4 12b", "text encoder"),
    "multi_shot": ("multi-shot", "multishot", "multiple shots", "connected scenes"),
    "duration_prediction": ("auto-duration", "duration prediction", "duration-head"),
    "diffusion_fidelity_rendering": ("diffusion fidelity rendering", "dynamic compute by scene", "dfr pipeline"),
    "diffusion_video_decoder": ("diffusion video decoder", "new video decoder", "diffvae"),
    "video_vae": ("video-vae", "conv vae", "diffvae"),
    "audio_vae": ("audio-vae", "audio vae", "audiovaedecode"),
    "refine_details": ("refine details", "refine-details", "pixel-spatial-upscaler"),
    "native_resolution": ("native 4k", "native 8k", "native_4k", "native_8k", "native resolution"),
    "tiled_fusion": ("tiled fusion", "tiledfusion"),
    "spatial_upscaling": ("spatial upscaler", "spatial-upscaler", "latent spatial"),
    "temporal_upscaling": ("temporal upscaler", "temporal-upscaler"),
    "hdr": ("hdr", "acescct", "hlg", "exr"),
    "ic_lora": ("ic-lora", "ic lora", "ingredients", "motion control"),
    "consistency": ("character consistency", "identity consistency", "environment consistency", "layout", "motion track", "motion_track"),
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
            release_notes = re.sub(r"\s+", " ", data.get("body") or "").strip()
            metadata = {"tag_name": data.get("tag_name"), "published_at": data.get("published_at"), "html_url": data.get("html_url"), "notes_sha256": digest(release_notes)}
            summary = release_notes[:1200] or "Release published; no notes supplied."
            notes_lower = release_notes.lower()
            feature_tags = [name for name, phrases in FEATURES.items() if any(phrase in notes_lower for phrase in phrases)]
            return {"source": source_id, "label": cfg["label"], "kind": cfg["kind"], "url": url, "canonical_url": data.get("html_url") or url, "metadata": metadata, "fingerprint": digest(metadata), "version": data.get("tag_name"), "published_at": data.get("published_at"), "summary": summary, "feature_tags": feature_tags, "components": cfg["components"], "status": "OBSERVED"}
        if cfg["kind"] == "workflow_graphs":
            data = json.loads(body.decode("utf-8"))
            if not isinstance(data, list):
                raise ValueError("GitHub workflow directory response was not a list")
            workflow_manifest = []
            node_classes: set[str] = set()
            model_refs: set[str] = set()
            feature_texts: list[str] = []
            for row in data:
                if not isinstance(row, dict):
                    continue
                path = row.get("path")
                if not isinstance(path, str) or not path.startswith("example_workflows/2.5/") or ".." in Path(path).parts:
                    continue
                entry = {"name": row.get("name"), "path": path, "sha": row.get("sha"), "type": row.get("type")}
                if row.get("type") == "file" and path.lower().endswith(".json"):
                    raw_url = "https://raw.githubusercontent.com/Lightricks/ComfyUI-LTXVideo/master/" + quote(path, safe="/")
                    graph_body, _ = fetch(raw_url, timeout)
                    graph = json.loads(graph_body.decode("utf-8"))
                    classes: set[str] = set()
                    assets: set[str] = set()

                    def inspect_graph(value: Any) -> None:
                        if isinstance(value, dict):
                            # ComfyUI editor-export format: only the "type" field
                            # of an entry in the top-level/nested "nodes" array is
                            # an actual node class; other "type" fields are socket
                            # types, UI widget schemas, group metadata, etc.
                            node_rows = value.get("nodes")
                            if isinstance(node_rows, list):
                                for node_row in node_rows:
                                    if not isinstance(node_row, dict):
                                        continue
                                    node_type = node_row.get("type")
                                    if isinstance(node_type, str) and node_type.strip():
                                        classes.add(node_type.strip())
                                    api_type = node_row.get("class_type")
                                    if isinstance(api_type, str) and api_type.strip():
                                        classes.add(api_type.strip())
                            # ComfyUI API prompt-export format: class_type belongs
                            # to each prompt node object. Never infer from generic
                            # "type" or "name" fields elsewhere in the JSON.
                            api_type = value.get("class_type")
                            if isinstance(api_type, str) and api_type.strip():
                                classes.add(api_type.strip())
                            for child in value.values():
                                inspect_graph(child)
                        elif isinstance(value, list):
                            for child in value:
                                inspect_graph(child)
                        elif isinstance(value, str) and re.search(r"\.(safetensors|ckpt|pt|pth|gguf|model)$", value, re.IGNORECASE):
                            assets.add(value)

                    inspect_graph(graph)
                    classes_sorted = sorted(classes)
                    assets_sorted = sorted(assets)
                    node_classes.update(classes)
                    model_refs.update(assets)
                    feature_texts.append(" ".join(classes_sorted + assets_sorted))
                    entry["node_classes"] = classes_sorted
                    entry["model_refs"] = assets_sorted
                workflow_manifest.append(entry)
            metadata = sorted(workflow_manifest, key=lambda item: str(item.get("path")))
            feature_text = " ".join(feature_texts).lower()
            feature_tags = [name for name, phrases in FEATURES.items() if any(phrase in feature_text for phrase in phrases)]
            return {
                "source": source_id, "label": cfg["label"], "kind": cfg["kind"], "url": url,
                "canonical_url": "https://github.com/Lightricks/ComfyUI-LTXVideo/tree/master/example_workflows/2.5",
                "metadata": metadata, "fingerprint": digest(metadata),
                "summary": f"Official LTX-2.5 workflow catalogue: {len(metadata)} entries, {len(node_classes)} distinct node classes and {len(model_refs)} referenced asset names. Graph JSON metadata only; no model assets downloaded.",
                "version": digest(metadata)[:16],
                "feature_tags": feature_tags,
                "required_node_classes": sorted(node_classes), "referenced_model_assets": sorted(model_refs),
                "components": cfg["components"], "status": "OBSERVED",
            }
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
        content_lower = decoded.lower()
        metadata = {"text_sha256": digest(decoded), "characters": len(decoded)}
        feature_tags = [name for name, phrases in FEATURES.items() if any(phrase in content_lower for phrase in phrases)]
        return {"source": source_id, "label": cfg["label"], "kind": cfg["kind"], "url": url, "canonical_url": url, "metadata": metadata, "fingerprint": digest(metadata), "summary": decoded[:480], "feature_tags": feature_tags, "components": cfg["components"], "status": "OBSERVED"}
    except Exception as exc:
        return {"source": source_id, "label": cfg["label"], "kind": cfg["kind"], "url": url, "components": cfg["components"], "status": "SOURCE_ERROR", "error": f"{type(exc).__name__}: {str(exc)[:400]}"}


INVENTORY_TOP_LEVEL = {
    "schema_version", "status", "observed_at", "environment_fingerprint",
    "comfyui", "runtime", "gpu", "storage", "ltx", "custom_nodes",
    "installed_sources", "installed_node_classes", "installed_assets", "compatibility_results",
}
INVENTORY_NESTED_KEYS = {
    "comfyui": {"version", "commit"},
    "runtime": {"python_version", "pytorch_version", "cuda_version"},
    "gpu": {"model", "vram_total_gib", "driver_version"},
    "storage": {"persistent_mount_configured", "available_bytes", "mount_label"},
    "ltx": {"primary_model", "model_revision"},
}


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"inventory field '{field}' must be a non-empty string")
    return value.strip()


def environment_fingerprint(inventory: dict[str, Any]) -> str:
    """Stable fingerprint of installed production components, hardware and storage."""
    core = {
        "schema_version": inventory.get("schema_version"),
        "comfyui": inventory.get("comfyui"),
        "runtime": inventory.get("runtime"),
        "gpu": inventory.get("gpu"),
        "storage": {
            "persistent_mount_configured": inventory.get("storage", {}).get("persistent_mount_configured"),
            "mount_label": inventory.get("storage", {}).get("mount_label"),
        },
        "ltx": inventory.get("ltx"),
        "custom_nodes": sorted(inventory.get("custom_nodes", []), key=lambda row: (row.get("repository", ""), row.get("name", ""))),
        "installed_sources": inventory.get("installed_sources", {}),
        "installed_node_classes": sorted(set(inventory.get("installed_node_classes", []))),
        "installed_assets": sorted(inventory.get("installed_assets", []), key=lambda row: (row.get("repo_id", ""), row.get("filename", ""))),
    }
    return digest(core)


def validate_environment_inventory(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Accept only a complete, secret-free inventory for the fixed LTX-2.5 stack."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("environment inventory must be a JSON object")
    extra = set(value) - INVENTORY_TOP_LEVEL
    if extra:
        raise ValueError(f"environment inventory contains unsupported fields: {', '.join(sorted(extra))}")
    if value.get("schema_version") != 1:
        raise ValueError("environment inventory schema_version must be 1")

    status = value.get("status")
    if status == "NOT_CONNECTED":
        connected_fields = set(value) - {"schema_version", "status", "observed_at"}
        if connected_fields:
            raise ValueError("a NOT_CONNECTED inventory must not contain environment, asset or compatibility details")
        return {
            "schema_version": 1, "status": "NOT_CONNECTED",
            "observed_at": value.get("observed_at"),
            "note": "No production ComfyUI/GPU inventory is registered.",
        }
    if status != "CONNECTED":
        raise ValueError("environment inventory status must be NOT_CONNECTED or CONNECTED")

    normalized: dict[str, Any] = {"schema_version": 1, "status": "CONNECTED"}
    for section, allowed in INVENTORY_NESTED_KEYS.items():
        raw = value.get(section)
        if not isinstance(raw, dict):
            raise ValueError(f"connected inventory requires object '{section}'")
        extra_keys = set(raw) - allowed
        if extra_keys:
            raise ValueError(f"inventory section '{section}' contains unsupported fields: {', '.join(sorted(extra_keys))}")
        normalized[section] = dict(raw)

    for key in ("version", "commit"):
        normalized["comfyui"][key] = _require_text(normalized["comfyui"].get(key), f"comfyui.{key}")
    for key in ("python_version", "pytorch_version", "cuda_version"):
        normalized["runtime"][key] = _require_text(normalized["runtime"].get(key), f"runtime.{key}")
    normalized["gpu"]["model"] = _require_text(normalized["gpu"].get("model"), "gpu.model")
    normalized["gpu"]["driver_version"] = str(normalized["gpu"].get("driver_version") or "NOT_RECORDED")
    try:
        vram = float(normalized["gpu"].get("vram_total_gib"))
    except (TypeError, ValueError):
        raise ValueError("inventory field 'gpu.vram_total_gib' must be a positive number")
    if not (vram > 0):
        raise ValueError("inventory field 'gpu.vram_total_gib' must be a positive number")
    normalized["gpu"]["vram_total_gib"] = vram

    if normalized["storage"].get("persistent_mount_configured") is not True:
        raise ValueError("connected inventory requires persistent storage to be configured")
    try:
        available = int(normalized["storage"].get("available_bytes"))
    except (TypeError, ValueError):
        raise ValueError("inventory field 'storage.available_bytes' must be a positive integer")
    if available <= 0:
        raise ValueError("inventory field 'storage.available_bytes' must be a positive integer")
    normalized["storage"]["available_bytes"] = available
    normalized["storage"]["mount_label"] = _require_text(normalized["storage"].get("mount_label"), "storage.mount_label")

    normalized["ltx"]["primary_model"] = _require_text(normalized["ltx"].get("primary_model"), "ltx.primary_model")
    if normalized["ltx"]["primary_model"] != "LTX-2.5":
        raise ValueError("environment inventory must preserve LTX-2.5 as the primary model")
    normalized["ltx"]["model_revision"] = _require_text(normalized["ltx"].get("model_revision"), "ltx.model_revision")

    custom_nodes = value.get("custom_nodes")
    if not isinstance(custom_nodes, list):
        raise ValueError("connected inventory requires an explicit custom_nodes array")
    normalized_nodes = []
    for index, row in enumerate(custom_nodes):
        if not isinstance(row, dict) or set(row) - {"name", "repository", "version", "commit", "license", "node_classes"}:
            raise ValueError(f"custom_nodes[{index}] has an invalid shape")
        node_classes = row.get("node_classes")
        if not isinstance(node_classes, list) or any(not isinstance(name, str) or not name.strip() for name in node_classes):
            raise ValueError(f"custom_nodes[{index}].node_classes must be an explicit array of node class names")
        normalized_nodes.append({
            "name": _require_text(row.get("name"), f"custom_nodes[{index}].name"),
            "repository": _require_text(row.get("repository"), f"custom_nodes[{index}].repository"),
            "version": _require_text(row.get("version"), f"custom_nodes[{index}].version"),
            "commit": _require_text(row.get("commit"), f"custom_nodes[{index}].commit"),
            "license": str(row.get("license") or "NOT_RECORDED"),
            "node_classes": sorted({name.strip() for name in node_classes}),
        })
    normalized["custom_nodes"] = normalized_nodes

    installed_node_classes = value.get("installed_node_classes")
    if not isinstance(installed_node_classes, list) or any(not isinstance(name, str) or not name.strip() for name in installed_node_classes):
        raise ValueError("connected inventory requires an explicit installed_node_classes array")
    normalized["installed_node_classes"] = sorted({name.strip() for name in installed_node_classes})
    custom_node_classes = {name for row in normalized_nodes for name in row["node_classes"]}
    if not custom_node_classes.issubset(set(normalized["installed_node_classes"])):
        raise ValueError("installed_node_classes must include every class listed by each installed custom node repository")

    installed_sources = value.get("installed_sources")
    if not isinstance(installed_sources, dict):
        raise ValueError("connected inventory requires an installed_sources object")
    if set(installed_sources) - set(SOURCES):
        raise ValueError("installed_sources contains a source ID not present in the approved monitor")
    normalized["installed_sources"] = {
        str(key): _require_text(version, f"installed_sources.{key}")
        for key, version in installed_sources.items()
    }

    installed_assets = value.get("installed_assets")
    if not isinstance(installed_assets, list):
        raise ValueError("connected inventory requires an explicit installed_assets array")
    normalized_assets = []
    for index, row in enumerate(installed_assets):
        allowed = {"repo_id", "revision", "filename", "size_bytes", "sha256_or_lfs_oid", "license", "gated"}
        if not isinstance(row, dict) or set(row) - allowed:
            raise ValueError(f"installed_assets[{index}] has an invalid shape")
        try:
            size = int(row.get("size_bytes"))
        except (TypeError, ValueError):
            raise ValueError(f"installed_assets[{index}].size_bytes must be a positive integer")
        if size <= 0:
            raise ValueError(f"installed_assets[{index}].size_bytes must be a positive integer")
        normalized_assets.append({
            "repo_id": _require_text(row.get("repo_id"), f"installed_assets[{index}].repo_id"),
            "revision": _require_text(row.get("revision"), f"installed_assets[{index}].revision"),
            "filename": _require_text(row.get("filename"), f"installed_assets[{index}].filename"),
            "size_bytes": size,
            "sha256_or_lfs_oid": _require_text(row.get("sha256_or_lfs_oid"), f"installed_assets[{index}].sha256_or_lfs_oid"),
            "license": str(row.get("license") or "NOT_RECORDED"),
            "gated": bool(row.get("gated", False)),
        })
    normalized["installed_assets"] = normalized_assets

    result_rows = value.get("compatibility_results", [])
    if not isinstance(result_rows, list):
        raise ValueError("compatibility_results must be an array")
    normalized_results = []
    for index, row in enumerate(result_rows):
        allowed = {"source", "version", "result", "workflow_test_passed", "reason", "workflow_id", "tested_at", "environment_fingerprint"}
        if not isinstance(row, dict) or set(row) - allowed:
            raise ValueError(f"compatibility_results[{index}] has an invalid shape")
        source = _require_text(row.get("source"), f"compatibility_results[{index}].source")
        if source not in SOURCES:
            raise ValueError(f"compatibility_results[{index}].source is not an approved source ID")
        result = row.get("result")
        if result not in {"COMPATIBLE", "INCOMPATIBLE"} or row.get("workflow_test_passed") is not True:
            raise ValueError(f"compatibility_results[{index}] requires a completed workflow test result")
        normalized_results.append({
            "source": source,
            "version": _require_text(row.get("version"), f"compatibility_results[{index}].version"),
            "result": result,
            "workflow_test_passed": True,
            "reason": _require_text(row.get("reason"), f"compatibility_results[{index}].reason"),
            "workflow_id": _require_text(row.get("workflow_id"), f"compatibility_results[{index}].workflow_id"),
            "tested_at": _require_text(row.get("tested_at"), f"compatibility_results[{index}].tested_at"),
            "environment_fingerprint": _require_text(row.get("environment_fingerprint"), f"compatibility_results[{index}].environment_fingerprint"),
        })
    normalized["compatibility_results"] = normalized_results
    normalized["observed_at"] = str(value.get("observed_at") or "")
    computed_fingerprint = environment_fingerprint(normalized)
    supplied_fingerprint = value.get("environment_fingerprint")
    if supplied_fingerprint and supplied_fingerprint != computed_fingerprint:
        raise ValueError("environment_fingerprint does not match the installed ComfyUI/LTX/GPU/storage inventory")
    normalized["environment_fingerprint"] = computed_fingerprint
    return normalized


def read_inventory(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        raise ValueError(f"environment inventory is invalid JSON: {exc}") from exc
    return validate_environment_inventory(raw)


def build_installation_requirements(observation: dict[str, Any], inventory: dict[str, Any] | None) -> dict[str, Any]:
    metadata = observation.get("metadata", {}) if isinstance(observation.get("metadata"), dict) else {}
    files = metadata.get("files", []) if isinstance(metadata.get("files"), list) else []
    sized_files = [row for row in files if isinstance(row, dict) and isinstance(row.get("size_bytes"), int) and row["size_bytes"] > 0]
    estimated_bytes = sum(row["size_bytes"] for row in sized_files)
    available_bytes = None
    if isinstance(inventory, dict) and inventory.get("status") == "CONNECTED":
        available_bytes = inventory.get("storage", {}).get("available_bytes")
    if not sized_files:
        storage_result = "NOT_APPLICABLE_OR_SIZE_UNKNOWN"
    elif available_bytes is None:
        storage_result = "UNKNOWN_NO_CONNECTED_STORAGE_INVENTORY"
    elif available_bytes >= estimated_bytes:
        storage_result = "SUFFICIENT_FOR_DOWNLOAD_ONLY"
    else:
        storage_result = "INSUFFICIENT_FOR_DOWNLOAD"
    return {
        "asset_file_count_with_size": len(sized_files),
        "estimated_download_bytes": estimated_bytes if sized_files else None,
        "estimated_download_gib": round(estimated_bytes / (1024 ** 3), 3) if sized_files else None,
        "available_storage_bytes": available_bytes,
        "storage_preflight": storage_result,
        "license": metadata.get("license"),
        "gated_asset": metadata.get("gated"),
        "license_review": "DIRECTOR_REVIEW_REQUIRED" if metadata.get("license") or metadata.get("gated") else "NOT_CAPTURED",
        "gpu_vram_requirement_gib": None,
        "gpu_preflight": "UNKNOWN_REQUIRES_WORKFLOW_SPECIFIC_PROFILE",
        "requires_director_approval": True,
        "note": "Estimate covers listed files only; it excludes backups, temporary extraction space, dependencies and ComfyUI node storage. No download was started.",
    }


def classify_compatibility(candidate: dict[str, Any], inventory: dict[str, Any] | None) -> dict[str, Any]:
    """Classify only from explicit, version-matched local inventory/test evidence."""
    try:
        inventory = validate_environment_inventory(inventory)
    except (TypeError, ValueError):
        inventory = None
    if not isinstance(inventory, dict) or inventory.get("status") != "CONNECTED":
        return {
            "status": "REQUIRES_MANUAL_APPROVAL",
            "reason": "No verified production ComfyUI endpoint, installed-node inventory, model-file hashes, GPU/VRAM report or staging backup is registered. Upstream metadata alone cannot prove local compatibility.",
        }

    required_node_classes = candidate.get("required_node_classes", [])
    installed_node_classes = set(inventory.get("installed_node_classes", []))
    missing_node_classes = sorted(set(required_node_classes) - installed_node_classes)
    installed_asset_names = {
        Path(str(asset.get("filename", ""))).name.casefold()
        for asset in inventory.get("installed_assets", [])
        if isinstance(asset, dict) and asset.get("filename")
    }
    required_assets = candidate.get("referenced_model_assets", [])
    missing_assets = sorted({
        Path(str(name)).name for name in required_assets
        if Path(str(name)).name.casefold() not in installed_asset_names
    })
    if missing_node_classes or missing_assets:
        reasons = []
        if missing_node_classes:
            reasons.append("missing node classes: " + ", ".join(missing_node_classes[:30]))
        if missing_assets:
            reasons.append("missing model assets: " + ", ".join(missing_assets[:30]))
        return {
            "status": "INCOMPATIBLE",
            "reason": "The workflow is not ready in the registered ComfyUI environment (" + "; ".join(reasons) + ").",
        }
    source = candidate.get("source")
    version = candidate.get("version")
    installed = inventory.get("installed_sources", {})
    current = installed.get(source) if isinstance(installed, dict) else None
    if current and version and current == version:
        return {
            "status": "ALREADY_INSTALLED",
            "reason": "The registered production inventory records this exact version. Installation is not repeated; it remains unverified until the relevant workflow test passes.",
        }

    environment_fingerprint = inventory.get("environment_fingerprint")
    results = inventory.get("compatibility_results", [])
    if isinstance(results, list):
        matches = [
            row for row in results
            if isinstance(row, dict)
            and row.get("source") == source
            and row.get("version") == version
            and row.get("environment_fingerprint") == environment_fingerprint
        ]
        for row in reversed(matches):
            if row.get("result") == "INCOMPATIBLE":
                return {
                    "status": "INCOMPATIBLE",
                    "reason": str(row.get("reason") or "A version- and environment-matched compatibility test recorded this update as incompatible."),
                }
            if row.get("result") == "COMPATIBLE" and row.get("workflow_test_passed") is True:
                return {
                    "status": "COMPATIBLE",
                    "reason": "The exact version passed its recorded compatibility workflow against the currently fingerprinted ComfyUI/LTX environment. Director approval is still required before installation.",
                }
    return {
        "status": "REQUIRES_MANUAL_APPROVAL",
        "reason": "The connected environment has no matching, version-pinned compatibility test for this update. Review dependencies, licensing, VRAM, storage and the target workflow before approval.",
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
        "source_total_count": len(SOURCES),
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
    inventory_error = None
    try:
        inventory = validate_environment_inventory(inventory)
    except (TypeError, ValueError) as exc:
        inventory_error = str(exc)[:500]
        inventory = None
    current = json.loads(json.dumps(state or initial_state(interval_hours)))
    previous_interval = current.get("schedule", {}).get("interval_hours")
    current.setdefault("schedule", {})["interval_hours"] = interval_hours
    last = parse_stamp(current.get("last_successful_check_at"))
    stored_due = parse_stamp(current.get("next_check_due_at"))
    if last is None:
        due_at = stored_due
    elif previous_interval != interval_hours:
        due_at = last + timedelta(hours=interval_hours)
    else:
        due_at = stored_due or (last + timedelta(hours=interval_hours))
    if not force and due_at is not None and now < due_at:
        current["skipped"] = True
        current["next_check_due_at"] = stamp(due_at)
        return current

    if inventory_error:
        add_event(current, "MANUAL_ACTION_REQUIRED", "The saved ComfyUI/GPU inventory failed validation. Updates remain approval-required until the inventory is corrected.", details={"reason": inventory_error}, when=now)
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
        text_to_scan = (seen.get("summary", "") + " " + json.dumps(seen.get("metadata", {}))).lower()
        feature_tags = sorted(set(seen.get("feature_tags", [])) | {name for name, phrases in FEATURES.items() if any(phrase in text_to_scan for phrase in phrases)})
        capability_registry = current.setdefault("capabilities", {}).setdefault("detected", [])
        known_capabilities = {item.get("id") for item in capability_registry if isinstance(item, dict)}
        scope = "HOSTED_API_ONLY" if source_id == "ltx_api_changelog_docs" else "LOCAL_OPEN_WEIGHT_OR_COMFYUI"
        for feature in feature_tags:
            capability_id = digest([source_id, feature])[:20]
            if capability_id in known_capabilities:
                continue
            capability_registry.append({
                "id": capability_id, "name": feature, "source": source_id,
                "scope": scope, "status": "DETECTED_NOT_VERIFIED",
                "installation_status": "UNKNOWN",
                "verification_status": "NOT_TESTED",
                "detected_at": stamp(now),
                "source_url": seen.get("canonical_url") or seen.get("url"),
            })
            known_capabilities.add(capability_id)
        current["capabilities"]["detected"] = capability_registry[-250:]
        if old is None:
            add_event(current, "SOURCE_BASELINED", f"Initial baseline recorded for {cfg['label']}; advertised capabilities are catalogued as detected, not installed or verified.", details={"source": source_id, "feature_tags": feature_tags}, when=now)
            continue
        if old.get("fingerprint") == seen["fingerprint"]:
            continue
        candidate_id = digest([source_id, seen["fingerprint"]])[:24]
        if candidate_id in candidate_ids:
            continue
        compatibility = classify_compatibility({"source": source_id, "version": seen.get("version")}, inventory)
        if seen["kind"] in {"text", "html"}:
            compatibility = {"status": "REQUIRES_MANUAL_APPROVAL", "reason": "Documentation/changelog content changed; confirm the feature exists in the local open-weight ComfyUI workflow rather than assuming hosted API parity."}
        candidate_status = compatibility["status"] if compatibility["status"] in {"COMPATIBLE", "INCOMPATIBLE", "ALREADY_INSTALLED"} else "DETECTED"
        candidate = {
            "id": candidate_id, "source": source_id, "name": cfg["label"], "version": seen.get("version"),
            "release_date": seen.get("published_at"), "source_url": seen.get("canonical_url") or seen["url"],
            "summary": seen.get("summary", "Upstream metadata changed."), "affected_components": cfg["components"],
            "feature_tags": feature_tags,
            "required_node_classes": seen.get("required_node_classes", []),
            "referenced_model_assets": seen.get("referenced_model_assets", []),
            "change_fingerprint": seen["fingerprint"], "status": candidate_status,
            "compatibility": compatibility,
            "missing_dependencies": compatibility.get("reason", "") if compatibility.get("status") == "INCOMPATIBLE" else None,
            "installation_requirements": build_installation_requirements(seen, inventory),
            "installation_status": "INSTALLED" if compatibility["status"] == "ALREADY_INSTALLED" else "NOT_INSTALLED",
            "verification_status": "COMPATIBILITY_TEST_PASSED" if compatibility["status"] == "COMPATIBLE" else "NOT_TESTED",
            "detected_at": stamp(now), "director_action_required": True,
        }
        candidate["change_type"] = "SOURCE_CONTENT_CHANGE" if seen["kind"] in {"text", "html"} else "VERSION_OR_CATALOG_CHANGE"
        if candidate["installation_requirements"]["asset_file_count_with_size"]:
            candidate["risk_class"] = "MODEL_ASSET_AND_LICENSE_REVIEW"
        elif seen["kind"] in {"text", "html"}:
            candidate["risk_class"] = "DOCUMENTATION_ONLY"
        elif seen["kind"] == "contents":
            candidate["risk_class"] = "WORKFLOW_GRAPH_REVIEW"
        elif seen["kind"] == "release":
            candidate["risk_class"] = "SOFTWARE_DEPENDENCY_REVIEW"
        else:
            candidate["risk_class"] = "MODEL_CATALOG_REVIEW"
        candidates.append(candidate)
        candidate_ids.add(candidate_id)
        add_event(current, "NEW_UPDATE_DETECTED", f"New upstream change detected: {candidate['name']} {candidate.get('version') or ''}".strip(), candidate_id=candidate_id, details={"source": source_id, "source_url": candidate["source_url"]}, when=now)
        add_event(current, "COMPATIBILITY_CHECK_IN_PROGRESS", f"Compatibility review queued for {candidate['name']}; no environment changes made.", candidate_id=candidate_id, details={"compatibility": compatibility}, when=now)
        if compatibility["status"] == "ALREADY_INSTALLED":
            add_event(current, "ALREADY_INSTALLED_PENDING_VERIFICATION", f"{candidate['name']} {candidate.get('version') or ''} is already recorded in the installed inventory, but the relevant workflow is not yet marked VERIFIED.", candidate_id=candidate_id, details={"verification_status": candidate["verification_status"]}, when=now)
        else:
            add_event(current, "MANUAL_ACTION_REQUIRED", f"Director approval or test evidence is required for {candidate['name']}; automatic installation remains locked.", candidate_id=candidate_id, details={"reason": compatibility["reason"]}, when=now)

    current["source_observations"] = observations
    current["source_errors"] = errors
    current["candidates"] = candidates[-250:]
    current["last_check_at"] = stamp(now)
    current["successful_source_count"] = successful_sources
    current["source_total_count"] = len(SOURCES)
    current["failed_source_count"] = len(errors)
    if current["successful_source_count"] == len(SOURCES) and not errors:
        current["last_successful_check_at"] = stamp(now)
        current["next_check_due_at"] = stamp(now + timedelta(hours=interval_hours))
    else:
        # The Actions workflow wakes hourly. Retry a partial or failed source scan
        # after one hour instead of waiting six hours for the next full interval.
        current["next_check_due_at"] = stamp(now + timedelta(hours=1))
    current["schedule"]["interval_hours"] = interval_hours
    current["schedule"]["scheduler"] = "GitHub Actions scheduled workflow"
    if inventory_error:
        current["environment"] = {"status": "INVALID_INVENTORY", "inventory_error": inventory_error, "comfyui_version": None, "installed_ltx_version": None}
    elif isinstance(inventory, dict) and inventory.get("status") == "CONNECTED":
        current["environment"] = {
            "status": "CONNECTED",
            "comfyui_version": inventory["comfyui"]["version"],
            "comfyui_commit": inventory["comfyui"]["commit"],
            "python_version": inventory["runtime"]["python_version"],
            "pytorch_version": inventory["runtime"]["pytorch_version"],
            "cuda_version": inventory["runtime"]["cuda_version"],
            "installed_ltx_version": inventory["ltx"]["primary_model"],
            "installed_ltx_revision": inventory["ltx"]["model_revision"],
            "gpu_model": inventory["gpu"]["model"],
            "gpu_vram_gib": inventory["gpu"]["vram_total_gib"],
            "gpu_driver_version": inventory["gpu"]["driver_version"],
            "storage_mount_label": inventory["storage"]["mount_label"],
            "storage_available_bytes": inventory["storage"]["available_bytes"],
            "environment_fingerprint": inventory["environment_fingerprint"],
            "custom_node_count": len(inventory["custom_nodes"]),
            "installed_asset_count": len(inventory["installed_assets"]),
        }
    else:
        current["environment"] = {"status": "NOT_CONNECTED", "comfyui_version": None, "installed_ltx_version": None}
    current["safety"] = {"automatic_install": False, "downloads_enabled": False, "workflow_activation_enabled": False, "gpu_jobs_enabled": False, "director_approval_required": True, "reason": "No installer has been authorised. ComfyUI node inventory, immutable backups, licensing review and workflow acceptance are required before any install."}
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
    parser.add_argument("--inventory-file", type=Path, default=Path("state/ltx_environment_inventory.json"))
    parser.add_argument("--interval-hours", type=int, default=int(os.environ.get("LTX_UPDATE_INTERVAL_HOURS", "6")))
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--print-inventory-fingerprint", action="store_true", help="validate a connected inventory and print the environment fingerprint without running a metadata scan")
    args = parser.parse_args(argv)
    inventory_error = None
    try:
        inventory = read_inventory(args.inventory_file)
    except ValueError as exc:
        inventory = None
        inventory_error = str(exc)[:500]
    if args.print_inventory_fingerprint:
        if inventory_error:
            print("INVALID: " + inventory_error)
            return 2
        if isinstance(inventory, dict) and inventory.get("status") == "CONNECTED":
            print(inventory["environment_fingerprint"])
        elif isinstance(inventory, dict) and inventory.get("status") == "NOT_CONNECTED":
            print("NOT_CONNECTED")
        else:
            print("INVALID: no recognized inventory state")
            return 2
    state = read_state(args.state_file)
    updated = monitor_once(state, interval_hours=args.interval_hours, timeout=args.timeout, force=args.force, inventory=inventory)
    if inventory_error:
        add_event(updated, "MANUAL_ACTION_REQUIRED", "The saved ComfyUI/GPU inventory is invalid. Compatibility checks remain approval-required until it is corrected.", details={"reason": inventory_error}, when=now_utc())
        updated["environment"] = {"status": "INVALID_INVENTORY", "inventory_error": inventory_error, "comfyui_version": None, "installed_ltx_version": None}
    if updated.get("skipped"):
        print(f"Skipped until {updated.get('next_check_due_at')}")
        return 0
    write_state(args.state_file, updated)
    print(json.dumps({key: updated.get(key) for key in ("last_check_at", "successful_source_count", "failed_source_count", "next_check_due_at")}, indent=2))
    print(f"Detected candidates: {sum(1 for row in updated.get('candidates', []) if row.get('status') == 'DETECTED')}")
    return 0  # Persist source failures and their notifications; network errors are not a worker crash.


if __name__ == "__main__":
    raise SystemExit(main())
