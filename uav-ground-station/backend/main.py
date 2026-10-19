# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Remote viewer backend for the UAV Vision Analytics stack.

Runs on a machine *separate* from the UAV stack. Given the IP/hostname of a
host already running the uav-vision-analytics stack (docker-compose-pymavlink
or docker-compose-uavsdk, with nginx publishing its usual ports), this
service:

  * Looks up which DL Streamer pipeline/model is currently serving a given
    camera's RTSP stream, via the Pipeline Server's REST API (through nginx). A camera is a
    running pipeline with an RTSP frame destination, identified by its stream path (uav-<name>).
  * Proxies the metrics-manager SSE stream so the browser never needs direct,
    cross-origin, self-signed-TLS access to the remote host.
  * Also streams this ground-station machine's *own* CPU/RAM utilization
    (via /api/local-metrics-stream, read from /proc) so the dashboard can
    show how much local compute "H.264 Relay" mode's mediamtx remux costs
    on this box -- see the "UAV Ground Station Utilization" panel.
  * Bridges MQTT scene captions (topic uav/caption/<camera>, taken from pipeline-info) to the browser
    over SSE.
  * "H.264 Relay" video -- the only video path: whenever a remote pipeline
    is publishing RTSP for a camera (see pipeline_info's "rtsp_available";
    uav-vision-analytics publishes H.264), the local viz-backend configures a mediamtx sidecar
    (docker-compose-mediamtx.yml, always brought up alongside this
    service -- see `make up`) to pull that already-H.264 RTSP stream on
    demand and re-serve it as WebRTC -- pure remux, no transcoding: see
    /api/relay-path, and the dashboard iframes that local mediamtx's own
    WHEP viewer page, so this stack's own compute/network footprint for
    video is visible.
  * When no remote pipeline is publishing for a camera, the dashboard
    shows a "No video stream" placeholder instead of video.
  * Natural-language video search via a separately deployed Video Search
    and Summarization (VSS) stack -- see vss_search.py.

