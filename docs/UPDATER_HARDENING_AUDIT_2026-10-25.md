# HIS RISEN updater integration audit — 2026-10-27

## Verified candidate package

Candidate: `his_risen_controller_ltx25_updater_ui_integrated_2026-10-26.zip`

- Size: 1,032,148 bytes
- SHA-256: `77c74f84e1e94e356ac818d6aff92117db10470908963186138f98ca8bf65229`
- 73 regular files (91 ZIP entries including directories)
- Exact SHA-256 and ZIP integrity: passed in GitHub Actions.
- Extracted layout, Python bytecode compilation, and dependency installation: passed.
- Regression suite: **44 tests passed** in GitHub Actions.
- Isolated console startup smoke test: passed; `/health` returned `{"ok": true, "service": "HIS RISEN Director Console"}`.
- Latest full package validation and source probe: https://github.com/kingdomchroniclesstudio-ai/kingdom-chronicles-platform/actions/runs/40549526387

The CI workflow sets `HRF_DIRECTOR_PIN=123456` only for the isolated smoke-test runner. This is not a Render environment change or a production credential.

## Repository integration

The package is staged at the existing deployment artifact path:
`apps/his_risen_controller_ltx25_audited_update_2026-10-10 (2).zip`

The LTX Update Monitor, **Check for Updates** action, authenticated `POST /api/updates/check` endpoint, updater module, CLI command, and related tests are included. The redundant `(5).zip` duplicate and known-invalid 2-byte placeholder archive were removed as part of the review changes.

Pull request #1 was merged by squash into `main` on 2026-10-27:
https://github.com/kingdomchroniclesstudio-ai/kingdom-chronicles-platform/pull/1

Merge commit: `87ceedfeabfa7a5953950ebf31c676eeba4c6c9c`

## Upstream metadata diagnostic

On 2026-10-27, the GitHub-hosted CI runner executed `python cli.py check-updates`. All four configured upstream sources reported reachable with HTTP 200:

- Lightricks GitHub release metadata returned latest tag `v1.5.0` (published 2026-10-18).
- LTX workflow compatibility documentation.
- LTX API changelog documentation.
- Hugging Face LTX-2.5 Diffusers metadata, revision `4791a1100e0cf97f7ed5c55c12dd71dce13f9dd3`, last modified 2026-10-22.

This confirms reachability from the CI runner at that time, not necessarily from Render. First observations are reported as `first_observation_needs_manual_baseline`; the updater does not infer compatibility or apply updates. The interactive execution environment could not resolve the public Render hostname during its direct HTTP attempt, so the live public health/UI response could not be independently confirmed from that environment.

## Safety

The updater is read-only. It does not install controller code, download model weights, modify the capability manifest, switch model families, or start GPU jobs. The route is protected by the existing Director session and same-origin checks. CI tests cover updater UI presence, authentication, request validation, read-only behavior, and the existing Mock Mode lifecycle.

No real LTX/GPU generation job was started during this rollout. Real generation remains unverified and must stay off until ComfyUI/LTX-2.5, compatible workflows, model files, and appropriate compute are deliberately configured.

## Render deployment — 2026-10-27

Render service: `his-risen-director-console`
URL: https://his-risen-director-console.onrender.com
Service ID: `srv-dav72141nsns738v6jq0`

A read-only service inspection confirmed Render tracks `main`, with auto-deploy enabled. The configured build command extracts the exact staged ZIP into `app`, installs `app/requirements.txt`, and starts `app/director_console.py`.

The merge did not trigger an automatic deployment promptly, so a deployment was explicitly started against the merge commit. Render reported:
- Build successful.
- Start command executed: `cd app && python director_console.py --host 0.0.0.0 --port $PORT`.
- Service live message emitted.
- Deployment `dep-dbgdv96c6qcc738fuqsg` reached status `live` for merge commit `87ceedfeabfa7a5953950ebf31c676eeba4c6c9c`.

No Render environment variables or build/start settings were changed. Automated tests verified Mock Mode behavior in CI. A direct live UI interaction (sign in, confirm the LTX Update Monitor, press **Check for Updates**) remains to be confirmed from a browser because the direct HTTP probe from this execution environment failed DNS resolution and Render request logs showed no external test request. CI source reachability does not guarantee Render has identical outbound network access.

## Review materials

The source patch set is preserved at `docs/patches/his-risen-updater-integration/`:
- `01-director-console.patch`
- `02-update-checker.patch`
- `03-console-tests.patch`
- `04-updater-tests.patch`
- `README.md` documents the application order.

The automated validation workflow is `.github/workflows/his-risen-updater-validation.yml`.
