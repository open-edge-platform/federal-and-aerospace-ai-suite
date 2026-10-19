# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Proxy routes for the Video Search and Summarization (VSS) search feature.

VSS runs as its own containers, normally the minimal search-only set in
``docker-compose-vss.yml`` (which also sets ``VSS_ENABLED=true``). It can also
be a full VSS deployment started with VSS's own ``setup.sh``. This module only
talks to VSS's Pipeline Manager API and its object store over HTTP, the same
read-only proxy pattern the rest of viz-backend uses for the remote UAV host.
The browser never reaches VSS directly.

When ``VSS_ENABLED`` is not true, the dashboard hides the search UI and every
route below except ``/api/search/status`` returns 404:

  * ``GET  /api/search/status`` -- whether search is configured, VSS
    reachability, the VSS search feature flag and playback-quality options.
  * ``POST /api/search``        -- natural-language query; results are
    flattened and joined with filenames from Pipeline Manager's ``GET /videos``.
  * ``GET  /api/search-video``  -- Range-aware stream of a result's video
    object from VSS's object store (MinIO), so <video> can seek. With
    ``preview=1`` it serves a cached, low-bitrate transcode instead (see
    "Playback previews" below), falling back to the original on failure.
  * ``GET  /api/search-frame``  -- best-matching frame as JPEG via
    Pipeline Manager's ``GET /frames``; used as the result thumbnail and as the fallback
    when the browser can't decode the clip (e.g. some stored live-stream segments).
    ``width`` downscales it so a result list doesn't pull full 1080p frames.
