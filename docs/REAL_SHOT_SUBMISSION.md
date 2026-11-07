# HIS RISEN STUDIOS — Real Shot Submission Runbook

## Scope of this release

The new dashboard submission path supports one real **single-shot Text-to-Video (T2V)** request at a time. It is not a batch renderer.

The first release deliberately limits submissions to:
- 16:9 aspect ratio.
- 1–20 whole-number seconds.
- 720p, 1080p, 1440p or 4K.
- Whole-number frame rate from 1 to 60 fps.
- A required nonnegative integer seed.
- The LTX-2.5 single-shot T2V preset only.

Image-to-video, first-frame, first/last-frame, continuation and multi-shot remain disabled until their genuine ComfyUI API exports and mappings have been separately validated. A quality-preset selector is intentionally omitted because the current mapping contract does not yet expose a verified quality control.

## Preconditions before unlocking a real shot

1. Keep the controller in Mock Mode while cloud infrastructure is being prepared. Do not change the live service to the real backend just because the dashboard has a submission form.
2. Attach a durable storage volume to the Render service. Set `HRF_DATA_DIR` to an absolute directory on that mounted volume. The controller database must resolve inside that directory. The submission preflight rejects the ordinary ephemeral filesystem and rejects a database outside the configured data root.
3. Configure the remote ComfyUI endpoint with HTTPS and its required authentication. Do not expose an unauthenticated ComfyUI port publicly.
4. Install the compatible LTX-2.5 ComfyUI node package and model assets in the cloud GPU environment. The dashboard preflight checks API reachability and node presence; it does **not** download nodes or model weights.
5. In ComfyUI, open the genuine LTX-2.5 T2V template and use **Export (API)**. Do not use the visual workflow JSON as the controller API graph.
6. Replace the T2V contract fixture with that exported API graph. Build its mapping from the actual exported node IDs and input names. The mapping must explicitly require all six controls: `prompt`, `duration`, `seed`, `width`, `height` and `fps`.
7. Verify that every mapped node and input exists in the exported graph and that every required node class appears in ComfyUI's `/object_info` response.
8. Only after that review, set `L25-T2V-SINGLE.ready` to `true`. Do not enable any other preset as part of this first T2V release.

## What the dashboard preflight verifies

The read-only gate requires:
- The production ComfyUI adapter rather than Mock Mode.
- A configured `HRF_DATA_DIR` on an actual mounted volume, with the controller SQLite database inside it.
- An explicitly approved T2V preset, a valid API-format workflow and complete required mappings.
- A reachable ComfyUI `/system_stats` endpoint with a CUDA device reporting at least 32 GiB of VRAM.
- Every workflow node class present in ComfyUI `/object_info`.

The gate does not queue a prompt, download files, install nodes, load the model, verify that a model can render, or prove that audio/video outputs are correct. It is a readiness check, not a successful-generation claim. A fresh preflight is run again immediately before submission.

## Submission and duplicate protection

A real submission requires the authenticated director session, a same-origin browser request, a valid shot specification and the server-verified cost acknowledgement. The checkbox is not merely a visual confirmation: the API rejects a missing or false acknowledgement.

A UUID request key and specification hash are stored with the take reservation in SQLite. Retries after controller restart return the existing take. The controller also checks for an existing pending, running or completed take with the same film/scene/shot identity, so refreshing the browser and submitting the same shot again does not create another ComfyUI job. A different specification for that same shot ID is blocked until the existing take is reviewed.

If a request was reserved but interrupted before its ComfyUI submission state was recorded, the controller will not automatically submit it again. Inspect ComfyUI queue/history and the take record before deciding what to do. This is intentionally safer than risking a duplicate GPU charge.

## First real GPU acceptance test

After all preconditions are satisfied and the director explicitly approves the spend, submit one short T2V test. Check:
- The expected prompt, duration, seed, width, height and frame rate reach the intended API nodes.
- ComfyUI accepts the request and the controller records the prompt ID.
- Queue/history and WebSocket monitoring recover and report progress correctly.
- The resulting video is retrieved from the configured ComfyUI origin and is playable.
- Actual duration, resolution, frame rate, visual quality, motion and any native audio match the request.
- The take remains in the review workflow: only a director-approved take can be exported.

Passing unit tests, fake-ComfyUI tests or the dashboard preflight is not a substitute for this real GPU acceptance test. Keep Mock Mode and the real workflow readiness flags locked until the required infrastructure and authentic API workflow are in place.

## Current release boundary

This code change does not provision RunPod, rent a GPU, download LTX weights, attach Render storage, set `HRF_DATA_DIR`, configure production credentials, enable a real preset, or deploy to Render. Those steps remain separate and require a deliberate production setup after costs and storage have been reviewed.
