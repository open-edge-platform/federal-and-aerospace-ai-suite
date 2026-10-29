<!--
SPDX-FileCopyrightText: (C) 2026 Intel Corporation
SPDX-License-Identifier: Apache-2.0
-->

# Change the Captioning (VLM) Model

Each camera's scene captions come from a vision-language model run by the
`gvagenai` element. The model is chosen per camera in
[`configs/cameras-pymavlink.yaml`](../camera-management/configure-cameras.md)
under `captioning.model`; no pipeline or compose edit is needed to switch.
This page covers the bundled model, the format a replacement must be in,
how to download or export one, and how to apply it. For the detection
model, see [Modify the Detection Model](./modify-model.md).

## The bundled model

`make vlm-model` downloads **InternVL2-1B** (`OpenGVLab/InternVL2-1B`) and
converts it to OpenVINO IR, INT8 weights, for the CPU and the GPU:

```text
resources/ov_models/
├── cpu/InternVL2-1B/
└── gpu/InternVL2-1B/
```

The VLM runs on the CPU or the GPU only (not the NPU). The conversion uses
the shared `download_models.sh` from the Live Video Captioning sample
application, fetched once into `.cache/`.

## How a camera selects the model

```yaml
cameras:
  - id: front_camera
    captioning:
      enabled: true
      device: gpu                    # cpu | gpu
      model: InternVL2-1B            # folder name under resources/ov_models/<device>/
      prompt: Describe what you see in the scene.
      max_new_tokens: 50
```

`model` is a folder name; the manager resolves it to
`/home/pipeline-server/resources/ov_models/<device>/<model>` and passes it
to the pipeline as `captioner_model_path`. The folder must exist for the
device the camera uses.

## Required format

`gvagenai` loads the model with `openvino_genai.VLMPipeline`, so the folder
must contain a complete **OpenVINO IR export of the VLM** (not a PyTorch,
safetensors or ONNX checkpoint). A typical export contains:

| Files | Purpose |
| --- | --- |
| `openvino_language_model.{xml,bin}` | Language-model decoder |
| `openvino_text_embeddings_model.{xml,bin}` | Text embeddings |
| `openvino_vision_embeddings_model.{xml,bin}` | Vision encoder |
| `openvino_tokenizer.{xml,bin}`, `openvino_detokenizer.{xml,bin}` | Tokenizer / detokenizer as IR |
| `config.json`, `generation_config.json`, `preprocessor_config.json` | Model, generation and preprocessing configuration |
| `chat_template.jinja` (or in `tokenizer_config.json`) | Prompt template |

Exact file names vary slightly by architecture. Models published under the
`OpenVINO/` organization on Hugging Face are already in this format.

## Get a different model

**Option A — `make vlm-model` with another model id** (uses the same
conversion script as the bundled model):

```bash
make vlm-model VLM_MODEL_ID=<org>/<model> VLM_DEVICE=CPU,GPU VLM_WEIGHT_FORMAT=int8
```

The result is `resources/ov_models/<device>/<model>/` for each device
listed. `VLM_WEIGHT_FORMAT` accepts `int8` (default, smallest and fastest to
load), `int4` or `fp16`.

**Option B — export with `optimum-cli`** (any Hugging Face model id or
local checkpoint `optimum-intel` supports):

```bash
resources/venv/bin/pip install "optimum[openvino]"
resources/venv/bin/optimum-cli export openvino \
  --model <org>/<model> --weight-format int8 \
  resources/ov_models/gpu/<model>
```

Repeat with `resources/ov_models/cpu/<model>` if a camera will run it on the
CPU (the same export works on both devices; the folder is per device so a
different precision can be used for each).

**Option C — download a pre-exported model:**

```bash
resources/venv/bin/pip install "huggingface_hub[cli]"
resources/venv/bin/hf download OpenVINO/<model>-ov --local-dir resources/ov_models/gpu/<model>
```

## Apply it

1. Set `captioning.model: <model>` (and `captioning.device`) for the
   camera(s) in `configs/cameras-pymavlink.yaml`.
2. Validate and apply:

   ```bash
   make check-cameras      # reports "captioning model not found" if the folder is missing
   make start-rtsp         # or disarm/arm; the file is re-read at every arming
   ```

3. Watch the captions:

   ```bash
   mosquitto_sub -h <HOST_IP> -t uav/caption/front_camera
   ```

For a pipeline started by hand, pass the container path in
`parameters.captioner_model_path` (see
[Manage Pipelines — Start a pipeline](../pipeline-management/manage-pipelines.md#start-a-pipeline)).

## Prompt and caption length

`prompt` may contain letters, digits, spaces and `, . ? ' -` only (validated
by `make check-cameras`). `max_new_tokens` bounds the caption length and
therefore the generation time; the pipeline sends one frame to the VLM every
5 s, so a model/prompt combination that takes longer than that per caption
falls behind. Start around 50 tokens and raise it only if captions are cut
short.

## Troubleshooting

`captioning model not found`, a captioning pipeline that goes to `ERROR` at
start, and captions that arrive slowly or stop are covered in
[Troubleshooting — Models & Captioning](../../how-to-guides/troubleshooting.md#models--captioning).
If the model loads but captions are poor, adjust the prompt first; `fp16`
weights on the GPU can be tried, INT8 rarely changes quality noticeably.