"""

import asyncio
import hashlib
import logging
import os
import re
import shutil
import tempfile
from collections import OrderedDict
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote, unquote, urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

import uav_naming

logger = logging.getLogger("viz-backend.vss-search")

VSS_ENABLED = os.environ.get("VSS_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
# docker-compose-vss.yml points these at the pipeline-manager and minio-service
# containers. The defaults reach a full VSS deployment's nginx gateway
# (APP_HOST_PORT 12345) published on this same machine.
VSS_MANAGER_URL = os.environ.get("VSS_MANAGER_URL", "http://host.docker.internal:12345/manager").rstrip("/")
VSS_DATASTORE_URL = os.environ.get("VSS_DATASTORE_URL", "http://host.docker.internal:12345/datastore").rstrip("/")
VSS_DATASTORE_BUCKET = os.environ.get("VSS_DATASTORE_BUCKET", "video-summary")
VSS_SEARCH_TIMEOUT_SECONDS = float(os.environ.get("VSS_SEARCH_TIMEOUT_SECONDS", "60"))

# --- Relevance filtering ----------------------------------------------------
# VSS's relevance_score is min-max normalized per query (the top hit is always
# 1.0), so it ranks hits but cannot tell a real match from the best of a set of
# unrelated clips. score_breakdown.max_frame_score -- the raw query-to-frame
# similarity of the segment's best frame -- is the only absolute signal, so
# filtering is done on that:
#   1. Drop hits whose peak frame score is below VSS_SEARCH_MIN_PEAK_SCORE. This
#      is what turns "an elephant" over road footage into zero results.
#   2. Of the rest, keep hits whose peak is within VSS_SEARCH_RELATIVE_CUTOFF of
#      the best peak, trimming a weak tail behind a strong match.
# Both depend on the embedding model VSS runs (0.25 suits CLIP ViT-B/32), so
# both are tunable via env. Set VSS_SEARCH_MIN_PEAK_SCORE=0 and
# VSS_SEARCH_RELATIVE_CUTOFF=0 to show everything VSS returns.
VSS_SEARCH_MIN_PEAK_SCORE = float(os.environ.get("VSS_SEARCH_MIN_PEAK_SCORE", "0.25"))
VSS_SEARCH_RELATIVE_CUTOFF = float(os.environ.get("VSS_SEARCH_RELATIVE_CUTOFF", "0.90"))

# --- Playback previews / thumbnails ------------------------------------------
# Stored clips are full-resolution (live segments are 1080p at ~4 Mbps), which
# stalls playback for a browser on a slow or lossy link (VPN, WAN). With ffmpeg
# available, the player is served a cached H.264 transcode at
# VSS_PREVIEW_HEIGHT and at most VSS_PREVIEW_MAX_KBPS, with its index at the
# front of the file so playback starts after the first few KB. "Download clip"
# still returns the original. Set VSS_PREVIEW_ENABLED=false to always stream
# originals.
FFMPEG = shutil.which("ffmpeg")
# Quality the player starts in: "sd" (the preview) or "hd" (the original).
# Users can switch per clip, and the browser remembers their last choice.
VSS_PLAYBACK_DEFAULT = "hd" if os.environ.get("VSS_PLAYBACK_DEFAULT", "sd").strip().lower() == "hd" else "sd"
VSS_PREVIEW_ENABLED = os.environ.get("VSS_PREVIEW_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
VSS_PREVIEW_HEIGHT = max(144, min(1080, int(os.environ.get("VSS_PREVIEW_HEIGHT", "360"))))
VSS_PREVIEW_MAX_KBPS = max(100, min(8000, int(os.environ.get("VSS_PREVIEW_MAX_KBPS", "800"))))
VSS_PREVIEW_CACHE_DIR = Path(os.environ.get("VSS_PREVIEW_CACHE_DIR", os.path.join(tempfile.gettempdir(), "vss-preview-cache")))
VSS_PREVIEW_CACHE_MB = max(50, int(os.environ.get("VSS_PREVIEW_CACHE_MB", "1024")))
# Results whose previews are transcoded as soon as a search returns, so the
# clip the player opens first is usually ready by the time it's requested.
VSS_PREVIEW_PREWARM = max(0, min(10, int(os.environ.get("VSS_PREVIEW_PREWARM", "3"))))
PREVIEW_SOURCE_MAX_BYTES = 1024 * 1024 * 1024
PREVIEW_TIMEOUT_SECONDS = 180.0
THUMBNAIL_CACHE_ENTRIES = 512

_preview_locks: dict = {}
_preview_slots = asyncio.Semaphore(2)
_background_tasks: set = set()
_thumbnail_cache: "OrderedDict[tuple, bytes]" = OrderedDict()

SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
MAX_QUERY_LENGTH = 500
TIME_UNITS = ("minutes", "hours", "days", "weeks")
# IPv4 address or DNS hostname; mirrors vss_live_sync.HOST_PATTERN (duplicated
# rather than imported, since vss_live_sync.py already imports this module).
HOST_PATTERN = r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"

# Upstream headers forwarded to the browser for video playback/seeking.
_PASSTHROUGH_VIDEO_HEADERS = ("content-length", "content-range", "accept-ranges", "etag", "last-modified")
_VIDEO_CONTENT_TYPES = {"mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime", "mkv": "video/x-matroska"}

router = APIRouter()


def _require_enabled() -> None:
    if not VSS_ENABLED:
        raise HTTPException(status_code=404, detail="VSS search is not enabled on this ground station.")


def _client(base_url: str = VSS_MANAGER_URL, timeout: Optional[float] = VSS_SEARCH_TIMEOUT_SECONDS) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, timeout=timeout, trust_env=False)


def _is_safe_object_path(path: str) -> bool:
    parts = path.split("/")
    return bool(parts) and all(SAFE_SEGMENT.fullmatch(p) and p not in (".", "..") for p in parts)


def _object_path_from_url(value: Any) -> Optional[str]:
    """Return '<bucket>/<...>' if value is already a datastore object path.

    Mirrors VSS's own UI (ui/react/src/redux/video/videoUrl.ts): dataprep
    download-API URLs (absolute internal hostnames, or anything with a query
    string) are not playable object paths and are rejected.
    """
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value.startswith("/") or "?" in value or "/download" in value:
        return None
    path = value.strip("/")
    return path if _is_safe_object_path(path) else None


def _resolve_object_path(metadata: dict, video: Optional[dict]) -> Optional[str]:
    for key in ("video_rel_url", "video_url"):
        path = _object_path_from_url(metadata.get(key))
        if path:
            return path
    if video:
        bucket = (video.get("dataStore") or {}).get("bucket")
        url = video.get("url")
        if bucket and url:
            path = f"{bucket}/{str(url).strip('/')}"
            if _is_safe_object_path(path):
                return path
    bucket = metadata.get("bucket_name") or VSS_DATASTORE_BUCKET
    video_id = metadata.get("video_id")
    if bucket and video_id:
        path = f"{bucket}/{video_id}/source.mp4"
        if _is_safe_object_path(path):
            return path
    return None


def _as_tag_list(tags: Any) -> list:
    if isinstance(tags, list):
        return [str(t).strip() for t in tags if str(t).strip()]
    if isinstance(tags, str):
        return [t.strip() for t in tags.split(",") if t.strip()]
    return []


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _frame_params(metadata: dict) -> Optional[dict]:
    """Query params for /api/search-frame, preferring the hit's best_frame_info."""
    info = metadata.get("best_frame_info") if isinstance(metadata.get("best_frame_info"), dict) else {}
    video_id = info.get("video_id") or metadata.get("video_id")
    timestamp = _as_float(info.get("timestamp"))
    if timestamp is None:
        timestamp = _as_float(metadata.get("seek_timestamp"))
    if not video_id or timestamp is None or not SAFE_SEGMENT.fullmatch(str(video_id)):
        return None
    params = {"video_id": video_id, "timestamp": round(max(timestamp, 0.0), 3)}
    bucket = info.get("bucket_name") or metadata.get("bucket_name")
    if bucket and SAFE_SEGMENT.fullmatch(str(bucket)):
        params["bucket_name"] = bucket
    media_path = info.get("media_path") or metadata.get("media_path")
    if media_path and _is_safe_object_path(str(media_path)):
        params["media_path"] = media_path
    return params


