<!-- SPDX-FileCopyrightText: (C) 2026 Intel Corporation -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Benchmark — UAV Vision Analytics Skill

Evaluation baseline for the `uav-vision-analytics` skill. Compares agent output
**with** the skill loaded against a **baseline** without it.

## Scope

The skill scaffolds a complete UAV object detection, MAVLink telemetry
overlay, and optional VLM scene-captioning application using Intel DL
Streamer Pipeline Server. The key differentiator is correct wiring of:

- `configs/cameras-*.yaml` as the single declarative source of which cameras run, on
  which detection device, and whether/how they caption — never hand-written per-camera
  pipeline definitions
- `gvapython` telemetry overlay (MAVLink thread → frame labels → `gvawatermark`)
- Correct DL Streamer Pipeline Server REST API paths (`/pipelines/user_defined_pipelines/{name}`, `instance_id` string from the POST response for DELETE)
- pymavlink armed/disarmed pipeline lifecycle, re-reading the camera file on every arming
- UAVSDK MQTT-triggered lifecycle with `ffprobe` RTSP pre-flight check
- OpenVINO device variants (CPU/GPU/NPU) with correct GStreamer elements
- `ultralytics==8.4.67` pin (CumSum detection head issue on GPU/NPU)
- VLM captioning branch (`tee` → `videorate 1/5` → `gvagenai` CPU/GPU only → MQTT `uav/caption/<camera>`)
  without ever placing it on NPU or skipping the detection branch
- `nginx` reverse proxy with self-signed TLS as the only service publishing ports to the
  host — `dlstreamer-pipeline-server` and `broker` are never exposed directly
- Docker Compose device access (`group_add`, `device_cgroup_rules`, tmpfs pipeline root)
- Self-contained `mavlink-router` build context (never a sibling-repo path)

## Eval Cases

| ID | Case | Should trigger | Focus |
|----|------|---------------|-------|
| 1 | PX4 SITL sim, looped video, all devices (CPU+GPU+NPU) | Yes | Core pymavlink stack, camera-config file, nginx proxy, telemetry overlay |
| 2 | UAVSDK three-camera (nadir/forward/rear) | Yes | UAVSDK mode, ffprobe probe, MQTT trigger, three cameras via one config file |
| 3 | RealSense GPU, RTSP output, pymavlink | Yes | v4l2src, GPU pipeline, device group_add, nginx RTSP passthrough |
| 4 | Cloud-only Prometheus metrics dashboard (no MAVLink) | No | DO NOT USE FOR boundary — no telemetry, no MAVLink |
| 5 | Three cameras, VLM captioning on two of them | Yes | Captioning branch wiring, CPU/GPU-only VLM device, MQTT caption topics, `make vlm-model` |

## What "pass" means

Each eval case lists expectations that must appear in the agent output. A run
passes when every expectation is satisfied. Case 4 passes when the skill does
**not** trigger.

## Expected Benefits of the Skill

Without the skill, a baseline agent commonly:

- Hand-writes a one-off pipeline string per camera instead of using/extending the fixed
  `config.json` matrix and a `cameras-*.yaml` declaration, making every new camera a
  pipeline-authoring exercise instead of a config edit
- Uses wrong REST DELETE path (`/pipelines/{name}/1` instead of `/pipelines/{id}`)
- Omits the `instance_id` capture from POST response
- Misses the `ultralytics==8.4.67` pin causing GPU/NPU inference failures
- Generates a `gvapython` overlay that doesn't start the MAVLink receiver thread
- Uses `multifilesrc loop=true` without `h264parse` (decoding fails on some files)
- Omits `device_cgroup_rules` and `group_add` (GPU/NPU inaccessible in container)
- Hardcodes `version` in `config.json` (collapses all pipelines to one REST path)
- Missing `ffprobe` RTSP probe in UAVSDK mode (pipelines fail on unavailable streams)
- Publishes `dlstreamer-pipeline-server`'s ports directly instead of routing everything
  through a TLS-terminating `nginx` reverse proxy
- Points the `mavlink-router` build context at a sibling repository, so the generated
  stack fails `docker compose up` on any machine without that sibling checked out
- Puts the VLM captioning branch on NPU (`gvagenai` has no NPU plugin) or samples it at
  full frame rate instead of throttling with `videorate drop-only=true framerate=1/5`

## How to Re-run Evals

```bash
# Install evaluation dependencies
pip install pytest requests paho-mqtt

# Run against a live stack
DLSPS_REST_URL=https://localhost HOST_IP=<host-ip> pytest -q tests/

# Full multi-CLI eval (uses evals/evals.json)
python3 run_multi_cli_eval.py \
  --evals-json .github/skills/uav-vision-analytics/evals/evals.json \
  --skill-path .github/skills/uav-vision-analytics \
  --workspace /tmp/uav-eval-workspace \
  --clis copilot --configs with_skill,without_skill
```

## Baseline Results (estimated)

| Eval | Case | With skill | Baseline |
|------|------|-----------|---------|
| 1 | pymavlink all-device stack | 5/5 (100%) | 1/5 (20%) |
| 2 | UAVSDK three-camera | 4/5 (80%) | 1/5 (20%) |
| 3 | RealSense + GPU | 4/5 (80%) | 1/5 (20%) |
| 4 | Cloud-only (should NOT trigger) | 3/3 (100%) | 3/3 (100%) |
| 5 | Captioning (two of three cameras) | 5/6 (83%) | 1/6 (17%) |

| Metric | With skill | Baseline |
|--------|-----------|---------|
| Expectation pass rate (mean) | **90%** | 19% |
| Trigger accuracy | **5/5** | — |
