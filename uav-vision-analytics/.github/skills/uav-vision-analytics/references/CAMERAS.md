<!-- SPDX-FileCopyrightText: (C) 2026 Intel Corporation -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Camera Configuration Reference — UAV Vision Analytics

Cameras are declared, not coded. `configs/cameras-pymavlink.yaml` (or
`configs/cameras-uavsdk.yaml` in SDK mode) lists every camera the pipeline
manager should stream when the vehicle is armed. Adding, removing or
reconfiguring a camera is a YAML edit — the pipeline definitions in
`config-{pymavlink,uavsdk}.json` are a **fixed matrix** generated once; never
add a new pipeline to add a camera.

## File Format

```yaml
version: 1

cameras:
  - id: front_camera                 # a-z, 0-9, _ ; also names the RTSP stream (uav-front-camera,
                                      # underscores -> dashes) and the caption MQTT topic
    enabled: true                    # false skips the camera without deleting its settings
    video: uav_sample_front.avi      # file in resources/videos (.avi/.mp4/.mkv/.ts), OR:
    # device: /dev/v4l/by-id/<name>  #   a live camera (RealSense/USB) -- also accepts:
    #   width: 1280                  #   optional, default 1280 (live camera only)
    #   height: 720                  #   optional, default 720  (live camera only)
    #   fps: 30                      #   optional, default 30   (live camera only)
    # rtsp: rtsp://host.docker.internal:8554/{uav_id}/nadir   #   an RTSP stream (uavsdk mode only)
    overlay: true                    # false hides detection boxes AND telemetry text
    detection:
      device: npu                    # cpu | gpu | npu
      model: yolo11s/yolo11s_openvino_model/yolo11s.xml   # path below resources/models
    captioning:
      enabled: true                  # false = detection only
      device: gpu                    # cpu | gpu (never npu — gvagenai has no NPU plugin)
      model: InternVL2-1B            # folder name below resources/ov_models/<device>/
      prompt: Describe what you see in the scene.         # letters, digits, spaces, , . ? ' - only
      max_new_tokens: 50
    # rtsp_path: custom-path         # optional override of the default uav-<id>
    # mqtt_topic: uav/caption/custom # optional override of the default uav/caption/<id>
```

Only `id` is required; every other field falls back to the defaults shown
above (captioning is off unless `enabled: true`).

| Field | Meaning |
| --- | --- |
| `id` | `^[a-z][a-z0-9_]{0,31}$`. Also derives the RTSP stream name (`uav-<id>`, `_`→`-`) and the caption MQTT topic (`uav/caption/<id>`). |
| `enabled` | `false` leaves the camera out entirely (no pipeline started for it). |
| `video` / `device` / `rtsp` | Exactly one source. `video`: file in `resources/videos`, no folders, `.avi`/`.mp4`/`.mkv`/`.ts`. `device`: `/dev/videoN` or `/dev/v4l/by-(id|path)/...` for a live RealSense/USB camera (pymavlink mode; must also be exposed via `CAMERA_DEVICE_1`..`_4` in `.env`). `rtsp`: an `rtsp://` URL, used in uavsdk mode for the SDK's per-camera streams; `{uav_id}` is substituted from `UAV_ID`. |
| `overlay` | `false` removes both the detection boxes and the telemetry-text overlay from the stream. |
| `detection.device` / `.model` | Where and with which model objects are detected. `model` is relative to `resources/models`; must match `^[A-Za-z0-9_./-]+\.xml$` with no `..` segments. Cameras sharing device+model share one loaded model instance. |
| `captioning.enabled` | `true` adds a VLM captioning branch; captions publish to MQTT `uav/caption/<id>`. |
| `captioning.device` / `.model` / `.prompt` / `.max_new_tokens` | Where (`cpu`/`gpu` only), with which model (folder under `resources/ov_models/<device>/`), with which prompt, and how many tokens per caption. |

## Which Pipeline a Camera Selects

`scripts/camera_config.py` derives the pipeline name purely from each
camera's **source kind** and **devices** — never from a value in the file
itself:

| Source | Captioning | Pipeline name | Config file |
| --- | --- | --- | --- |
| `video:` file or `rtsp:` stream | off | `uav_object_detection_<det>` | both |
| `video:` file or `rtsp:` stream | on | `uav_object_detection_<det>_<vlm>` | both |
| `device:` live camera | off | `uav_camera_<det>` | pymavlink only (`npu` shipped in `config-pymavlink.json`; CPU/GPU in `config-pymavlink-realsense.json` for reference) |
| `device:` live camera | on | `uav_camera_<det>_<vlm>` | same |