def _live_captured_at(media_path: Any, offset: Optional[float]) -> Optional[str]:
    """Live segments are named segments/<unix-epoch>.mp4; return an ISO time."""
    match = re.fullmatch(r"segments/(\d{9,11})\.[A-Za-z0-9]+", str(media_path or ""))
    if not match:
        return None
    return datetime.fromtimestamp(int(match.group(1)) + (offset or 0.0), tz=timezone.utc).isoformat()


def _camera_and_host(stream_name: Optional[str]) -> tuple:
    """(camera, host) for a result's VSS stream_name, using uav_naming's
    registry of currently-managed live streams. None, None for uploaded
    videos (no stream_name) or a stream this feature doesn't recognize
    (e.g. hand-registered, or indexed before this container last restarted --
    the registry is in-memory only)."""
    if not stream_name:
        return None, None
    info = uav_naming.info_for(stream_name)
    if info:
        return info[1], info[0]
    if uav_naming.LEGACY_NAME.fullmatch(stream_name):
        # Pre-multi-UAV stream name (bare camera, no embedded host) -- the
        # camera is still known, just not which host it came from.
        return stream_name[4:], None
    return None, None


def _belongs_to_host(result: dict, host: str) -> bool:
    """True if `result` should be shown when scoping search to `host`.

    Only live results are scoped at all -- a result from an uploaded/
    recorded video has no "owning" UAV host to filter by, so it's always
    kept. A live result with a stream_name this feature doesn't recognize
    (not currently managed -- e.g. hand-registered in VSS, or indexed before
    a container restart cleared the in-memory registry) is also kept rather
    than hidden, since we cannot prove it belongs to a *different* host.
    """
    if result.get("source") != "live":
        return True
    result_host = result.get("host")
    if result_host is None:
        return True
    return result_host == host


