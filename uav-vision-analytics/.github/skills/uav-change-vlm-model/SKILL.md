---
name: uav-change-vlm-model
description: >-
  Download/export a different vision-language model (VLM) for scene
  captioning in an already-deployed uav-vision-analytics stack, or tune an
  existing captioning camera's prompt/caption length/device, via `make
  vlm-model` and configs/cameras-*.yaml. USE FOR: "use a different/better
  captioning model", "captions are too slow / too long / cut off", "change
  the caption prompt", "turn on captioning for this camera", "captions
  aren't appearing on MQTT". DO NOT USE FOR: the object-detection model (use
  `uav-change-detection-model`), adding/removing a camera or changing its
  video source (use `uav-manage-cameras`), editing the captioning pipeline's
  GStreamer elements directly (use `uav-manage-pipelines`), or scaffolding a
  brand-new stack (use `uav-vision-analytics`).
license: Apache-2.0
compatibility: >-
  Requires an already-deployed uav-vision-analytics stack checked out at a
  known path. The VLM runs on CPU or GPU only (never NPU) via `gvagenai` /
  OpenVINO GenAI `VLMPipeline`, and must be a complete OpenVINO IR export —
  not a PyTorch/safetensors/ONNX checkpoint.
---

<!-- SPDX-FileCopyrightText: (C) 2026 Intel Corporation -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Change UAV Captioning (VLM) Model Skill

Scene captions come from a vision-language model run by `gvagenai`. This
skill covers getting a different VLM (or re-exporting the bundled one), and
tuning an already-captioning camera's prompt, caption length, or device, in
an **already-deployed** uav-vision-analytics stack. No pipeline or compose
edit is needed — captioning is selected per camera in `configs/cameras-*.yaml`.

## Canonical Documentation (read before acting — do not rely on memorized snippets)

| Task | Read this file in the target repo first |
| --- | --- |
| Bundled model, required OpenVINO IR format, `make vlm-model`, `optimum-cli` export, applying a model to a camera | `docs/user-guide/how-to-customize/model-and-video-management/vlm-model.md` |
| `captioning:` block fields (device, model, prompt, max_new_tokens) and validation | `docs/user-guide/how-to-customize/camera-management/configure-cameras.md` |

Read the live copy in the target repo — the default model id, weight format,
and download-script pin can change between app releases; do not hardcode a
remembered `make vlm-model` invocation.

## How to Use This Skill

1. Confirm `{{STACK_DIR}}` and which camera(s) are in scope.
2. Ask, in one batched question:
   - Goal: get a new/different VLM, re-export the current one, enable
     captioning on a camera that doesn't have it yet, or just tune
     prompt/length/device on an already-captioning camera.
   - If a new model: its Hugging Face id (or "recommend one"), which
     device(s) it must run on (`cpu`/`gpu`), and weight format
     (`int8` default / `int4` / `fp16`).
   - Which camera(s) should use it, and the prompt / max tokens if not default.
3. Read `vlm-model.md` for the exact `make vlm-model` invocation (or the
   `optimum-cli`/`hf download` alternative) and the expected OpenVINO IR
   folder layout, and follow it.
4. Update the camera's `captioning:` block in `configs/cameras-*.yaml`.
5. Validate, apply, and verify per the guardrails and completion criteria.

## Parameter Validation (enforce BEFORE editing the camera file)

| Param | Rule | Why |
| --- | --- | --- |
| `captioning.device` | `cpu` / `gpu` only, never `npu` | `gvagenai` has no NPU plugin |
| `captioning.model` | folder name that exists under `resources/ov_models/<device>/` for every device a camera uses it on | the pipeline fails to load an absent model |
| `captioning.prompt` | letters, digits, spaces, and `, . ? ' -` only | pipeline parameter pattern rejects anything else before the pipeline starts |
| `captioning.max_new_tokens` | positive integer; keep it low enough that generation finishes within the ~5 s sampling interval | a slow prompt/model falls progressively behind, captions arrive late |
| Model folder contents | must be a complete OpenVINO IR export (language model, text/vision embeddings, tokenizer/detokenizer, configs) | a partial export fails at pipeline start, not at file-validation time |

## Execution Guardrails

- `make vlm-model` (and a manual `optimum-cli`/`hf download` run) execute from
  the calling shell on the **host** — not inside a Docker build (`make vlm-model`'s
  script also starts a short-lived `model-download-ephemeral` container, so Docker
  access is needed; logs go to `.model_download_logs/`). If fetching
  `download_models.sh` or the model itself hangs or TLS-fails behind a
  corporate proxy, the fix is exporting `http_proxy`/`https_proxy`/`no_proxy`
  in that shell (and trusting the proxy's root CA if it does TLS inspection),
  never `curl -k`/`--insecure` against the download host; see
  `docs/user-guide/how-to-guides/troubleshooting.md#make-model--make-vlm-model-fail-behind-a-corporate-proxy`.
- Never set `captioning.device: npu` under any circumstance.
- Do not touch `configs/config-*.json` — captioning model selection is a
  camera-file change (`captioning.model`/`captioning.device`); the pipeline
  already takes these as parameters (`captioner_model_path`, `device=`).
- Before downloading/exporting anything, surface the model's license
  requirement to the user (the Make target shows and asks for confirmation;
  don't silently pass `ACCEPT_LICENSE=y` on the user's behalf without them
  agreeing).
- Exporting a VLM downloads several GB and needs RAM roughly the size of the
  model — warn the user before starting a large export, and confirm disk/RAM
  headroom if it's a borderline case.
- Run the export/download once per device the camera(s) actually use
  (`cpu` and/or `gpu`); do not export for a device nothing uses.
- Always run `make check-cameras` after editing the camera file — it reports
  "captioning model not found" before anything restarts.
- Apply with `make start-rtsp` or disarm/arm (file re-read at every arming);
  tell the user if a restart is needed for a change to take effect on an
  already-running pipeline.
- Several VLM instances (different model/device pairs) plus GPU detection share one iGPU. A
  large model (e.g. Gemma 4 E2B, ~5 GB) added next to other GPU VLMs was observed to fail with
  `CL_OUT_OF_RESOURCES` and wedge the pipeline server (REST times out; `docker restart
  uav-va-dlstreamer-pipeline-server` recovers). Trial a new model on one camera first, and
  note it also needs ~1 min to load on first start.
- Cameras sharing the same device + model path share one loaded VLM
  instance — changing it affects every camera using that pair; confirm
  before editing a shared model.

## Completion Criteria

1. The OpenVINO IR folder for the chosen model exists under
   `resources/ov_models/<device>/<model>/` for every device used.
2. `make check-cameras` reports no "captioning model not found" and shows
   the expected captioning device/model/prompt in its table for the
   affected camera(s).
3. `make cameras-status` (once armed) shows the camera's pipeline running
   with the captioning branch active.
4. A caption arrives on `uav/caption/<id>` roughly every 5 seconds once the pipeline is
   running. Host `mosquitto_sub` is usually not installed; use the broker container:
   `docker exec uav-va-broker mosquitto_sub -t 'uav/caption/<id>' -C 2` (pymavlink) or
   `docker exec mqtt-broker mosquitto_sub ...` (UAVSDK).
5. Caption text reflects the new prompt/model; no truncated or repeated
   captions beyond what `max_new_tokens` would explain.
