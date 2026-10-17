#!/usr/bin/env bash
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Manually start/stop/check ONE pipeline per detection device on the DL Streamer
# Pipeline Server fronted by nginx in the pymavlink stack (docker-compose-pymavlink.yml),
# without needing to arm the drone via MAVLink and without cameras.yaml: ad-hoc testing
# of 'make pymav-up' stacks with the pipelines' default video, models and prompt.
# The cameras of configs/cameras.yaml, started when the vehicle is armed by
# scripts/mavlink_pipeline_manager.py ('make start-rtsp'), remain the normal way to run
# this app end to end ('make start-rtsp' also has --start-now to run them without a vehicle).
#
# Each started pipeline's instance_id is cached in a per-device/variant state
# file (.uav_pipeline_<device>[_caption]_instance_id) so 'stop'/'status' can
# find it without the caller tracking it manually. Streams are published as
# rtsp://<HOST_IP>:8555/uav-manual-<device>.
#
# Usage:
#   ./scripts/uav_pipeline_control.sh start  [cpu|gpu|npu|all] [--caption]
#   ./scripts/uav_pipeline_control.sh stop   [cpu|gpu|npu|all] [--caption]
#   ./scripts/uav_pipeline_control.sh status [cpu|gpu|npu|all] [--caption]
#
# --caption starts the uav_object_detection_<device>_gpu pipeline (detection on <device> plus
# VLM scene captioning on the GPU, published over MQTT on 'uav/caption/manual_<device>').
# Requires 'make vlm-model' to have been run first (see README.md).
#
# The RTSP destination is always H.264 encoded (the "encoding": "h264" field,
# see dlstreamer-pipeline-server's gstreamer_rtsp_destination.py).
# uav-ground-station's H.264 relay needs it.
#
# BBOX_THICKNESS (in .env, default "6") sets the detection bounding-box line
# thickness (1-10, gvawatermark's own default is 2) via the RTSP
# destination's "overlay-properties": {"thickness": N} field -- no
# pipeline.json or dlstreamer-pipeline-server image change needed.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"

if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  set -a; source "${ENV_FILE}"; set +a
fi

HOST_IP="${HOST_IP:-127.0.0.1}"
NPU_DEVICE="${NPU_DEVICE:-/dev/null}"
BBOX_THICKNESS="${BBOX_THICKNESS:-6}"
ALL_DEVICES=(cpu gpu npu)

log()  { echo "[INFO ] $*"; }
err()  { echo "[ERROR] $*" >&2; }

api() {
  curl -sk --noproxy '*' "$@"
}

state_file() {
  local device="$1" caption="$2"
  if [[ "${caption}" == "true" ]]; then
    echo "${REPO_ROOT}/.uav_pipeline_${device}_caption_instance_id"
  else
    echo "${REPO_ROOT}/.uav_pipeline_${device}_instance_id"
  fi
}

pipeline_name() {
  local device="$1" caption="$2"
  if [[ "${caption}" == "true" ]]; then
    echo "uav_object_detection_${device}_gpu"
  else
    echo "uav_object_detection_${device}"
  fi
}

frame_path() {
  # Same RTSP path regardless of --caption, so the URL a viewer connects to
  # never changes whether captioning is on or off.
  local device="$1"
  echo "uav-manual-${device}"
}

rtsp_frame_json() {
  # Builds the "frame" destination's RTSP object, selecting H.264 encoding and
  # setting the detection bounding-box line thickness via overlay-properties
  # from BBOX_THICKNESS in .env (pipeline server auto-inserts
  # 'gvawatermark displ-cfg=thickness=N' ahead of this destination's
  # encoder).
  local path="$1"
  echo "{\"type\": \"rtsp\", \"path\": \"${path}\", \"encoding\": \"h264\", \"overlay-properties\": {\"thickness\": ${BBOX_THICKNESS}}}"
}