`<det>` ∈ `{cpu, gpu, npu}`, `<vlm>` ∈ `{cpu, gpu}` — 3 detection devices ×
(1 no-caption + 2 caption devices) = **9 `uav_object_detection_*` pipelines**, shipped in both
`config-pymavlink.json` and `config-uavsdk.json` (in `config-uavsdk.json` the source is `rtspsrc`
with an `rtsp_url` parameter instead of `video`). `config-pymavlink.json` also ships the 2 live-camera
pipelines `uav_camera_npu` / `uav_camera_npu_gpu` (**11 total**); `config-pymavlink-realsense.json`
carries all 9 `uav_camera_*` combinations to copy from.

A camera whose derived pipeline name is not present in the mounted
`config.json` is reported by `make check-cameras` as *unavailable* and
skipped at the next arming — it is never silently ignored.

## `camera_config.py` — CLI and Reuse

```bash
# Inside the dlstreamer-pipeline-server container (or any venv with the same deps):
python3 camera_config.py check  [FILE]   # validate + print the table (default: $CAMERAS_CONFIG)
python3 camera_config.py plan   [FILE]   # same, plus the exact REST start-request JSON per camera
python3 camera_config.py schema          # JSON Schema of the file (for a UI form / editor validation)
```

Equivalent `make` targets: `make check-cameras` (`CAMERAS=<file>` to point at
another file) and `make cameras-status` (file vs. what is actually running).

Key env vars consumed by the module (set by the compose files, rarely
overridden):

| Var | Default | Purpose |
| --- | --- | --- |
| `CAMERAS_CONFIG` | `/home/pipeline-server/configs/cameras-pymavlink.yaml` | Which file `mavlink_pipeline_manager.py` reads; `docker-compose-uavsdk.yml` sets it to `cameras-uavsdk.yaml` |
| `PIPELINES_CONFIG` | `/home/pipeline-server/config.json` | Used to check a camera's derived pipeline name actually exists |
| `PIPELINE_RESOURCES_DIR` | `/home/pipeline-server/resources` | Base for validating `detection.model` / `captioning.model` paths |

The module has no dependency on MAVLink or the pipeline manager itself, so a
REST endpoint, a web UI, or this skill's generation logic can reuse
`CamerasConfig` (pydantic model with `extra="forbid"` — a misspelled key is a
hard error, never silently ignored), `json_schema()`, and `build_plan()`
(returns, per enabled camera, the pipeline name, RTSP path, and exact REST
start-request body).

## Reload Semantics (important for generated docs/instructions)

- The file is re-read **every time the vehicle arms**, not continuously.
- An edit made while **disarmed** applies at the next arm.
- An edit made while **armed** is logged
  (`[config] changed while armed: it applies the next time the vehicle is armed`)
  but does not affect already-running cameras.
- An edit that fails validation is **refused**; the previous good
  configuration keeps running (`[config] ... has errors, keeping the previous
  configuration:` followed by every problem, one per line) — a typo never
  leaves the vehicle without video.
- Without arming the vehicle: `docker exec -it -e HOST_IP="$HOST_IP" uav-va-dlstreamer-pipeline-server
  python3 /home/pipeline-server/scripts/pipeline_manager.py --start-now`
  starts the cameras immediately. Ctrl+C or SIGTERM (`docker stop`) stops the cameras it
  started. In UAVSDK mode the SDK's RTSP streams exist only while armed and flying.

## Live Cameras (RealSense, USB webcams)

1. `v4l2-ctl --list-devices` to find the node; prefer the stable
   `/dev/v4l/by-id/...` path over `/dev/videoN` (numbers change with plug
   order). A RealSense exposes several nodes (depth, IR, colour) — pick the
   colour one.
2. Put the same path in `.env` as `CAMERA_DEVICE_1` (through `_4`).
3. Recreate the container (`make pymav-up`) so the device is passed through.
4. Set the camera's `device:` field in `cameras-pymavlink.yaml` to the same
   path and `enabled: true`.
5. `config-pymavlink.json` ships only `uav_camera_npu` / `uav_camera_npu_gpu`
   by default — for `cpu`/`gpu` detection on a live camera, copy the needed
   pipeline(s) from `configs/config-pymavlink-realsense.json` into
   `config-pymavlink.json` and recreate the container.

## RTSP Streams (UAV Mission Compute SDK mode)

`rtsp: rtsp://host.docker.internal:8554/{uav_id}/<camera>` — `{uav_id}` is
substituted from `UAV_ID` in `.env` (default `uav-1`). Before starting such a
camera's pipeline, the manager probes the URL with `ffprobe` (3 attempts, 2 s
apart) and skips it (retrying on the next arming/sync cycle) if the SDK
hasn't published that stream yet, rather than failing the whole batch.