def _flatten_results(payload: Any) -> list:
    """VSS wraps hits as {"results": [{"query_id", "results": [...]}]}."""
    groups = payload.get("results", []) if isinstance(payload, dict) else payload
    hits = []
    for group in groups or []:
        if isinstance(group, dict) and isinstance(group.get("results"), list):
            hits.extend(group["results"])
    return hits


class TimeFilter(BaseModel):
    value: int = Field(..., ge=1, le=10000)
    unit: str = Field(..., pattern="^(" + "|".join(TIME_UNITS) + ")$")


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=MAX_QUERY_LENGTH)
    tags: Optional[str] = Field(None, max_length=500)
    timeFilter: Optional[TimeFilter] = None
    # Optional: scope results to one UAV's own footage (multi-UAV dashboards
    # keep a tab per connected host). Only affects *live* results -- a result
    # from an uploaded/recorded video that isn't tied to any host's live
    # stream is never filtered out, since it isn't "someone else's drone".
    host: Optional[str] = Field(None, min_length=1, max_length=253, pattern=HOST_PATTERN)


@router.get("/api/search/status")
async def search_status():
    status = {"enabled": VSS_ENABLED, "reachable": False, "search_enabled": False}
    if not VSS_ENABLED:
        return status
    # Informational only (architecture view); set by docker-compose-vss.yml.
    status["devices"] = {
        key: os.environ[env][:8] for key, env in (
            ("query_embedding", "VSS_QUERY_EMBEDDING_DEVICE"),
            ("ingest_embedding", "VSS_INGEST_EMBEDDING_DEVICE"),
            ("detection", "VSS_DETECTION_DEVICE"),
        ) if os.environ.get(env)
    }
    status["playback"] = {
        "preview_available": _previews_available(),
        "default": VSS_PLAYBACK_DEFAULT,
        "preview_height": VSS_PREVIEW_HEIGHT,
    }
    try:
        async with _client(timeout=5.0) as client:
            health = await client.get("/health")
            status["reachable"] = health.status_code == 200
            if status["reachable"]:
                features = await client.get("/app/features")
                if features.status_code == 200:
                    status["search_enabled"] = features.json().get("search") == "FEATURE_ON"
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("VSS status check failed (%s): %s", VSS_MANAGER_URL, exc)
        status["error"] = "VSS is not reachable"
    return status


