# Real ComfyUI workflow files — installation and export contract

The files in this directory are intentionally not enabled yet. The current `*.api.json` files are contract fixtures only; they are not genuine LTX-2.5 API workflows.

## Required files

For the initial supported path, create these from ComfyUI's **File → Export Workflow (API)** output:

- `L25-T2V-SINGLE.api.json`
- `L25-T2V-SINGLE.mapping.json`
- `L25-I2V-SINGLE.api.json`
- `L25-I2V-SINGLE.mapping.json`
- `L25-FIRST-LAST-FRAME-SINGLE.api.json`
- `L25-FIRST-LAST-FRAME-SINGLE.mapping.json`

The first-frame preset should reuse the I2V workflow/mapping unless a verified reason requires a separate graph. Native multi-shot remains a T2V prompt-contract question, not a separate arbitrary graph. Continuation remains disabled until a specific official workflow has been validated.

## Export procedure (no GPU run required)

1. Install/use a ComfyUI frontend version that can load the current official LTX-2.5 templates.
2. Load the template: `video_ltx2_5_t2v`, `video_ltx2_5_i2v`, or `video_ltx2_5_flf2v`.
3. Do not queue the graph; do not click Download all; no models need to be installed merely to export.
4. Choose **File → Export Workflow (API)**.
5. Save the exact downloaded JSON under its matching `*.api.json` filename.
6. Inspect the exported graph and build the paired mapping JSON from the actual node IDs, `class_type` values, and input names.
7. Run the offline validation/tests before touching any `ready` value.

The UI-format template and the API-format export are different JSON formats. Never paste the visual template JSON into this directory and label it API.

## Mapping format target

The current simple mapping contract is too weak for final production. Before enabling a workflow, the mapping schema should validate:

- logical controller value;
- one or more API target node IDs;
- expected `class_type` for each target;
- exact input name;
- whether the value is mandatory;
- value type/coercion policy;
- for image nodes, the ComfyUI-returned uploaded filename, not the controller asset ID.

Node IDs must come from the exported API JSON. Do not guess IDs from visual-template node IDs or subgraph internal IDs.

## Ready flag

Keep every preset `ready: false` until the acceptance criteria in `docs/COMFYUI_LTX25_WORKFLOW_INTEGRATION_AUDIT_2026-11-04.md` have been met, including an actual short LTX render on a real ComfyUI/GPU instance.
