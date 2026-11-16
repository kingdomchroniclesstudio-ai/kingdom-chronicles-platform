# HIS RISEN ComfyUI / LTX-2.5 workflow integration audit
**Audit date:** 2026-11-04  
**Scope:** no-cost software preparation only  
**Target route:** official ComfyUI LTX-2.5 templates → ComfyUI API-format workflow → HIS RISEN Director Console  
**Production safety:** all real presets remain disabled; Mock Mode remains the production default.

## Executive finding

The controller's transport and lifecycle scaffolding is present, but its checked-in real-workflow fixtures are not usable LTX workflows. They are tiny contract placeholders and must never be enabled.

The current archive's `workflows/real_presets.json` has six entries, all `ready: false`. The referenced `workflows/real/*.api.json` files are only 3–129 bytes. Several contain a fake `SaveVideo` node with non-existent inputs such as `prompt`, `duration`, `seed`, `input_image`, or `source_video`; two are empty objects. The mapping fixtures target those fake inputs. They are not valid exports from ComfyUI.

This is why the real presets are correctly gated. **Do not set any `ready` flag to true until a real API export has been imported, mapped, and validated.**

## What is already working (software scaffolding)

- The adapter submits API-format graphs through ComfyUI `POST /prompt`.
- It uses a stable ComfyUI `client_id` for the matching WebSocket.
- It polls `/history` and `/queue`, including recovery after a controller restart.
- It supports authenticated image upload to ComfyUI's input folder.
- Remote ComfyUI endpoints require HTTPS; the controller supports `HRF_COMFYUI_BASE_URL` and `HRF_COMFYUI_API_KEY`.
- Output retrieval is restricted to the configured ComfyUI origin.
- Durable state can be redirected with `HRF_DATA_DIR`, but the current Render service is on the Free plan and has no persistent disk.

These features are scaffolding and fake-server regression-tested, not proof of a real server connection or real media generation.

## Official LTX-2.5 workflow sources

Use ComfyUI's built-in official templates as the starting point:

| HIS RISEN use | Official ComfyUI template | Workflow behavior | Preparation decision |
|---|---|---|---|
| Standard text-to-video | `video_ltx2_5_t2v` | Two-stage distilled video + synchronized audio | Primary first integration |
| Image-to-video | `video_ltx2_5_i2v` | Two-stage; animates one supplied start image | Primary second integration |
| First-frame mode | Same I2V template | First frame is the supplied image | Treat as an explicit I2V mode, not a separate graph |
| First + last frame | `video_ltx2_5_flf2v` | Single-stage motion between start and end images | Third integration, Director-gated |
| Native multi-shot | T2V template, subject to prompt-format validation | Multi-shot behavior is expressed in the prompt/model workflow; not a separate guaranteed API graph | Keep disabled until prompt structure and continuity are tested |
| Continuation/extension | No direct equivalent among the three built-in templates | A V2V workflow is not automatically the same as temporal continuation | Keep disabled until an exact continuation workflow is sourced and validated |

Do not repurpose the existing placeholder `L25-CONTINUE-TESTED` as an arbitrary V2V graph.

## Why the visual workflow JSON is not the API workflow

The ComfyUI template JSON is the editable visual graph. It contains layout metadata and, for current LTX templates, nested subgraph definitions. ComfyUI's API expects a different graph representation: a node-ID-keyed object whose nodes contain `class_type`, `inputs`, and optional metadata.

The supported procedure is:

1. Open the exact official LTX-2.5 template in a compatible ComfyUI frontend.
2. Do **not** click Queue and do not use Download all.
3. Choose **File → Export Workflow (API)**.
4. Save the generated API JSON as the controller's workflow source.
5. Preserve its exact node IDs; do not invent IDs or copy IDs from the visual workflow.
6. Validate node classes, input names, linked node references and output node(s) before writing a mapping.

This export step prepares a software artifact; it is not a GPU generation job. It still requires a ComfyUI installation/frontend capable of loading the current template. The export is authoritative because ComfyUI itself resolves and flattens its nested subgraphs.

## Mapping contract required by HIS RISEN

After API exports exist, each mapping file must target actual API nodes and include an expected node class. Mapping validation must fail closed if a node, class, or input is missing. It must not silently skip a required target.

### Shared generation fields

- `prompt`: the approved shot prompt.
- `duration`: seconds, with an explicit rule for converting the controller's numeric duration to the template's integer duration.
- `width` and `height`: derived from the approved resolution and aspect ratio, rounded to the official workflow's supported dimension multiples. The exact chosen values must be recorded in the take snapshot.
- `frame_rate`: the shot's requested frame rate (default 24 only when the shot specification omits it).
- `seed`: fixed integer when supplied. If the exported workflow uses more than one noise input, the mapping schema must support multiple targets.
- `prompt_enhance`: default OFF for HIS RISEN's already detailed prompts, unless the Director explicitly enables it and the optional enhancer model is installed.
- Model and decoder filenames: pinned in the workflow and recorded in the package manifest; never silently substituted.
- Video output: verify the API graph includes the official `SaveVideo` output and confirm the returned history contains a real video descriptor. Verify audio output separately because LTX generates synchronized audio too.