@router.post("/api/search")
async def search(req: SearchRequest):
    _require_enabled()
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Search query cannot be empty.")
    body: dict = {"query": query}
    if req.tags and req.tags.strip():
        body["tags"] = req.tags.strip()
    if req.timeFilter:
        body["timeFilter"] = req.timeFilter.model_dump()

    try:
        async with _client() as client:
            resp = await client.post("/search/query", json=body)
            if resp.status_code >= 400:
                detail = _upstream_message(resp)
                logger.warning("VSS search failed (%s): %s", resp.status_code, detail)
                code = 400 if resp.status_code == 400 else 502
                raise HTTPException(status_code=code, detail=f"VSS search failed: {detail}")
            hits = _flatten_results(resp.json())

            videos: dict = {}
            try:
                vresp = await client.get("/videos")
                if vresp.status_code == 200:
                    videos = {v.get("videoId"): v for v in vresp.json().get("videos", []) if isinstance(v, dict)}
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("VSS video list lookup failed: %s", exc)

            streams: dict = {}
            try:
                sresp = await client.get("/streams")
                if sresp.status_code == 200:
                    streams = {s.get("stream_id"): s for s in sresp.json().get("streams", []) if isinstance(s, dict)}
            except (httpx.HTTPError, ValueError) as exc:
                logger.debug("VSS stream list lookup failed: %s", exc)
    except httpx.HTTPError as exc:
        logger.warning("VSS search request failed (%s): %s", VSS_MANAGER_URL, exc)
        raise HTTPException(status_code=502, detail="Cannot reach the VSS search service.")
    except ValueError:
        raise HTTPException(status_code=502, detail="VSS returned an invalid response")

    results = []
    for hit in hits:
        metadata = hit.get("metadata") if isinstance(hit, dict) else None
        if not isinstance(metadata, dict):
            continue
        video_id = metadata.get("video_id")
        video = videos.get(video_id)
        stream = streams.get(video_id)
        object_path = _resolve_object_path(metadata, video)
        frame = _frame_params(metadata)
        best = metadata.get("best_frame_info") if isinstance(metadata.get("best_frame_info"), dict) else {}
        is_live = bool(best.get("is_live")) or stream is not None
        stream_name = (stream or {}).get("stream_name")
        camera, result_host = _camera_and_host(stream_name)
        results.append({
            "video_id": video_id,
            "source": "live" if is_live else "upload",
            "filename": ((video or {}).get("dataStore") or {}).get("fileName") or (video or {}).get("name"),
            "stream_name": stream_name,
            # Which UAV/camera this clip came from, if it's a live result
            # from a camera this feature currently manages (multi-UAV
            # dashboards use this to show/filter "which drone" a result is
            # from); None for uploaded videos or unrecognized streams.
            "camera": camera,
            "host": result_host,
            "captured_at": _live_captured_at(frame.get("media_path"), frame.get("timestamp")) if frame else None,
            "score": _as_float(metadata.get("relevance_score")),
            "peak_score": _peak_score(metadata),
            "segment_start": _as_float(metadata.get("segment_start")),
            "segment_end": _as_float(metadata.get("segment_end")),
            "seek_timestamp": _as_float(metadata.get("seek_timestamp")),
            "tags": _as_tag_list(metadata.get("tags")),
            "video_proxy_url": f"/api/search-video?path={quote(object_path, safe='/')}" if object_path else None,
            "thumbnail_url": f"/api/search-frame?{urlencode(frame)}" if frame else None,
        })

    if req.host:
        results = [r for r in results if _belongs_to_host(r, req.host)]

    results, raw_count = _filter_and_score(results)
    _prewarm_previews(results)
    return {
        "query": query,
        "results": results,
        "total_matches": raw_count,
        "filtered_out": raw_count - len(results),
    }


@router.get("/api/search-video")
async def search_video(
    request: Request,
    path: str = Query(..., min_length=3, max_length=512),
    preview: bool = Query(False),
):
    _require_enabled()
    path = path.strip("/")
    if not _is_safe_object_path(path) or "/" not in path:
        raise HTTPException(status_code=400, detail="Invalid video path")

    if preview and _previews_available():
        try:
            preview_file = await _ensure_preview(path)
        except _MediaNotFound:
            raise HTTPException(status_code=404, detail="Video not available")
        except Exception as exc:  # serve the original rather than fail playback
            logger.warning("VSS preview transcode failed for %s: %s", path, exc)
        else:
            return FileResponse(
                preview_file,
                media_type="video/mp4",
                headers={"Cache-Control": "private, max-age=3600", "X-Preview": "1"},
            )

    headers = {}
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    client = _client(VSS_DATASTORE_URL, timeout=httpx.Timeout(10.0, read=None))
    try:
        upstream = await client.send(client.build_request("GET", f"/{path}", headers=headers), stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        logger.warning("VSS video fetch failed for %s: %s", path, exc)
        raise HTTPException(status_code=502, detail="Cannot reach the VSS object store.")

    if upstream.status_code not in (200, 206):
        status = upstream.status_code
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(status_code=404 if status in (403, 404) else 502, detail="Video not available")

    out_headers = {k: upstream.headers[k] for k in _PASSTHROUGH_VIDEO_HEADERS if k in upstream.headers}
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    media_type = _VIDEO_CONTENT_TYPES.get(ext) or upstream.headers.get("content-type", "application/octet-stream")

    async def close():
        await upstream.aclose()
        await client.aclose()

    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=out_headers,
        media_type=media_type,
        background=BackgroundTask(close),
    )