start_one() {
  local device="$1" caption="$2"
  local name path sfile payload response instance_id rtsp_frame

  if [[ "${device}" == "npu" && "${NPU_DEVICE}" == "/dev/null" ]]; then
    err "Skipping NPU: NPU_DEVICE is not set in .env (no NPU device available)."
    return 0
  fi

  name="$(pipeline_name "${device}" "${caption}")"
  path="$(frame_path "${device}")"
  sfile="$(state_file "${device}" "${caption}")"

  if [[ -f "${sfile}" ]]; then
    err "Pipeline '${name}' already tracked (instance $(cat "${sfile}")). Run 'stop' first."
    return 1
  fi

  # Base and caption variants for the same device share the same RTSP path
  # (so the URL a viewer connects to never changes) — only one of the two
  # can publish to it at a time, so refuse to start one while the other is
  # already tracked for this device.
  local other_caption other_sfile other_name
  if [[ "${caption}" == "true" ]]; then other_caption="false"; else other_caption="true"; fi
  other_sfile="$(state_file "${device}" "${other_caption}")"
  if [[ -f "${other_sfile}" ]]; then
    other_name="$(pipeline_name "${device}" "${other_caption}")"
    err "'${other_name}' is already running and publishes to the same RTSP path" \
        "(${path}) as '${name}'. Run 'stop ${device}$([ "${other_caption}" = "true" ] && echo " --caption")' first."
    return 1
  fi

  log "Starting ${name} on https://${HOST_IP} (RTSP path: ${path})"

  # Video, models, prompt and instance ids come from the pipeline's own defaults. Only the
  # overlay label and, when captioning, the MQTT topic are set so manual runs are recognisable.
  # No metadata destination: the pipelines publish no per-frame JSON.
  rtsp_frame="$(rtsp_frame_json "${path}")"
  if [[ "${caption}" == "true" ]]; then
    payload="{\"destination\": {\"frame\": ${rtsp_frame}}, \"parameters\": {\"overlay_label\": \"manual-${device}-${device}-gpu\", \"mqtt_topic\": \"uav/caption/manual_${device}\"}}"
  else
    payload="{\"destination\": {\"frame\": ${rtsp_frame}}, \"parameters\": {\"overlay_label\": \"manual-${device}\"}}"
  fi

  response="$(api -X POST "https://${HOST_IP}/pipelines/user_defined_pipelines/${name}" \
    -H 'Content-Type: application/json' \
    -d "${payload}")"

  instance_id="$(echo "${response}" | tr -d '"')"
  if [[ -z "${instance_id}" || "${instance_id}" == *error* || "${instance_id}" == *detail* ]]; then
    err "Failed to start '${name}': ${response}"
    return 1
  fi

  echo "${instance_id}" > "${sfile}"
  log "Started '${name}'. Instance ID: ${instance_id}"
  log "RTSP output: rtsp://${HOST_IP}:8555/${path} (H.264)"
  if [[ "${caption}" == "true" ]]; then
    log "MQTT captions: topic 'uav/caption/manual_${device}' on broker:1883"
  fi
}

stop_one() {
  local device="$1" caption="$2"
  local name sfile instance_id

  name="$(pipeline_name "${device}" "${caption}")"
  sfile="$(state_file "${device}" "${caption}")"

  if [[ ! -f "${sfile}" ]]; then
    log "No tracked instance for '${name}' (${sfile} missing) — skipping."
    return 0
  fi

  instance_id="$(cat "${sfile}")"
  log "Stopping '${name}' (instance ${instance_id})"
  api -X DELETE "https://${HOST_IP}/pipelines/${instance_id}" > /dev/null
  rm -f "${sfile}"
  log "Stopped."
}

status_one() {
  local device="$1" caption="$2"
  local name sfile instance_id

  name="$(pipeline_name "${device}" "${caption}")"
  sfile="$(state_file "${device}" "${caption}")"

  if [[ ! -f "${sfile}" ]]; then
    log "'${name}': no tracked instance."
    return 0
  fi

  instance_id="$(cat "${sfile}")"
  log "'${name}' (instance ${instance_id}):"
  api "https://${HOST_IP}/pipelines/${instance_id}/status" | python3 -m json.tool 2>/dev/null \
    || echo "  (status unavailable — instance may no longer exist)"
}

resolve_devices() {
  local device="$1"
  case "${device}" in
    all) echo "${ALL_DEVICES[@]}" ;;
    cpu|gpu|npu) echo "${device}" ;;
    *)
      err "device must be one of: cpu, gpu, npu, all (got '${device}')"
      exit 1
      ;;
  esac
}

ACTION="${1:-}"
DEVICE_ARG="${2:-gpu}"
CAPTION="false"
for arg in "${@:3}"; do
  [[ "${arg}" == "--caption" ]] && CAPTION="true"
done
# Allow --caption as the 2nd positional too, e.g. 'start all --caption'.
case "${DEVICE_ARG}" in
  --caption) CAPTION="true"; DEVICE_ARG="all" ;;
esac

case "${ACTION}" in
  start|stop|status)
    for device in $(resolve_devices "${DEVICE_ARG}"); do
      "${ACTION}_one" "${device}" "${CAPTION}"
    done
    ;;
  *)
    echo "Usage: $0 {start|stop|status} [cpu|gpu|npu|all] [--caption]" >&2
    exit 1
    ;;
esac
