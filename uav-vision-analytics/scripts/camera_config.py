# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Camera configuration for the pipeline manager: load, validate and turn it into pipeline start requests.

One entry per camera says which video it plays, which device and model detect objects, whether the VLM
captions it (and on which device, with which model and prompt) and whether detections are drawn on the
stream. From that the manager picks one of the nine pipelines in ``configs/config-pymavlink-pipelines.json``:

    detection only          uav_object_detection_<det>             det: cpu | gpu | npu
    detection + captioning  uav_object_detection_<det>_<vlm>      vlm: cpu | gpu

This module has no dependency on MAVLink or on the manager, so a REST endpoint or the web UI can reuse the
same validation (``CamerasConfig``), the JSON schema (``json_schema()``) and the plan (``build_plan()``).
The file is YAML (JSON is valid YAML, so ``.json`` files load too).

CLI:
    camera_config.py check [FILE]     validate and print what would run (no hardware needed beyond the file checks)
    camera_config.py plan  [FILE]     the same plan as JSON, including the start requests
    camera_config.py schema           JSON schema of the configuration (for UI forms)
"""
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

SCHEMA_VERSION = 1
RESOURCES_DIR = os.getenv("PIPELINE_RESOURCES_DIR", "/home/pipeline-server/resources")
DEFAULT_FILE = os.getenv("CAMERAS_CONFIG", "/home/pipeline-server/configs/cameras.yaml")

# The pipelines accept these values only through schema patterns, so keep the same rules here.
_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_VIDEO = re.compile(r"^[A-Za-z0-9_.-]+\.(avi|mp4|mkv|ts)$")
_REL_MODEL = re.compile(r"^[A-Za-z0-9_./-]+\.xml$")
_VLM_MODEL = re.compile(r"^[A-Za-z0-9_.-]+$")
_PROMPT = re.compile(r"^[A-Za-z0-9 ,.?'-]+$")
_PATH = re.compile(r"^[A-Za-z0-9_-]{1,48}$")
_TOPIC = re.compile(r"^uav/caption/[A-Za-z0-9_-]+$")

Device = Literal["cpu", "gpu", "npu"]
VlmDevice = Literal["cpu", "gpu"]


class ConfigError(Exception):
    """The configuration is not usable; the message lists every problem, one per line."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")      # a misspelled key is an error, not silently ignored


class Detection(_Strict):
    device: Device = "npu"
    # relative to <resources>/models; the pipeline server only accepts models below that folder
    model: str = "yolo11s/yolo11s_openvino_model/yolo11s.xml"

    @field_validator("model")
    @classmethod
    def _model(cls, value: str) -> str:
        if not _REL_MODEL.match(value) or ".." in value.split("/") or value.startswith("/"):
            raise ValueError("must be a relative path to an .xml file below resources/models (letters, digits, _ . / -)")
        return value


class Captioning(_Strict):
    enabled: bool = False
    device: VlmDevice = "gpu"                       # the VLM runs on cpu or gpu only
    model: str = "InternVL2-1B"                      # folder name below <resources>/ov_models/<device>/
    prompt: str = "Describe what you see in the scene."
    max_new_tokens: int = Field(default=50, ge=1, le=4096)

    @field_validator("model")
    @classmethod
    def _model(cls, value: str) -> str:
        if not _VLM_MODEL.match(value) or value in (".", ".."):
            raise ValueError("must be a model folder name (letters, digits, _ . -)")
        return value

    @field_validator("prompt")
    @classmethod
    def _prompt(cls, value: str) -> str:
        if not _PROMPT.match(value):
            raise ValueError("may contain only letters, digits, spaces and , . ? ' -")
        return value


class Camera(_Strict):
    id: str
    enabled: bool = True
    video: str = "uav_sample_front.avi"              # file name below <resources>/videos
    overlay: bool = True                              # False hides the detection boxes AND the telemetry text
    detection: Detection = Detection()
    captioning: Captioning = Captioning()
    rtsp_path: Optional[str] = None                   # default: uav-<id with _ replaced by ->
    mqtt_topic: Optional[str] = None                  # default: uav/caption/<id>

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not _ID.match(value):
            raise ValueError("must start with a lowercase letter and contain only a-z, 0-9 and _ (max 32)")
        return value

    @field_validator("video")
    @classmethod
    def _video(cls, value: str) -> str:
        if not _VIDEO.match(value):
            raise ValueError("must be a file name like uav_sample_front.avi (avi, mp4, mkv or ts, no folders)")
        return value

    @field_validator("rtsp_path")
    @classmethod
    def _rtsp_path(cls, value):
        if value is not None and not _PATH.match(value):
            raise ValueError("may contain only letters, digits, _ and - (max 48)")
        return value

    @field_validator("mqtt_topic")
    @classmethod
    def _topic(cls, value):
        if value is not None and not _TOPIC.match(value):
            raise ValueError("must look like uav/caption/<name>")
        return value


class CamerasConfig(_Strict):
    version: int = SCHEMA_VERSION
    cameras: list[Camera] = Field(min_length=1)

    @field_validator("version")
    @classmethod
    def _version(cls, value: int) -> int:
        if value != SCHEMA_VERSION:
            raise ValueError(f"unsupported version {value} (this software reads version {SCHEMA_VERSION})")
        return value

    @model_validator(mode="after")
    def _unique(self):
        for field, label in (("id", "camera id"), ("stream_path", "RTSP path")):
            seen = {}
            for camera in self.cameras:
                key = camera.id if field == "id" else stream_path(camera)
                if key in seen:
                    raise ValueError(f"duplicate {label} '{key}' (cameras '{seen[key]}' and '{camera.id}')")
                seen[key] = camera.id
        return self