Only ever makes outbound, read-only requests to the user-supplied host; it
never starts/stops pipelines on the remote stack.
"""

import asyncio
import json
import logging
import os
import re
from typing import Optional

import httpx
import paho.mqtt.client as mqtt
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

import caption_log
import vss_live_sync
from vss_search import router as vss_search_router
from vss_summary import router as vss_summary_router

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger("viz-backend")

DEFAULT_REMOTE_HOST = os.environ.get("DEFAULT_REMOTE_HOST", "127.0.0.1")
REMOTE_HTTPS_PORT = int(os.environ.get("REMOTE_HTTPS_PORT", "443"))
REMOTE_MQTT_PORT = int(os.environ.get("REMOTE_MQTT_PORT", "1883"))
REMOTE_RTSP_PORT = int(os.environ.get("REMOTE_RTSP_PORT", "8555"))

# Local mediamtx sidecar used only for "H.264 Relay" mode (see module
# docstring) -- MEDIAMTX_API_BASE is the internal docker-network address this
# backend uses to (re)configure the relay path; the other two are what the
# *browser* needs to reach mediamtx's own WHEP viewer page directly (so they
# default to loopback but should be set to the ground-station box's LAN IP
# in .env if the browser runs on a different machine). None of these matter
# unless docker-compose-mediamtx.yml is also brought up.
MEDIAMTX_API_BASE = os.environ.get("MEDIAMTX_API_BASE", "http://mediamtx:9997")
MEDIAMTX_WEBRTC_HOST = os.environ.get("MEDIAMTX_WEBRTC_HOST", "127.0.0.1")
MEDIAMTX_WEBRTC_PORT = int(os.environ.get("MEDIAMTX_WEBRTC_PORT", "8889"))

# This ground station's own metrics-manager (intel/metrics-manager, same
# image/metric set as the remote host's), container name "gs-metrics-manager"
# -- deliberately distinct from the remote stack's own "metrics-manager"
# container so the two can coexist if someone ever runs both stacks on the
# same machine (same reasoning for the "gs-" prefix wherever it shows up
# below). Internal-only, no host port published; this backend proxies its
# SSE stream over the docker network, same pattern as /api/metrics-stream.
LOCAL_METRICS_MANAGER_BASE = os.environ.get("LOCAL_METRICS_MANAGER_BASE", "http://gs-metrics-manager:9090")


# A camera is identified by its RTSP stream path (for example "uav-front-camera"); the MQTT caption
# topic of a camera is "uav/caption/<name>". Both end up in URLs / subscriptions, so they are validated.
CAMERA_PATTERN = r"^[A-Za-z0-9_-]{1,48}$"
TOPIC_PATTERN = r"^uav/caption/[A-Za-z0-9_-]{1,48}$"
# uav_object_detection_<det>[_<vlm>] (video file) or uav_camera_<det>[_<vlm>] (live camera); the older uav_object_detection_<device>_caption
# naming is still recognised so a UAV host that has not been updated keeps working.
_PIPELINE_NAME = re.compile(r"^uav_(?:object_detection|camera)_(cpu|gpu|npu)(?:_(cpu|gpu)|(_caption))?$")
# Display order of the camera cards: a camera whose name contains one of these
# words (e.g. "uav-front-camera" -> "front") is placed by that word's position;
# any other camera follows, alphabetically.
CAMERA_ORDER = [w.strip().lower() for w in os.environ.get("CAMERA_ORDER", "front,bottom,back").split(",") if w.strip()]

app = FastAPI(title="UAV Vision Analytics - Remote Viewer")


def _remote_base(host: str) -> str:
    return f"https://{host}:{REMOTE_HTTPS_PORT}"


def _dest_frame_for_path(destination: dict, frame_path: str) -> Optional[dict]:
    """Return the destination.frame entry matching frame_path.

    destination.frame is a single dict for RTSP-only pipelines, but a *list*
    of dicts (one per transport) for the combined pipeline's WebRTC-enabled
    variant (see uav-vision-analytics's _build_rtsp_caption_payload) -- this
    normalizes both shapes so callers don't need to know which one a given
    running instance used.
    """
    if not isinstance(destination, dict):
        return None
    frame = destination.get("frame")
    if isinstance(frame, dict):
        return frame if frame.get("path") == frame_path else None
    if isinstance(frame, list):
        for entry in frame:
            if isinstance(entry, dict) and entry.get("path") == frame_path:
                return entry
    return None


def _dest_frame_paths(destination: dict) -> list:
    """All destination paths present in destination.frame, regardless of
    whether it's a single dict (RTSP-only) or a list (RTSP+WebRTC combined
    variant) -- see _dest_frame_for_path for the shape rationale."""
    if not isinstance(destination, dict):
        return []
    frame = destination.get("frame")
    if isinstance(frame, dict):
        return [frame.get("path")]
    if isinstance(frame, list):
        return [entry.get("path") for entry in frame if isinstance(entry, dict)]
    return []


def _pipeline_identity(pipeline: dict) -> Optional[str]:
    """The REST API's request.pipeline.name is always the generic grouping
    name ("user_defined_pipelines"), not the actual pipeline that was
    started -- that's request.pipeline.version instead. Prefer version,
    falling back to name for older/unexpected response shapes.
    """
    return pipeline.get("version") or pipeline.get("name")


def _camera_title(path: str) -> str:
    """Stream path -> display name: "uav-front-camera" -> "front camera"."""
    name = path[4:] if path.startswith("uav-") else path
    return name.replace("-", " ").replace("_", " ")


def _camera_record(inst: dict, request: dict, path: str, frame: dict) -> dict:
    """Everything the dashboard shows about one camera, taken from the start request of its pipeline."""
    name = _pipeline_identity(request.get("pipeline") or {})
    params = request.get("parameters") or {}
    match = _PIPELINE_NAME.match(name or "")
    detection_device = match.group(1) if match else None
    vlm_device = match.group(2) if match else None
    captioning = bool(vlm_device) or bool(match and match.group(3)) or (match is None and "caption" in (name or ""))
    topic = None
    if captioning:
        default_name = (path[4:] if path.startswith("uav-") else path).replace("-", "_")
        topic = params.get("mqtt_topic") or f"uav/caption/{default_name}"
    return {
        "camera": path,
        "title": _camera_title(path),
        "pipeline_name": name,
        "state": inst.get("state"),
        "detection_device": detection_device,
        "detection_model": os.path.basename(params["detection_model"]) if params.get("detection_model") else None,
        "captioning": captioning,
        "vlm_device": vlm_device,
        "vlm_model": os.path.basename(params["captioner_model_path"]) if params.get("captioner_model_path") else None,
        "prompt": params.get("captioner_prompt"),
        "max_new_tokens": params.get("captioner_max_new_tokens"),
        "mqtt_topic": topic,
        "overlay": frame.get("overlay", True) is not False,
        "video": params.get("video"),
        # a live camera (RealSense, USB webcam) has a device node instead of a video file
        "device": params.get("device"),
        "rtsp_url": params.get("rtsp_url"),
        "camera_size": f"{params['camera_width']}x{params['camera_height']}" if params.get("device") and params.get("camera_width") else None,
        "label": params.get("overlay_label"),
        "frame_rate": params.get("frame_rate"),
    }


async def _instances_with_requests(client: httpx.AsyncClient, base: str, running_only: bool) -> list:
    """(instance, request) for the remote pipelines, RUNNING first and newest first, so stale or
    aborted runs on the same stream path never hide the live one."""
    resp = await client.get(f"{base}/pipelines/status")
    resp.raise_for_status()
    instances = resp.json()
    if not isinstance(instances, list):
        return []
    instances = sorted(instances, key=lambda inst: (0 if inst.get("state") == "RUNNING" else 1, -(inst.get("start_time") or 0)))
    found = []
    for inst in instances:
        if running_only and inst.get("state") != "RUNNING":
            continue
        inst_id = inst.get("id")
        if inst_id is None:
            continue
        detail_resp = await client.get(f"{base}/pipelines/{inst_id}")
        if detail_resp.status_code != 200:
            continue
        found.append((inst, (detail_resp.json().get("request") or {})))
    return found


def _cameras_from(instances: list) -> list:
    """One record per RTSP stream path, first (best) instance wins."""
    cameras, seen = [], set()
    for inst, request in instances:
        destination = request.get("destination") or {}
        for path in _dest_frame_paths(destination):
            if not isinstance(path, str) or not re.fullmatch(CAMERA_PATTERN, path) or path in seen:
                continue
            seen.add(path)
            frame = _dest_frame_for_path(destination, path) or {}
            cameras.append(_camera_record(inst, request, path, frame))
    return sorted(cameras, key=_camera_sort_key)


def _camera_sort_key(camera: dict) -> tuple:
    words = _camera_title(camera["camera"]).lower().split()
    rank = next((i for i, w in enumerate(CAMERA_ORDER) if w in words), len(CAMERA_ORDER))
    return (rank, camera["camera"])


@app.get("/api/runtime-config")
async def runtime_config():
    return {
        "defaultHost": DEFAULT_REMOTE_HOST,
        "remoteHttpsPort": REMOTE_HTTPS_PORT,
        # Where the browser should reach the local mediamtx sidecar's own
        # WHEP viewer page for "H.264 Relay" mode. Harmless to send even if
        # docker-compose-mediamtx.yml isn't up; the dashboard only uses these
        # once /api/relay-path succeeds.
        "mediamtxWebrtcHost": MEDIAMTX_WEBRTC_HOST,
        "mediamtxWebrtcPort": MEDIAMTX_WEBRTC_PORT,
    }


@app.get("/api/pipeline-info")
async def pipeline_info(host: str = Query(...), camera: str = Query(..., pattern=CAMERA_PATTERN)):
    """Report which pipeline, devices and models currently serve the given camera's RTSP stream."""
    info = {
        "reachable": False,
        "camera": camera,
        "rtsp_path": camera,
        "title": _camera_title(camera),
        "pipeline_name": None,
        "state": None,
        "captioning": False,
        "caption_topic": None,
        # True once a remote pipeline instance publishes an RTSP frame destination for this camera's
        # path -- the dashboard then starts the H.264 relay; otherwise it shows a "No video stream" placeholder.
        "rtsp_available": False,
    }
    try:
        # Self-signed TLS on the remote nginx (see configs/nginx/ssl on that host) -- trusted-LAN tool,
        # same posture as the -k curl examples in the main README.
        async with httpx.AsyncClient(verify=False, timeout=5.0, trust_env=False) as client:
            instances = await _instances_with_requests(client, _remote_base(host), running_only=False)
        info["reachable"] = True
        record = next((c for c in _cameras_from(instances) if c["camera"] == camera), None)
        if record:
            info.update(record)
            info["caption_topic"] = record["mqtt_topic"]
            info["rtsp_available"] = True
            if record.get("captioning") and record.get("mqtt_topic"):
                # Keep the Flight Summary feature's caption history warm for
                # this (host, camera) -- cheap to call on every poll; it's a
                # no-op unless the subscriber doesn't exist yet or the topic
                # changed.
                asyncio.ensure_future(caption_log.note_active(host, camera, record["mqtt_topic"]))
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("pipeline-info lookup failed for host=%s camera=%s: %s", host, camera, exc)
    return info


