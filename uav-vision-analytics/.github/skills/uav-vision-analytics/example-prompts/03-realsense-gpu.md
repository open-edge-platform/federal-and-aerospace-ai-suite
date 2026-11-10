<!-- SPDX-FileCopyrightText: (C) 2026 Intel Corporation -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Example: Intel RealSense Camera — GPU Inference, RTSP Output

Build an end-to-end UAV vision analytics stack in `./uav-realsense-stack/`
using the uav-vision-analytics skill.

**Scenario:** A UAV companion computer is connected to an Intel RealSense depth
camera (RGB stream via v4l2). Detect aerial objects on GPU from the live
RealSense video feed. Overlay live MAVLink telemetry. Serve the annotated
stream as RTSP for consumption by QGroundControl or ffplay. PX4 SITL provides
the simulated flight controller.

**Requirements:**
- Deployment mode: `pymavlink`
- Video source: `device` (RealSense colour node, `/dev/v4l/by-id/...`, also set as `CAMERA_DEVICE_1` in `.env`)
- Detection device: `gpu`, captioning `off`
- Model: `yolo11s`
- Output directory: `./uav-realsense-stack/`

Produce:
- `docker-compose-pymavlink.yml` with all required services
- `configs/cameras-pymavlink.yaml` with one `device:` camera on `gpu` (selects `uav_camera_gpu`)
- `configs/config-pymavlink.json` with the `uav_camera_gpu` pipeline copied from
  `config-pymavlink-realsense.json` (the default file only ships `uav_camera_npu[_gpu]`)
- `gvapython/telemetry-overlay-pymavlink.py` overlay
- `scripts/mavlink_pipeline_manager.py` and `scripts/camera_config.py`
- `mavlink-router/main.conf`
- `Makefile` with model, up/down, check-cameras, start-rtsp targets
- `.env` template
- `tests/` pytest suite

> [!NOTE]
> RealSense device must be physically connected and accessible as
> `/dev/video0` on the host. The compose file must mount the device and
> include the appropriate `group_add` GID for the video group.

Verify against all completion criteria before declaring success.
