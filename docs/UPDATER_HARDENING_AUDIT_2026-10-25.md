# HIS RISEN updater integration audit — 2026-10-26

## Candidate package

Candidate: `his_risen_controller_ltx25_updater_ui_integrated_2026-10-26.zip`

- Size: 1,032,148 bytes
- SHA-256: `77c74f84e1e94e356ac818d6aff92117db10470908963186138f98ca8bf65229`
- 73 regular files (91 ZIP entries including directories)
- ZIP integrity check: passed
- Fresh-extraction regression suite: **44 passed**
- Inline console JavaScript syntax check with `node --check`: passed

The package file is currently a generated candidate artifact in the ChatGPT working environment. It has **not** yet replaced the repository's deployment ZIP.

## Console updater integration

The candidate adds an **LTX Update Monitor** card with a **Check for Updates** action in the Director Console. The action calls the authenticated `POST /api/updates/check` endpoint and displays per-source reachability, metadata change status, and errors. Client-supplied configuration is rejected; the UI escapes returned text before displaying it.

The existing updater checks official Lightricks GitHub release metadata, Hugging Face model metadata, and documentation reachability. Its local observation cache is not an installed-version manifest. First observations and metadata differences are manual-review candidates, not proof that an update is compatible or needed.

## Safety guarantees

This check does not install controller code, download model weights, alter the capability manifest, silently switch model families, or start GPU jobs. The endpoint is protected by the existing Director session and same-origin checks. Integration tests cover UI presence, authentication, request validation, read-only result handling, and existing controller lifecycle behavior.

## Deployment gate — not yet cleared

- The repository's current ZIP under `apps/` has **not** been replaced with the candidate.
- No change was made to `main`.
- No Render settings were changed and no production deployment was triggered.
- Before deployment, stage the exact candidate archive, verify its extraction layout against Render's build/start commands, then smoke-test the live console in Mock Mode.
- Real LTX generation remains unverified and must stay off until ComfyUI/LTX-2.5, compatible workflows, model files, and GPU access are available.
