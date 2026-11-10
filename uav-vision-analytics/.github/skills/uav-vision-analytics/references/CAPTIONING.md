<!-- SPDX-FileCopyrightText: (C) 2026 Intel Corporation -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Captioning (VLM) Reference — UAV Vision Analytics

Any camera can run a vision-language model (VLM) alongside detection to
publish natural-language scene captions over MQTT. Captioning is declared
per camera in `configs/cameras-*.yaml` (`captioning:` block, see
`references/CAMERAS.md`) — it is never a separate service or a pipeline you
hand-write; it selects one of the pre-generated `*_<vlm>` pipelines already
in `config.json`.

## How a Captioning Pipeline Is Built

A captioned pipeline `tee`s the decoded stream right after the source so
detection and captioning run independently and at different rates:

```
source ! decodebin3 ! tee name=split
  split. ! queue ! gvadetect ... ! gvapython (telemetry overlay)
         ! gvametaconvert ! gvametapublish ! gvafpscounter ! appsink   (unchanged detection branch)
  split. ! queue leaky=downstream max-size-buffers=2
         ! videorate drop-only=true ! video/x-raw,framerate=1/5        (1 frame every 5 s)
         ! videoscale ! videoconvert ! video/x-raw,format=BGRA,width=[1,W],height=[1,H]
         ! gvagenai name=captioner model-instance-id=... model-path=... device=CPU|GPU
                    prompt="..." chunk-size=1
                    generation-config="max_new_tokens=...,num_beams=1,do_sample=false,temperature=0.1,repetition_penalty=1.1"
                    frame-rate=0 metrics=true
         ! gvametaconvert add-empty-results=true name=caption_metaconvert
         ! gvapython class=MQTTPublisher function=process
                      module=/home/pipeline-server/gvapython/mqtt_publisher/mqtt_publisher.py
                      name=mqtt_publisher kwarg={"topic":"<mqtt_topic>"}
         ! fakesink sync=false async=false
```

Key points when reading/writing this branch:

- **`frame-rate=1/5`** via `videorate drop-only=true` throttles the VLM branch to one frame
  every 5 seconds — the VLM is far slower than the detector, and this is also the cadence used
  in `captioner_model_path`/completion-criteria checks (expect a new caption roughly every 5 s).
- **`chunk-size=1`** and `generation-config` are fixed by the shipped pipelines; only
  `max_new_tokens` and `prompt` are exposed as per-camera parameters.
- **`gvapython ... class=MQTTPublisher`** (module shipped inside the DL Streamer Pipeline
  Server image at `/home/pipeline-server/gvapython/mqtt_publisher/mqtt_publisher.py` — this
  skill does **not** generate that file) publishes the caption text to the MQTT topic given in
  `kwarg={"topic": ...}`. Topic default: `uav/caption/<camera id>`.
- The detection branch is otherwise identical to the non-captioning pipeline (same
  `gvadetect`/telemetry-overlay/`gvametaconvert`/RTSP-sink chain) — captioning never changes
  how detection or the RTSP stream work.
- `device=CPU|GPU` only — `gvagenai` (OpenVINO GenAI `VLMPipeline`) has no NPU plugin. Never
  generate `device=NPU` for the captioning branch.

## Pipeline Parameters (captioning-enabled pipelines)

| Parameter | Pattern / range | Default | Meaning |
| --- | --- | --- | --- |
| `captioner_model_path` | `^/home/pipeline-server/resources/ov_models/[A-Za-z0-9_./-]+$` | `.../ov_models/<cpu\|gpu>/InternVL2-1B` | OpenVINO IR VLM folder (see Model Format below) |
| `captioner_instance_id` | `^[a-z0-9_]+$` | `instvlm_cpu` / `instvlm_gpu` | Shared model instance across cameras using the same model+device |
| `captioner_prompt` | `^[A-Za-z0-9 ,.?'-]+$` | `Describe what you see in the scene.` | Letters, digits, spaces, `, . ? ' -` only — anything else is rejected by both the pipeline schema and `camera_config.py` |
| `captioner_max_new_tokens` | integer, `1`–`4096` | `50` | Caps caption length and generation time; must finish within the ~5 s frame interval or captions fall behind |
| `frame_width` / `frame_height` | integer ≥ 0 | `896` / `448` | Upper bound the VLM branch scales frames to before `gvagenai` |
| `mqtt_topic` | `^uav/caption/[A-Za-z0-9_-]+$` | `uav/caption/<camera>` | MQTT topic the caption text is published to |

