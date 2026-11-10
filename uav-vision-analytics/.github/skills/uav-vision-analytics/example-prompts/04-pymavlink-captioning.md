<!-- SPDX-FileCopyrightText: (C) 2026 Intel Corporation -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Example: PX4 SITL Simulation — Captioning (VLM) on Two of Three Cameras

Build a full end-to-end UAV object detection, telemetry overlay and
scene-captioning stack in `./uav-caption-stack/` using the uav-vision-analytics
skill.

**Scenario:** Simulate a UAV flight using PX4 SITL with three cameras (front,
back, bottom). All three cameras detect objects with YOLO11s. The front and
bottom cameras additionally run a vision-language model to publish
natural-language scene captions over MQTT — front on GPU with the default
prompt, bottom on CPU with a custom one-sentence prompt. The back camera has
captioning turned off.

**Requirements:**
- Deployment mode: `pymavlink`
- Cameras:
  - `front_camera`: `file` (`uav_sample_front.avi`), detection `gpu`, captioning `gpu`, default prompt, 50 tokens
  - `back_camera`: `file` (`uav_sample_back.avi`), detection `npu`, captioning `off`
  - `bottom_camera`: `file` (`uav_sample_bottom.avi`), detection `cpu`, captioning `cpu`,
    prompt "Describe the terrain and any objects below the drone in one sentence.", 40 tokens
- Model: `yolo11s` (default)
- VLM model: `InternVL2-1B` (default)
- Output directory: `./uav-caption-stack/`

Produce:
- `docker-compose-pymavlink.yml` with all required services, including `nginx` reverse proxy
- `configs/cameras-pymavlink.yaml` declaring the three cameras above (captioning block only
  on `front_camera` and `bottom_camera`)
- `configs/config-pymavlink.json` with the fixed pipeline matrix (do not hand-write new
  pipeline names for these cameras — `uav_object_detection_gpu_gpu`,
  `uav_object_detection_npu`, `uav_object_detection_cpu_cpu` already cover them)
- `Makefile` with `model`, `vlm-model`, up/down, `check-cameras`, `start-rtsp` targets
- `.env.example` template
- `tests/` pytest suite including `test_captioning.py`

Verify against all completion criteria before declaring success, including:
caption MQTT topics `uav/caption/front_camera` and `uav/caption/bottom_camera`
receive a new message roughly every 5 seconds once armed, and `back_camera`
never gets a caption topic.