@app.get("/api/detect-pipelines")
async def detect_pipelines(host: str = Query(...)):
    """Every camera (RUNNING pipeline with an RTSP stream) on the host, so the UI can show one card per
    camera and notice, by re-polling, when a pipeline is started, stopped or replaced."""
    return await _detect_running_cameras(host)


async def _detect_running_cameras(host: str) -> dict:
    """Shared by /api/detect-pipelines and the VSS live-stream sync."""
    result = {"reachable": False, "cameras": []}
    try:
        async with httpx.AsyncClient(verify=False, timeout=5.0, trust_env=False) as client:
            instances = await _instances_with_requests(client, _remote_base(host), running_only=True)
        result["reachable"] = True
        result["cameras"] = _cameras_from(instances)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("detect-pipelines lookup failed for host=%s: %s", host, exc)
    return result


_prev_cpu_times: Optional[tuple] = None


@app.get("/api/local-metrics-stream")
async def local_metrics_stream():
    """Proxy this ground station's own gs-metrics-manager SSE stream to the
    browser -- same metric set (CPU/RAM/GPU/NPU) and wire format as
    /api/metrics-stream, just reached directly over the docker network
    (internal-only, no host port) instead of via a remote host's nginx."""
    url = f"{LOCAL_METRICS_MANAGER_BASE}/metrics/stream"

    async def relay():
        try:
            async with httpx.AsyncClient(timeout=None, trust_env=False) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        yield f"event: error\ndata: {json.dumps({'status': resp.status_code})}\n\n"
                        return
                    async for chunk in resp.aiter_bytes():
                        if chunk:
                            yield chunk
        except httpx.HTTPError as exc:
            logger.warning("local-metrics-stream proxy failed: %s", exc)
            yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(relay(), media_type="text/event-stream")