@router.get("/api/search-frame")
async def search_frame(
    video_id: str = Query(..., min_length=1, max_length=128, pattern=SAFE_SEGMENT.pattern),
    timestamp: float = Query(..., ge=0, le=10_000_000),
    bucket_name: Optional[str] = Query(None, max_length=128, pattern=SAFE_SEGMENT.pattern),
    media_path: Optional[str] = Query(None, max_length=256),
    width: Optional[int] = Query(None, ge=64, le=1920),
):
    _require_enabled()
    params: dict = {"video_id": video_id, "timestamp": timestamp}
    if bucket_name:
        params["bucket_name"] = bucket_name
    if media_path:
        if not _is_safe_object_path(media_path):
            raise HTTPException(status_code=400, detail="Invalid media path")
        params["media_path"] = media_path

    cache_key = (video_id, round(timestamp, 3), bucket_name, media_path, width)
    cached = _thumbnail_cache.get(cache_key)
    if cached is not None:
        _thumbnail_cache.move_to_end(cache_key)
        return Response(content=cached, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    try:
        async with _client(timeout=30.0) as client:
            resp = await client.get("/frames", params=params)
    except httpx.HTTPError as exc:
        logger.warning("VSS frame fetch failed for %s: %s", video_id, exc)
        raise HTTPException(status_code=502, detail="Cannot reach the VSS search service.")
    if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("image/"):
        raise HTTPException(status_code=404 if resp.status_code in (400, 404) else 502, detail="Frame not available")

    content, media_type = resp.content, resp.headers["content-type"]
    if width and FFMPEG:
        try:
            content = await _run_ffmpeg(
                ["-f", "image2pipe", "-i", "pipe:0", "-vf", f"scale='min({width},iw)':-2",
                 "-q:v", "5", "-f", "image2pipe", "-c:v", "mjpeg", "pipe:1"],
                stdin_data=resp.content, timeout=15.0,
            )
            media_type = "image/jpeg"
        except Exception as exc:  # the full-size frame still works as a thumbnail
            logger.warning("Thumbnail resize failed for %s: %s", video_id, exc)
    if media_type == "image/jpeg":
        _thumbnail_cache[cache_key] = content
        while len(_thumbnail_cache) > THUMBNAIL_CACHE_ENTRIES:
            _thumbnail_cache.popitem(last=False)
    return Response(content=content, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})


class _MediaNotFound(Exception):
    pass


def _previews_available() -> bool:
    return VSS_PREVIEW_ENABLED and FFMPEG is not None


async def _run_ffmpeg(args: list, stdin_data: Optional[bytes] = None, timeout: float = 60.0) -> bytes:
    """Run ffmpeg with an argument list (never a shell) and return its stdout."""
    proc = await asyncio.create_subprocess_exec(
        FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", *args,
        stdin=asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin_data), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"ffmpeg timed out after {timeout:.0f}s")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg exited {proc.returncode}: {err.decode(errors='replace').strip()[-300:]}")
    return out


async def _download_object(path: str, dest: Path) -> None:
    received = 0
    async with _client(VSS_DATASTORE_URL, timeout=httpx.Timeout(10.0, read=60.0)) as client:
        async with client.stream("GET", f"/{path}") as resp:
            if resp.status_code in (403, 404):
                raise _MediaNotFound(path)
            if resp.status_code != 200:
                raise RuntimeError(f"object store returned HTTP {resp.status_code}")
            with dest.open("wb") as fh:
                async for chunk in resp.aiter_bytes():
                    received += len(chunk)
                    if received > PREVIEW_SOURCE_MAX_BYTES:
                        raise RuntimeError("source video is too large to preview")
                    fh.write(chunk)