### Image inputs

- I2V / first-frame: upload the registered reference file and map the ComfyUI-returned filename to the real `LoadImage` input.
- First/last-frame: upload both registered images and map the returned filenames to the two distinct `LoadImage` inputs.
- Never map an `asset_id` string directly into a ComfyUI image input; use the filename returned by `/upload/image`.
- The existing adapter already uploads the supplied `profiles.reference_assets`, but the export-specific node IDs and input names still need to be identified from the API graph.

## Controller changes required after API export

1. Replace the fake API JSONs with exports for T2V, I2V and first/last-frame.
2. Replace their mapping fixtures with mappings against real API node IDs and class types.
3. Extend the mapping contract to validate expected `class_type` and to support multiple targets where the graph needs one logical value in more than one node.
4. Extend adapter values to include dimensions and frame rate; define integer duration rounding and dimension constraints with tests.
5. Verify frame-conditioning filenames are uploaded and mapped correctly for both frames.
6. Add fixture tests for each real exported graph: schema validity, required mappings, node/input existence, expected classes, output discovery and no missing references.
7. Add a fake-ComfyUI integration test that captures the exact graph submitted to `/prompt` and checks the mapped values. This is still not a real render test.
8. Keep native multi-shot and continuation disabled until their distinct prompt/workflow contracts are signed off.
9. Set a preset's `ready` flag only after the export, mapping, local tests and real-server validation have all passed.

## Model and custom-node compatibility

The current official ComfyUI T2V/I2V templates use a ComfyUI-specific model stack. Current template metadata includes the INT8 ConvRot distilled transformer and Gemma text encoder, BF16 video/audio VAEs, and the BF16 latent spatial upscaler. The prompt-enhancer encoder is optional and should remain off for the first HIS RISEN baseline.

Do not copy the old native-PyTorch/Diffusers BF16 model list blindly into a ComfyUI template. The LTX compatibility guide distinguishes the ComfyUI-only `*-comfy-int8-convrot` assets from the BF16 assets used by other routes.

The current official LTX ComfyUI guide's Quick Start recommends installing the `ComfyUI-LTXVideo` node pack through ComfyUI Manager (or the repository's documented manual setup) and restarting ComfyUI before loading the LTX-2.5 templates. Treat this node pack as a setup prerequisite unless the exact installed ComfyUI template and `/object_info` preflight prove that every required node is already registered. This node-pack installation is separate from downloading model weights: for the export-only stage, do not click **Download all** and do not queue a generation. Advanced IC-LoRA/HDR/V2V workflows may add further requirements; do not install specialist extras unless a selected workflow needs them.

## Infrastructure boundary (not part of this no-cost work)

The current Render service is Free and has no persistent disk. Render documents persistent disks as available to paid web services, private services and background workers; a disk-backed service is single-instance and cannot use zero-downtime deploys. The controller's `HRF_DATA_DIR` must point to a real persistent mount or external durable store before production state is considered safe.

The current LTX ComfyUI guide lists a CUDA-compatible GPU with 32 GB+ VRAM, 100 GB+ free disk space, and Python 3.12+ as setup requirements for running LTX workflows. Check the live guide again when selecting a GPU provider; do not provision anything during this export-only phase. (The API-export preparation step itself does not queue a model run.)

## No-cost completion checklist

- [x] Inspect actual deployed controller archive and all six real preset fixtures.
- [x] Verify all six real presets are still `ready: false`.
- [x] Verify the current package test suite locally (64 tests passed; tests use Mock Mode/fake ComfyUI, not real generation).
- [x] Identify official built-in T2V, I2V and FLF templates.
- [x] Confirm ComfyUI API export is separate from visual workflow save format.
- [ ] Export official T2V API JSON from a compatible ComfyUI frontend.
- [ ] Export official I2V API JSON.
- [ ] Export official FLF API JSON.
- [ ] Build and validate exact node mappings.
- [ ] Add mapping/dimension/frame-rate/asset tests.
- [ ] Decide whether native multi-shot uses the T2V graph and approved prompt structure.
- [ ] Explicitly keep continuation disabled until a genuine LTX-2.5 continuation workflow is found.
- [ ] Review and merge the software-only change set; do not deploy until the package is ready and the Director approves.

## Acceptance criteria before any real preset can be enabled

- A genuine `Export Workflow (API)` JSON exists for the exact template/version.
- Every mapping resolves to an existing node of the expected class and an existing input.
- Prompt, duration, dimensions, frame rate, seed, and image file names are verified in the final submitted `/prompt` payload.
- The workflow contains its expected `SaveVideo` output.
- Fake-server regression tests pass for queue, history, WebSocket, image upload and output discovery.
- A real ComfyUI server validates `/object_info`, accepts the workflow without validation errors, and completes a short, low-resolution GPU-backed test.
- The returned output is visually inspected and is demonstrably generated by LTX-2.5, not a placeholder.
- Only then may the specific preset be changed to `ready: true`.

**Current conclusion:** the issue is clearly bounded and solvable. The remaining no-cost dependency for exact API mappings is a real ComfyUI API export. GPU, model weights, persistent paid storage and real rendering are separate later gates.
