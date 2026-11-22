# HIS RISEN LTX Update and Integration Manager — Phase 1

## Purpose and model policy

LTX-2.5 remains the primary and permanent HIS RISEN production model. This manager discovers official Lightricks/LTX ecosystem changes, keeps a durable activity/notification history, and surfaces candidates for human compatibility review. It does not silently switch model families.

## Scheduling without Render uptime

A dedicated GitHub Actions workflow performs scheduled metadata-only checks. It wakes hourly and enforces a configurable interval of 1–24 hours (default six hours; repository Actions variable LTX_UPDATE_INTERVAL_HOURS may override the default). A Director can trigger a forced run with workflow_dispatch. It writes state to the separate public ltx-update-state branch, not main, so monitoring activity does not trigger Render deployments. The Render Free web process is not the scheduler.

This repository is public and the workflow uses standard GitHub-hosted Ubuntu runners. GitHub documents standard runner use in public repositories as free. The workflow uses no larger runners, model downloads, persistent Actions artifacts, GPU runners or paid external scheduler. GitHub-hosted cron can still be delayed by platform load; the dashboard reports last and next due timestamps rather than promising exact wall-clock execution.

## Sources observed

- Lightricks/LTX-2 GitHub latest release metadata.
- Lightricks/ComfyUI-LTXVideo GitHub latest release metadata.
- Official example_workflows/2.5 repository directory contents and Git object IDs.
- Lightricks/LTX-2.5-Diffusers Hugging Face model metadata.
- Hugging Face catalogue of Lightricks repositories matching LTX-2.5 (metadata only), plus the exact ComfyUI model stack, pixel spatial upscaler, Gemma 4 enhancer repository and public model card.
- LTX source changelog, official ComfyUI workflow README, and official LTX ComfyUI, prompt-enhancement and hosted API documentation.

Documentation pages are fingerprinted from extracted content, not merely treated as reachable. Workflow catalog entries track file names and source object IDs. Hugging Face catalog checks fetch metadata only; model weights are never downloaded by this worker.

## Detection and compatibility policy

The shipped baseline carries forward the prior official-source observations: LTX core v1.5.0, ComfyUI-LTXVideo v1.1.0 and the prior Diffusers revision. The first scheduled run therefore surfaces upstream changes since that baseline rather than suppressing known changes as a “first observation”. Other sources are initially baselined without false update alerts. Later fingerprint changes create persistent candidates and activity notifications.

Each candidate records its upstream source, source URL, version/revision where available, summary, release date where available, affected component class and detected feature tags. A metadata change is not a compatibility result. A source is only marked ALREADY_INSTALLED when a Director-registered inventory records the exact source version. Until a production ComfyUI endpoint, installed nodes and versions, pinned model files/hashes, VRAM and persistent storage are inspected, other candidates remain REQUIRES_MANUAL_APPROVAL.

## Production inventory contract

The state branch also contains `state/ltx_environment_inventory.json`, initially marked `NOT_CONNECTED`. It is deliberately separate from the update history. Once the GPU/ComfyUI environment is funded and configured, a trusted inventory exporter may populate it with:

- ComfyUI version and commit, Python/PyTorch/CUDA versions, and installed custom-node repository versions/commits.
- The fixed LTX-2.5 model revision and installed model/adapter file names, sizes and cryptographic/LFS hashes.
- GPU model and total VRAM, plus confirmation of an attached persistent storage mount and available bytes.
- Explicit, version-pinned workflow compatibility test results.

The inventory schema is `config/ltx_environment_inventory.schema.json`. It rejects unknown fields and has no place for endpoints, access tokens, passwords or API keys. The connected status is accepted only when ComfyUI/runtime/GPU/storage/LTX-2.5 details and explicit node/model arrays are present. Run `python scripts/ltx_update_scheduled_check.py --inventory-file state/ltx_environment_inventory.json --print-inventory-fingerprint` to validate it and obtain the environment fingerprint.

A compatibility result is used only when its source/version and environment fingerprint exactly match the current inventory and a workflow test has completed. If the ComfyUI commit, node versions, model hashes, GPU or storage changes, the fingerprint changes and old test results no longer qualify. This is a metadata gate, not a claim that a production installation has been tested.

The manager estimates the sum of known file sizes from upstream manifests and compares it with recorded free storage. The result is labelled `SUFFICIENT_FOR_DOWNLOAD_ONLY`, `INSUFFICIENT_FOR_DOWNLOAD` or `UNKNOWN`; it excludes backups, temporary extraction space and dependencies. VRAM requirement is never inferred from file size alone.

## Current safety boundary

Automatic installation, model downloads, ComfyUI mutation, workflow activation and GPU jobs remain disabled. The Render console serves as the read-only dashboard and state viewer; it is not a model asset store. All large model files and real workloads must stay in the separately configured GPU/ComfyUI environment.

Before an installer is enabled, a separate staging adapter must exist with Director approval, immutable backups, file integrity checks, dependency/licensing review, isolated ComfyUI tests and rollback. Failure must restore the last known-good node/workflow/model configuration. This Phase 1 is scheduled discovery and notification plumbing, not a complete automated installer.

## Notifications

The state document stores bounded activity and notification histories (up to 250 entries), including new-source-change, compatibility-review, manual-action, source-failure and source-recovery events. The console reads the latest state from the dedicated branch and caches it locally when possible. Email notifications are not configured because no SMTP provider or credentials are available.

## Operational acceptance

Mock tests cover scheduled interval enforcement, baseline creation, simulated release and model-revision changes, documentation change detection, per-source failures, persistent JSON round trips and conservative compatibility classification. This validates monitor control logic only. It does not claim a live scheduler run, real ComfyUI install, workflow registration or GPU output verification.
