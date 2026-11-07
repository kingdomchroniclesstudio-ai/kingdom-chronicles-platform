# HIS RISEN STUDIOS — Production Control Room

## Purpose

The pre-GPU control-room upgrade adds a simple production workspace around the existing HIS RISEN Director Console. It is designed for film planning, test discipline, continuity reference organisation and director review.

## Production rooms

- **Studio Overview** — project, scene, shot, test and asset totals; Mock Mode and storage status; read-only LTX update monitor; truthful Director Command placeholder.
- **Film Projects** — create a film project, add numbered scenes, add shot-code records, and track project/scene/shot status.
- **Testing Laboratory** — log planned or completed experiments with purpose, model, workflow, prompt, seed, resolution, frame rate, duration, comparison group, notes, manually entered GPU time and cost. Tests sharing a comparison-group label are shown together for visual review.
- **Asset Library** — register character, location, prop, wardrobe, reference and sound records with identifiers, descriptions, tags and continuity notes.
- **Review Room** — view existing controller takes, use the existing formal approve/reject actions, and store director notes against an existing take ID. A note is not an approval decision.
- **Production Reports** — portfolio totals, approved-shot progress, experiment outcomes and manually logged cost/time figures.
- **Generation Room** — retains the existing Mock Mode test and guarded single-shot T2V form. Real generation remains locked by the controller's preflight and cost acknowledgement.

## Data and persistence

The workspace records are stored in `studio_workspace.sqlite3` under the directory returned by `resolve_data_root()`. When `HRF_DATA_DIR` points to an attached Render persistent disk, the workspace database follows that durable root. Without the environment variable, the app's resolved data root may be the extracted application directory and is not durable across Render deployments/restarts. The dashboard shows the storage configuration state.

SQLite uses foreign-key constraints, WAL journaling, a busy timeout and full synchronous writes. A forward migration adds the test-record update timestamp to an existing workspace database.

## Boundaries in this release

- Asset records are metadata and continuity notes. Direct image/binary uploads and image thumbnails are deferred until persistent media storage and retention are configured.
- Test GPU minutes and cost are entered by the director; this release does not read live RunPod billing or GPU telemetry.
- Comparison groups organise recorded parameters but do not score visual quality automatically.
- Studio notes do not approve/reject controller takes. The existing director approval actions remain authoritative.
- Production project records are a planning layer. The current single-shot generation form still uses its validated specification inputs; a later integration can prefill those inputs from selected project/scene/shot records after end-to-end acceptance.
- Director Command remains visibly disconnected; it does not execute natural-language instructions.
- This release does not install ComfyUI, download LTX weights, enable real workflow presets, provision storage or start GPU jobs.

## API

All new routes are behind the existing authenticated Director session.

GET:
- `/api/studio/overview`
- `/api/studio/projects`
- `/api/studio/scenes?project_id=...`
- `/api/studio/shots?project_id=...`
- `/api/studio/tests?project_id=...`
- `/api/studio/assets?project_id=...&category=...`
- `/api/studio/reviews?take_id=...`
- `/api/studio/reports`

POST:
- `/api/studio/projects`
- `/api/studio/scenes`
- `/api/studio/shots`
- `/api/studio/tests`
- `/api/studio/assets`
- `/api/studio/reviews`
- `/api/studio/{projects|scenes|shots|tests}/{id}/status`

Mutating workspace POST requests require an authenticated session and same-origin `Origin` header. Input is length-limited and statuses/categories are allow-listed.
