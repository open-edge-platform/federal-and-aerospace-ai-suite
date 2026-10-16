# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""
Monitors UAV ARMED/DISARMED status via MAVLink and starts/stops DL Streamer
pipelines accordingly:
  - ARMED    -> POST to start each configured pipeline
  - DISARMED -> DELETE each pipeline using its stored instance_id

Usage:
  python3 pipeline_manager.py
"""

import argparse
import json
import os
import time

import requests
from pymavlink import mavutil

# ── Constants ─────────────────────────────────────────────────────────────────

CONNECTION_STRING   = "udpin:0.0.0.0:14541"
PIPELINE_BASE_URL   = "http://localhost:8081/pipelines/user_defined_pipelines"
PIPELINE_DELETE_URL = "http://localhost:8081/pipelines/{instance_id}"
PIPELINE_STATUS_URL = "http://localhost:8081/pipelines/{instance_id}/status"
# Loading models (GPU/NPU compile, VLM) can take a while after a (re)start, so the
# start request and the wait for RUNNING get generous timeouts.
START_REQUEST_TIMEOUT = 60
START_READY_TIMEOUT   = 180
MODEL_PATH          = (
    "/home/pipeline-server/resources/models/"
    "yolo11s/yolo11s_openvino_model/yolo11s.xml"
)
# Passed via make start-rtsp DEVICE=cpu|gpu|npu|all; default is gpu.
PIPELINE_DEVICE = os.getenv("PIPELINE_DEVICE", "gpu").lower()
# Passed via make start-rtsp CAPTION=true|false; default is false. When true,
# the RTSP sink uses the *_caption pipeline variants (detection+telemetry RTSP
# branch, unchanged, plus an independent VLM captioning branch over MQTT).
CAPTION_ENABLED = os.getenv("CAPTION", "false").strip().lower() in ("1", "true", "yes")

# Passed via make start-rtsp BBOX_THICKNESS=<1-10>; default 6 (gvawatermark's
# own default). Applied as overlay-properties on the RTSP destination
# -- the pipeline server auto-inserts 'gvawatermark displ-cfg=thickness=N'
# ahead of the encoder for each destination, so this needs no pipeline.json
# or dlstreamer-pipeline-server image change, just a REST request field.
BBOX_THICKNESS = os.getenv("BBOX_THICKNESS", "6").strip()
BBOX_OVERLAY_PROPERTIES = {"thickness": BBOX_THICKNESS}

# ── Pipeline definitions ──────────────────────────────────────────────────────

RTSP_PIPELINES = [
    {"name": "uav_object_detection_cpu", "frame_path": "uav-mavlink-cpu", "device": "CPU"},
    {"name": "uav_object_detection_gpu", "frame_path": "uav-mavlink-gpu", "device": "GPU"},
    {"name": "uav_object_detection_npu", "frame_path": "uav-mavlink-npu", "device": "NPU"},
]

# Caption variants: same RTSP/telemetry output as RTSP_PIPELINES — including
# the exact same frame_path per device, so the RTSP URL a viewer connects to
# never changes whether CAPTION is on or off — plus a second branch that runs
# VLM scene captioning and publishes results over MQTT (topic:
# uav/caption/<device>). Requires 'make vlm-model' first.
RTSP_CAPTION_PIPELINES = [
    {"name": "uav_object_detection_cpu_caption", "frame_path": "uav-mavlink-cpu", "device": "CPU"},
    {"name": "uav_object_detection_gpu_caption", "frame_path": "uav-mavlink-gpu", "device": "GPU"},
    {"name": "uav_object_detection_npu_caption", "frame_path": "uav-mavlink-npu", "device": "NPU"},
]

# ── Payload builders ──────────────────────────────────────────────────────────

def _build_rtsp_payload(pipeline: dict) -> dict:
    return {
        "destination": {
            "metadata": {
                "type": "file",
                # Per-device log file so CPU/GPU/NPU detections never
                # interleave into a single results.jsonl.
                "path": f"/tmp/results_{pipeline['device'].lower()}.jsonl",
                "format": "json-lines",
            },
            "frame": {
                "type": "rtsp",
                "path": pipeline["frame_path"],
                "encoding": "h264",
                "overlay-properties": BBOX_OVERLAY_PROPERTIES,
            },
        },
        "parameters": {
            "detection-properties": {
                "model": MODEL_PATH,
                "device": pipeline["device"],
            }
        },
    }


def _build_rtsp_caption_payload(pipeline: dict) -> dict:
    # NOTE: unlike _build_rtsp_payload(), this intentionally omits
    # 'detection-properties' (gvadetect model/device are hardcoded inline in
    # the *_caption pipeline strings) and 'destination.metadata' (would
    # auto-attach a duplicate MQTT/file publisher onto every gvametaconvert
    # element in the pipeline, including the caption branch's own explicit
    # mqtt_publisher — both are known to deadlock the pipeline; see
    # configs/config-pymavlink.json comments and docs/ for details).
    #
    # Detection-box overlay is NOT drawn in-pipeline (only a gvapython
    # telemetry-text overlay runs before gvametaconvert/gvametapublish) --
    # it's rendered by the pipeline server's own RTSP AppDestination
    # (gvawatermark auto-inserted ahead of the encoder), so 'overlay' must
    # be left at its default (on). 'overlay-properties' sets the thickness.
    return {
        "destination": {
            "frame": {
                "type": "rtsp",
                "path": pipeline["frame_path"],
                "encoding": "h264",
                "overlay-properties": BBOX_OVERLAY_PROPERTIES,
            },
        },
    }


# ── Pipeline lifecycle ────────────────────────────────────────────────────────

def _filter_by_device(pipelines: list[dict], device: str) -> list[dict]:
    """Return pipelines matching device; 'all' returns the full list."""
    if device == "all":
        return pipelines
    filtered = [p for p in pipelines if p["device"].lower() == device]
    if not filtered:
        print(f"[config] Warning: no pipeline for device='{device}' — defaulting to GPU.")
        return [p for p in pipelines if p["device"] == "GPU"]
    return filtered


running_instance_ids: list[str] = []


def _wait_until_running(name: str, instance_id: str) -> bool:
    """Block until the instance reports RUNNING; False on ERROR/ABORTED or timeout."""
    url = PIPELINE_STATUS_URL.format(instance_id=instance_id)
    deadline = time.time() + START_READY_TIMEOUT
    state = None
    while time.time() < deadline:
        try:
            state = requests.get(url, timeout=5).json().get("state")
        except (requests.RequestException, ValueError):
            state = None
        if state == "RUNNING":
            print(f"[pipeline] '{name}' is RUNNING")
            return True
        if state in ("ERROR", "ABORTED"):
            print(f"[pipeline] '{name}' failed to start (state {state})")
            return False
        time.sleep(1)
    print(f"[pipeline] '{name}' not RUNNING after {START_READY_TIMEOUT}s (last state {state})")
    return False


def start_pipelines(pipelines: list[dict], build_payload) -> None:
    """POST all configured pipelines and record their instance_ids."""
    global running_instance_ids
    running_instance_ids = []

    npu_device = os.getenv("NPU_DEVICE", "/dev/null")
    for pipeline in pipelines:
        if pipeline["device"] == "NPU" and npu_device == "/dev/null":
            print(f"[pipeline] Skipping '{pipeline['name']}': NPU_DEVICE not available.")
            continue

        url     = f"{PIPELINE_BASE_URL}/{pipeline['name']}"
        payload = build_payload(pipeline)
        try:
            resp = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=START_REQUEST_TIMEOUT,
            )
            print(f"[pipeline] Start '{pipeline['name']}' → {resp.status_code}: {resp.text}")
            if resp.status_code == 200:
                try:
                    instance_id = json.loads(resp.text)
                except (json.JSONDecodeError, ValueError):
                    instance_id = resp.text.strip().strip('"')
                if instance_id:
                    running_instance_ids.append(instance_id)
                    # One pipeline at a time: starting several caption pipelines at once
                    # made their GPU model loads collide and crashed the pipeline server.
                    _wait_until_running(pipeline["name"], instance_id)
        except requests.RequestException as exc:
            print(f"[pipeline] Failed to start '{pipeline['name']}': {exc}")


def _print_stream_urls(pipelines: list[dict]) -> None:
    host_ip = os.getenv("HOST_IP", "127.0.0.1")
    npu_device = os.getenv("NPU_DEVICE", "/dev/null")
    active = [p for p in pipelines if p["device"] != "NPU" or npu_device != "/dev/null"]
    urls = "\n".join(f"  rtsp://{host_ip}:8555/{p['frame_path']}" for p in active)
    print(f"RTSP streams available at:\n{urls}")


def stop_pipelines() -> None:
    """DELETE all currently tracked pipeline instances."""
    global running_instance_ids
    if not running_instance_ids:
        print("[pipeline] No running instances; nothing to stop.")
        return

    for instance_id in running_instance_ids:
        url = PIPELINE_DELETE_URL.format(instance_id=instance_id)
        try:
            resp = requests.delete(url, timeout=10)
            print(f"[pipeline] Stop '{instance_id}' → {resp.status_code}: {resp.text}")
        except requests.RequestException as exc:
            print(f"[pipeline] Failed to stop '{instance_id}': {exc}")

    running_instance_ids = []

# ── Main monitor loop ─────────────────────────────────────────────────────────

def _is_vehicle_heartbeat(msg) -> bool:
    """True for a heartbeat sent by the vehicle's autopilot.

    Ground-control stations (QGroundControl: system 255, MAV_TYPE_GCS) also send
    heartbeats, and QGroundControl sets the "armed" bit in base_mode. Reacting to
    those would flip the armed state every heartbeat and start/stop the
    pipelines in a loop once a remote QGroundControl connects.
    """
    return (msg.type != mavutil.mavlink.MAV_TYPE_GCS
            and msg.autopilot != mavutil.mavlink.MAV_AUTOPILOT_INVALID)


def monitor_and_control() -> None:
    if CAPTION_ENABLED:
        pipelines     = RTSP_CAPTION_PIPELINES
        build_payload = _build_rtsp_caption_payload
    else:
        pipelines     = RTSP_PIPELINES
        build_payload = _build_rtsp_payload
    pipelines = _filter_by_device(pipelines, PIPELINE_DEVICE)

    print(f"[config] Device    : {PIPELINE_DEVICE.upper()}")
    print(f"[config] Captioning: {'ENABLED' if CAPTION_ENABLED else 'disabled'}")
    print(f"[config] Pipelines : {[p['name'] for p in pipelines]}")
    print(f"Connecting to {CONNECTION_STRING}...")

    master = mavutil.mavlink_connection(CONNECTION_STRING)
    print("Waiting for vehicle heartbeat...")
    msg = None
    while msg is None or not _is_vehicle_heartbeat(msg):
        msg = master.recv_match(type="HEARTBEAT", blocking=True)
    vehicle_sysid = msg.get_srcSystem()
    print(f"Heartbeat received from System {vehicle_sysid} "
          f"Component {msg.get_srcComponent()}")

    last_armed_state = None
    print("Monitoring ARMED/DISARMED status. Press Ctrl+C to stop.\n")

    try:
        while True:
            msg = master.recv_match(type="HEARTBEAT", blocking=True)
            if not msg:
                time.sleep(0.01)
                continue
            if msg.get_srcSystem() != vehicle_sysid or not _is_vehicle_heartbeat(msg):
                continue

            is_armed = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)

            if is_armed != last_armed_state:
                if is_armed:
                    print("Vehicle Status: ARMED → starting pipelines")
                    start_pipelines(pipelines, build_payload)
                    _print_stream_urls(pipelines)
                else:
                    print("Vehicle Status: DISARMED → stopping pipelines")
                    stop_pipelines()
                last_armed_state = is_armed

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nInterrupted — stopping active pipelines before exit.")
        if running_instance_ids:
            stop_pipelines()

# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    argparse.ArgumentParser(
        description="MAVLink-triggered DL Streamer pipeline manager (RTSP output)"
    ).parse_args()
    monitor_and_control()


if __name__ == "__main__":
    main()
