# HIS RISEN updater integration audit — 2026-10-27

## Candidate package and repository staging

Verified candidate: `his_risen_controller_ltx25_updater_ui_integrated_2026-10-26.zip`

- Size: 1,032,148 bytes
- SHA-256: `77c74f84e1e94e356ac818d6aff92117db10470908963186138f98ca8bf65229`
- 73 regular files (91 ZIP entries including directories)
- Exact SHA-256 and ZIP integrity: passed in GitHub Actions.
- Extracted layout and Python bytecode compilation: passed.
- Dependencies from `app/requirements.txt`: installed successfully in CI.
- Regression suite: **44 tests passed** in GitHub Actions.
- Console startup smoke test: passed; `/health` returned `{"ok": true, "service": "HIS RISEN Director Console"}`.
- Successful CI run: https://github.com/kingdomchroniclesstudio-ai/kingdom-chronicles-platform/actions/runs/40548852329

The workflow uses `HRF_DIRECTOR_PIN=123456` only as a temporary test value in its isolated runner. This is not a Render environment-variable change and is not a production credential.

The archive was inspected in the earlier verification pass: `director_console.py` includes the **LTX Update Monitor**, **Check for Updates** action, and `/api/updates/check` integration; the updater module, CLI command, and related tests are present.

The exact candidate bytes are staged at the existing deployment artifact path:
`apps/his_risen_controller_ltx25_audited_update_2026-10-10 (2).zip`

The redundant `(5).zip` duplicate and the known-invalid 2-byte `apps/his_risen_director_console_render_ready.zip` placeholder have been removed from the review branch only. The configured deployment artifact path was not renamed.

A direct live-check attempt from the execution environment could not resolve outbound hostnames (`Temporary failure in name resolution`) for the four configured sources. The checker returned per-source failures without crashing and wrote no observation cache. This is an environment networking limitation, **not** evidence that upstream sites are down. Live source availability remains unverified.

## Console updater integration

The candidate adds an **LTX Update Monitor** card with a **Check for Updates** action in the Director Console. The action calls the authenticated `POST /api/updates/check` endpoint and displays per-source reachability, metadata change status, and errors. Client-supplied configuration is rejected; the UI escapes returned text before displaying it.

The updater checks official Lightricks GitHub release metadata, Hugging Face model metadata, and documentation reachability. Its local observation cache is not an installed-version manifest. First observations and metadata differences are manual-review candidates, not proof that an update is compatible or needed.

## Safety guarantees

This check does not install controller code, download model weights, alter the capability manifest, silently switch model families, or start GPU jobs. The endpoint is protected by the existing Director session and same-origin checks. The CI regression suite covers UI presence, authentication, request validation, read-only result handling, and existing controller lifecycle behavior.

## Deployment configuration and gate — still pending

- A read-only inspection of Render confirms service `his-risen-director-console` is configured to track `main`, with automatic deployment on commits to that branch.
- The Render build command unpacks `apps/his_risen_controller_ltx25_audited_update_2026-10-10 (2).zip` into `app` and installs `app/requirements.txt`; its start command runs `app/director_console.py`. These paths match the staged artifact's intended layout, and the same extraction/startup path passed the isolated CI smoke test.
- The review branch is not the service's deployment branch; staging these changes did not trigger a production deploy.
- `main` remains unchanged. No Render settings were changed and no production deployment was triggered.
- Before production deployment, review the successful CI run, then conduct the approved deployment and a controlled smoke test on Render in Mock Mode. Confirm outbound network access before treating update-source results as live.
- Real LTX generation remains unverified and must stay off until ComfyUI/LTX-2.5, compatible workflows, model files, and GPU access are available.

## Reviewable source patch set

Code-level diffs are committed on the review branch under `docs/patches/his-risen-updater-integration/`:
- `01-director-console.patch`
- `02-update-checker.patch`
- `03-console-tests.patch`
- `04-updater-tests.patch`
- `README.md` documents application order and scope.

These text patches are review materials; the deployment artifact itself is staged at the configured repository path on the review branch.