# ── derived values ────────────────────────────────────────────────────────────

def stream_path(camera: Camera) -> str:
    return camera.rtsp_path or "uav-" + camera.id.replace("_", "-")


def pipeline_name(camera: Camera) -> str:
    det = camera.detection.device
    return f"uav_object_detection_{det}_{camera.captioning.device}" if camera.captioning.enabled else f"uav_object_detection_{det}"


@dataclass(frozen=True)
class CameraPlan:
    """What the manager runs for one enabled camera."""
    camera_id: str
    pipeline: str
    rtsp_path: str
    mqtt_topic: Optional[str]
    overlay: bool
    summary: str
    request: dict           # body of POST /pipelines/user_defined_pipelines/<pipeline>


def build_plan(config: CamerasConfig, *, resources_dir: str = RESOURCES_DIR, check_files: bool = True,
               thickness: str = "6") -> list[CameraPlan]:
    """Turn the enabled cameras into start requests. Raises ConfigError if a referenced file is missing."""
    problems, plans = [], []
    for camera in config.cameras:
        if not camera.enabled:
            continue
        det, cap = camera.detection, camera.captioning
        model_path = f"{resources_dir}/models/{det.model}"
        label = f"{camera.id.replace('_', '-')}-{det.device.upper()}" + (f"-{cap.device.upper()}-Caption" if cap.enabled else "")
        parameters = {
            "video": camera.video,
            "detection_model": model_path,
            # cameras sharing device and model share one loaded model; a different model gets its own instance
            "detection_instance_id": re.sub(r"[^a-z0-9_]", "_", f"inst{det.device}_{os.path.splitext(os.path.basename(det.model))[0]}".lower()),
            "overlay_label": label,
        }
        topic = None
        if cap.enabled:
            topic = camera.mqtt_topic or f"uav/caption/{camera.id}"
            vlm_path = f"{resources_dir}/ov_models/{cap.device}/{cap.model}"
            parameters.update({"captioner_model_path": vlm_path, "captioner_prompt": cap.prompt,
                               "captioner_max_new_tokens": cap.max_new_tokens, "mqtt_topic": topic})
        frame = {"type": "rtsp", "path": stream_path(camera), "encoding": "h264", "overlay-properties": {"thickness": thickness}}
        if not camera.overlay:
            frame["overlay"] = False
        if check_files:
            for what, path in (("video", f"{resources_dir}/videos/{camera.video}"), ("detection model", model_path),
                               *((("captioning model", vlm_path),) if cap.enabled else ())):
                if not os.path.exists(path):
                    problems.append(f"cameras[{camera.id}]: {what} not found: {path}")
        summary = f"{det.device.upper()} {os.path.basename(det.model)}" + (f" + {cap.device.upper()} {cap.model}" if cap.enabled else " (no captions)")
        plans.append(CameraPlan(camera.id, pipeline_name(camera), stream_path(camera), topic, camera.overlay, summary,
                                {"destination": {"frame": frame}, "parameters": parameters}))
    if problems:
        raise ConfigError("\n".join(problems))
    return plans


# ── loading ───────────────────────────────────────────────────────────────────

def _format_errors(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors():
        where = ".".join(str(part) for part in err["loc"]) or "(file)"
        lines.append(f"{where}: {err['msg'].removeprefix('Value error, ')}")
    return "\n".join(lines)


def parse_config(data) -> CamerasConfig:
    """Validate an already parsed document (the web UI / REST API passes its JSON body here)."""
    if not isinstance(data, dict):
        raise ConfigError("(file): the configuration must be a mapping with a 'cameras' list")
    try:
        return CamerasConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_format_errors(exc)) from None


def load_config(path: str = DEFAULT_FILE) -> CamerasConfig:
    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from None
    return parse_config(data)


def json_schema() -> dict:
    return CamerasConfig.model_json_schema()


# ── command line ──────────────────────────────────────────────────────────────

def _table(plans: list[CameraPlan]) -> str:
    rows = [("camera", "pipeline", "stream path", "overlay", "detection / captioning")]
    rows += [(p.camera_id, p.pipeline, p.rtsp_path, "on" if p.overlay else "off", p.summary) for p in plans]
    widths = [max(len(row[i]) for row in rows) for i in range(5)]
    return "\n".join("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in rows)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "check"
    path = argv[1] if len(argv) > 1 else DEFAULT_FILE
    if command == "schema":
        print(json.dumps(json_schema(), indent=2))
        return 0
    if command not in ("check", "plan"):
        print(__doc__)
        return 2
    try:
        config = load_config(path)
        plans = build_plan(config)
    except ConfigError as exc:
        print(f"{path}: NOT valid\n" + "\n".join("  " + line for line in str(exc).splitlines()), file=sys.stderr)
        return 1
    if command == "plan":
        print(json.dumps([asdict(p) for p in plans], indent=2))
        return 0
    disabled = [c.id for c in config.cameras if not c.enabled]
    print(f"{path}: valid, {len(plans)} camera(s) enabled" + (f", disabled: {', '.join(disabled)}" if disabled else ""))
    print(_table(plans))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
