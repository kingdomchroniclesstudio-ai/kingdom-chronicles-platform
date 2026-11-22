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

## Current safety boundary

Automatic installation, model downloads, ComfyUI mutation, workflow activation and GPU jobs remain disabled. The Render console serves as the read-only dashboard and state viewer; it is not a model asset store. All large model files and real workloads must stay in the separately configured GPU/ComfyUI environment.

Before an installer is enabled, a separate staging adapter must exist with Director approval, immutable backups, file integrity checks, dependency/licensing review, isolated ComfyUI tests and rollback. Failure must restore the last known-good node/workflow/model configuration. This Phase 1 is scheduled discovery and notification plumbing, not a complete automated installer.

## Notifications

The state document stores bounded activity and notification histories (up to 250 entries), including new-source-change, compatibility-review, manual-action, source-failure and source-recovery events. The console reads the latest state from the dedicated branch and caches it locally when possible. Email notifications are not configured because no SMTP provider or credentials are available.

## Operational acceptance

Mock tests cover scheduled interval enforcement, baseline creation, simulated release and model-revision changes, documentation change detection, per-source failures, persistent JSON round trips and conservative compatibility classification. This validates monitor control logic only. It does not claim a live scheduler run, real ComfyUI install, workflow registration or GPU output verification.