async def _ensure_preview(path: str) -> Path:
    """Return the cached preview for an object path, transcoding it once if needed."""
    key = hashlib.sha256(path.encode()).hexdigest()[:32]
    out = VSS_PREVIEW_CACHE_DIR / f"{key}.mp4"
    if out.is_file():
        os.utime(out)
        return out

    lock = _preview_locks.setdefault(key, asyncio.Lock())
    try:
        async with lock:
            if out.is_file():
                return out
            VSS_PREVIEW_CACHE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
            async with _preview_slots:
                with tempfile.TemporaryDirectory(dir=VSS_PREVIEW_CACHE_DIR) as work:
                    src = Path(work) / "source"
                    part = Path(work) / "preview.mp4"
                    await _download_object(path, src)
                    kbps = VSS_PREVIEW_MAX_KBPS
                    await _run_ffmpeg([
                        "-i", str(src),
                        "-map", "0:v:0", "-map", "0:a:0?",
                        "-vf", f"scale=-2:'min({VSS_PREVIEW_HEIGHT},ih)'",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
                        "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k",
                        "-g", "30", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "64k",
                        "-movflags", "+faststart",
                        "-y", str(part),
                    ], timeout=PREVIEW_TIMEOUT_SECONDS)
                    os.replace(part, out)
            _prune_preview_cache()
            return out
    finally:
        if not lock.locked():
            _preview_locks.pop(key, None)


def _prune_preview_cache() -> None:
    try:
        files = sorted(VSS_PREVIEW_CACHE_DIR.glob("*.mp4"), key=lambda f: f.stat().st_mtime)
        total = sum(f.stat().st_size for f in files)
        limit = VSS_PREVIEW_CACHE_MB * 1024 * 1024
        while files and total > limit:
            oldest = files.pop(0)
            total -= oldest.stat().st_size
            oldest.unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("Preview cache prune failed: %s", exc)


def _prewarm_previews(results: list) -> None:
    if not _previews_available() or not VSS_PREVIEW_PREWARM:
        return
    paths = []
    for r in results:
        url = r.get("video_proxy_url") or ""
        if url.startswith("/api/search-video?path="):
            path = unquote(url.split("=", 1)[1])
            if path not in paths:
                paths.append(path)
        if len(paths) >= VSS_PREVIEW_PREWARM:
            break

    async def warm(path: str) -> None:
        try:
            await _ensure_preview(path)
        except Exception as exc:
            logger.debug("Preview pre-warm failed for %s: %s", path, exc)

    for path in paths:
        task = asyncio.create_task(warm(path))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)


def _peak_score(metadata: dict) -> Optional[float]:
    breakdown = metadata.get("score_breakdown")
    if not isinstance(breakdown, dict):
        return None
    return _as_float(breakdown.get("max_frame_score"))


def _filter_and_score(results: list) -> tuple:
    """Apply the peak-score filters described above. Returns (kept, raw_count).

    Hits without a peak score (older VSS builds that don't report a
    score_breakdown) are kept unfiltered rather than silently dropped.
    """
    raw_count = len(results)
    peaks = [r["peak_score"] for r in results if r.get("peak_score") is not None]
    if not peaks:
        return results, raw_count

    threshold = max(VSS_SEARCH_MIN_PEAK_SCORE, max(peaks) * VSS_SEARCH_RELATIVE_CUTOFF)
    kept = [r for r in results if r.get("peak_score") is None or r["peak_score"] >= threshold]
    kept.sort(key=lambda r: (r.get("score") is not None, r.get("score") or 0.0), reverse=True)
    return kept, raw_count


def _upstream_message(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        msg = data.get("message") or data.get("detail") or data.get("error")
        if isinstance(msg, list):
            msg = "; ".join(str(m) for m in msg)
        return str(msg)[:300] if msg else f"HTTP {resp.status_code}"
    except ValueError:
        return f"HTTP {resp.status_code}"
