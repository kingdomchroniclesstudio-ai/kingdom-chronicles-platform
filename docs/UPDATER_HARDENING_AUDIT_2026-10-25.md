# HIS RISEN updater hardening — verification note (2026-10-25)

## Scope

The candidate package `his_risen_controller_ltx25_audited_update_2026-10-25_updater_hardened.zip` was inspected independently of this repository branch. The original uploaded archive was preserved.

## Package integrity and tests

- Original package: 73 files; ZIP integrity check passed.
- Candidate package: 73 files; ZIP integrity check passed.
- Expected entry points and directories are present: `director_console.py`, `requirements.txt`, `updates/`, and `workflows/`.
- Regression suite run against the candidate package: **40 passed, 6 subtests passed**.

## Updater safety behavior

The candidate update checker reads structured metadata from the official Lightricks GitHub releases API and Hugging Face LTX-2.5-Diffusers model API. It stores observations in `storage/update_check_state.json`; that file is an observation cache, not an installed-version manifest. The first observation requires a manual baseline; later changes are candidates for review, not proof of compatibility.

The checker does not install code, download model weights, launch GPU jobs, silently switch model families, or modify the capability manifest. The official compatibility and API-changelog pages are checked for reachability only.

## Deployment gate — not yet cleared

This note is an audit record, not a deployment. No Render service was changed and no production deployment was triggered. Before deployment, the candidate package must be staged as the actual deployment artifact, its extraction layout and Render build/start commands checked together, and the deployed app smoke-tested in mock mode. Real LTX generation still requires a working ComfyUI/LTX-2.5 runtime, model files, compatible workflows, and GPU access.