@app.get("/api/metrics-stream")
async def metrics_stream(host: str = Query(...)):
    """Proxy metrics-manager's SSE stream (via the remote nginx) to the browser."""
    base = _remote_base(host)
    url = f"{base}/metrics/stream"

    async def relay():
        try:
            async with httpx.AsyncClient(verify=False, timeout=None, trust_env=False) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        yield f"event: error\ndata: {json.dumps({'status': resp.status_code})}\n\n"
                        return
                    async for chunk in resp.aiter_bytes():
                        if chunk:
                            yield chunk
        except httpx.HTTPError as exc:
            logger.warning("metrics-stream proxy failed for host=%s: %s", host, exc)
            yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(relay(), media_type="text/event-stream")


@app.get("/api/captions-stream")
async def captions_stream(host: str = Query(...), topic: str = Query(..., pattern=TOPIC_PATTERN)):
    """Bridge a caption topic (uav/caption/<name>, from pipeline-info's caption_topic) of the remote MQTT broker to the browser over SSE."""
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)

    def on_message(_client, _userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        loop.call_soon_threadsafe(queue.put_nowait, payload)

    def on_connect(client, _userdata, _flags, reason_code, _properties=None):
        if reason_code == 0:
            client.subscribe(topic)
            logger.info("captions-stream: subscribed to %s on %s", topic, host)
        else:
            logger.warning("captions-stream: MQTT connect failed (%s) for %s", reason_code, host)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(host, REMOTE_MQTT_PORT, keepalive=30)
    except OSError as exc:
        raise HTTPException(status_code=502, detail=f"Cannot reach MQTT broker at {host}:{REMOTE_MQTT_PORT}: {exc}")

    client.loop_start()

    async def relay():
        try:
            yield f"event: connected\ndata: {json.dumps({'topic': topic})}\n\n"
            while True:
                payload = await queue.get()
                yield f"data: {json.dumps(payload)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            client.loop_stop()
            client.disconnect()

    return StreamingResponse(relay(), media_type="text/event-stream")


@app.post("/api/relay-path")
async def relay_path(host: str = Query(...), camera: str = Query(..., pattern=CAMERA_PATTERN)):
    """(Re)configure the local mediamtx sidecar's "relay-<camera>" path to
    pull the remote host's H.264 RTSP stream on demand, for "H.264 Relay"
    video mode (see module docstring). Pure remux -- mediamtx does not
    transcode, the remote stream is already H.264.

    Idempotent/cheap to call on every connect (e.g. the user switching the
    host field, or re-polling pipeline-info) -- mediamtx's config API
    accepts repeat PATCHes to the same path name. Returns the path name for
    the dashboard to build its local WHEP viewer iframe URL; raises 502 if
    the mediamtx sidecar isn't reachable (e.g. docker-compose-mediamtx.yml
    wasn't brought up).
    """
    path_name = f"relay-{camera}"
    source = f"rtsp://{host}:{REMOTE_RTSP_PORT}/{camera}"
    # rtspTransport=tcp: the UAV host's nginx only forwards RTSP over TCP, so the default
    # "automatic" mode wastes several seconds trying UDP ("no UDP packets received,
    # switching to TCP") every time a viewer opens a stream.
    body = {"source": source, "sourceOnDemand": True, "rtspTransport": "tcp"}
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            resp = await client.patch(f"{MEDIAMTX_API_BASE}/v3/config/paths/patch/{path_name}", json=body)
            if resp.status_code == 404:
                # Path doesn't exist yet -- create it instead of patching.
                resp = await client.post(f"{MEDIAMTX_API_BASE}/v3/config/paths/add/{path_name}", json=body)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("relay-path config failed for host=%s camera=%s: %s", host, camera, exc)
        raise HTTPException(status_code=502, detail=f"Cannot configure local mediamtx relay: {exc}")
    return {"path": path_name}


# VSS natural-language search proxy (separate VSS Compose stack) -- see vss_search.py.
vss_live_sync.configure(_detect_running_cameras, REMOTE_RTSP_PORT)
app.include_router(vss_search_router)
app.include_router(vss_live_sync.router)
# Flight Summary report -- built from the caption history, keeps
# warm via the note_active() call in pipeline_info() above.
app.include_router(vss_summary_router)


class RevalidateStaticAssets:
    """Make browsers revalidate the dashboard's HTML/CSS/JS on every load
    (cheap 304s via ETag) so a rebuilt image is never paired with stale
    cached assets. Pure ASGI so /api/* streams (SSE, video) are untouched."""

    def __init__(self, asgi_app):
        self.app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return

        async def send_with_cache_header(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"]
                headers.append((b"cache-control", b"no-cache"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_cache_header)


app.add_middleware(RevalidateStaticAssets)

app.mount("/", StaticFiles(directory="static", html=True), name="static")