These map 1:1 to a camera's `captioning.model` / `captioning.device` /
`captioning.prompt` / `captioning.max_new_tokens` in `cameras-*.yaml` —
`camera_config.py build_plan()` fills them in; never assemble this REST
payload by hand when a camera file exists.

## Model Format and Location

The VLM must be a complete **OpenVINO IR export** loadable by
`openvino_genai.VLMPipeline` — not a PyTorch/safetensors/ONNX checkpoint.
Expected layout under `resources/ov_models/<device>/<model>/`:

| Files | Purpose |
| --- | --- |
| `openvino_language_model.{xml,bin}` | Language-model decoder |
| `openvino_text_embeddings_model.{xml,bin}` | Text embeddings |
| `openvino_vision_embeddings_model.{xml,bin}` | Vision encoder |
| `openvino_tokenizer.{xml,bin}`, `openvino_detokenizer.{xml,bin}` | Tokenizer / detokenizer IR |
| `config.json`, `generation_config.json`, `preprocessor_config.json` | Model / generation / preprocessing config |
| `chat_template.jinja` (or inside `tokenizer_config.json`) | Prompt template |

Models published under the `OpenVINO/` org on Hugging Face already ship in
this format. Exact file names vary slightly by architecture (e.g. Gemma
adds `openvino_text_embeddings_per_layer_model.{xml,bin}` — keep it).

## Getting the Model (`make vlm-model`)

```bash
make vlm-model                                   # InternVL2-1B, CPU+GPU, int8 (default)
make vlm-model VLM_MODEL_ID=<org>/<model> VLM_DEVICE=CPU,GPU VLM_WEIGHT_FORMAT=int8
```

- Shows the model's license and prompts for confirmation (`ACCEPT_LICENSE=y` to skip).
- Uses the same `download_models.sh` as the Live Video Captioning sample app, fetched once
  into `.cache/`.
- Produces `resources/ov_models/<device>/<model>/` for every device listed in `VLM_DEVICE`.
- `VLM_WEIGHT_FORMAT`: `int8` (default), `int4`, or `fp16`.

Alternative export paths (own `python3 -m venv .cache/venv-vlm` environment, separate from
the detection-model venv):

```bash
pip install "optimum[openvino]" huggingface_hub
optimum-cli export openvino --model <org>/<model> --weight-format int8 \
  resources/ov_models/gpu/<model>                 # add --trust-remote-code for models with custom modeling code
# or, for an already-exported model:
hf download OpenVINO/<model>-ov --local-dir resources/ov_models/gpu/<model>
```

Repeat per device a camera actually uses (folders are per-device so
precision can differ between CPU and GPU).

## Applying/Changing a Captioning Model

1. Set `captioning.model` (and `captioning.device`) for the camera(s) in `configs/cameras-*.yaml`.
2. `make check-cameras` — reports `captioning model not found` if the OpenVINO IR folder for
   that device/model is missing; a missing model does not start the camera.
3. `make start-rtsp` (or disarm/arm the vehicle) to apply — the file is re-read at every arming.
4. Watch captions: `docker exec uav-va-broker mosquitto_sub -t uav/caption/<camera>` (`mqtt-broker` in UAVSDK mode).

For a pipeline started by hand (bypassing `camera_config.py`), pass the container path
in `parameters.captioner_model_path` directly (see `references/PIPELINE.md`).

## Guardrails Specific to Captioning

- Never set `captioning.device: npu` — `gvagenai` has no NPU plugin; the pipeline fails to start.
- Keep `prompt` to the validated character set; punctuation outside `, . ? ' -` (quotes,
  colons, parentheses, emoji, newlines) is rejected before the pipeline ever starts.
- Tune `max_new_tokens` down (or move to GPU) if captions visibly lag — the VLM branch samples
  one frame every 5 s regardless of detection FPS, so a model/prompt that needs longer than
  that per caption falls progressively behind.
- Cameras sharing the same `captioning.device` + `captioning.model` share one loaded VLM
  instance (`captioner_instance_id`) — memory cost does not scale per camera for same-model
  captioning, but generation requests still queue behind one another.
- A caption-enabled camera still needs its `detection.model` to be a valid OpenVINO IR
  detection model — captioning never replaces the detection branch, it runs beside it.
