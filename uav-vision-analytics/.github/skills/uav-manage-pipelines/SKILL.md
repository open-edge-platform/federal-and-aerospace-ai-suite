---
name: uav-manage-pipelines
description: >-
  Start, stop, inspect, and modify DL Streamer Pipeline Server pipelines in
  an already-deployed uav-vision-analytics stack — via the arm/disarm
  pipeline manager, the REST API directly, or by editing an element's
  properties / parameter schema / adding a pipeline in configs/config-*.json.
  USE FOR: "start/stop a pipeline by hand", "what pipelines are running",
  "change the detection threshold", "a pipeline fails to start / 400 from
  the REST API", "add a new parameter to a pipeline", "the captioning branch
  needs a different frame rate". DO NOT USE FOR: declaring which camera uses
  which pipeline (that's a configs/cameras-*.yaml edit — use
  `uav-manage-cameras`), swapping a model file (use `uav-change-detection-
  model` / `uav-change-vlm-model`), or scaffolding a brand-new stack
  (use `uav-vision-analytics`).
license: Apache-2.0
compatibility: >-
  Requires an already-deployed uav-vision-analytics stack checked out at a
  known path, reachable via its nginx reverse proxy (self-signed TLS,
  `curl -k`). Editing configs/config-*.json requires recreating the
  dlstreamer-pipeline-server container to pick up the change (its pipeline
  root is a tmpfs volume reset on recreation).
---

<!-- SPDX-FileCopyrightText: (C) 2026 Intel Corporation -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Manage UAV Pipelines Skill

Two layers: the **pipeline manager** (`make start-rtsp`) drives every
pipeline automatically from `configs/cameras-*.yaml` as the vehicle
arms/disarms, and the **REST API** starts/stops/inspects a pipeline directly
(scripting, or a one-off run with custom parameters). The pipeline
*definitions* themselves (`configs/config-*.json`) are a fixed matrix of
GStreamer launch strings plus a parameter schema — this skill also covers
editing that file when an element's behaviour (not which camera uses it)
needs to change.

## Canonical Documentation (read before acting — do not rely on memorized snippets)

| Task | Read this file in the target repo first |
| --- | --- |
| Start/stop/check a pipeline (manager or REST API), list available pipelines | `docs/user-guide/how-to-customize/pipeline-management/manage-pipelines.md` |
| Change an element's property, add/change a parameter, pipeline naming, add a pipeline | `docs/user-guide/how-to-customize/pipeline-management/modify-pipelines.md` |
| Which pipeline a camera selects, camera file schema | `docs/user-guide/how-to-customize/camera-management/configure-cameras.md` |
| Inspect what a running pipeline detected | `docs/user-guide/how-to-guides/view-detection-logs.md` |

Read the live copy in the target repo for exact REST paths, `curl` syntax,
and the pipeline JSON shape — these are generated from the actual shipped
`config-*.json` and can differ by app version; do not hardcode a remembered
payload.

## How to Use This Skill

1. Confirm `{{STACK_DIR}}`, deployment mode, and `HOST_IP` (for REST/RTSP URLs).
2. Ask, in one batched question, what's needed:
   - Operate: start/stop/check a pipeline by hand, or via the manager —
     which camera(s)/pipeline name, with which parameters if starting.
   - Modify: which element/property, or which new parameter, in which
     pipeline name(s) — and whether this should apply to one device variant
     or the whole matrix (cpu/gpu/npu × caption cpu/gpu).
3. Read `manage-pipelines.md` and/or `modify-pipelines.md` as applicable for
   the exact commands/JSON shape.
4. Act (REST call, or edit `configs/config-*.json`), then validate, apply,
   and verify per the guardrails/completion criteria below.

## Parameter Validation (enforce BEFORE acting)

| Context | Rule | Why |
| --- | --- | --- |
| Starting a pipeline | pipeline `name` exists in the mounted `config.json` (list first if unsure) | a typo'd name 404s |
| Stopping/checking a pipeline | use the `instance_id` string (32-char hex) from the POST response, never the pipeline `name` | `DELETE /pipelines/{instance_id}`, not `/pipelines/{name}/{id}` |
| Editing an element property | keep the element's device in step with the pipeline's name (`uav_object_detection_gpu` keeps `device=GPU` throughout) | a mismatched device silently fails or runs on the wrong hardware |
| Adding a parameter | give it a `type`, a `default`, and a `pattern`/`minimum`/`maximum` restricting caller input | an unconstrained parameter lets a start request inject arbitrary pipeline behaviour |
| Captioning-branch edits | device stays `cpu`/`gpu` only, frame-rate throttle (`videorate ... framerate=1/5`) stays unless the user explicitly wants a different cadence | `gvagenai` has no NPU plugin; removing the throttle overloads the VLM |

## Execution Guardrails

- The REST API is reached only through nginx at `https://<HOST_IP>/` with a
  self-signed certificate (`curl -k`) — `dlstreamer-pipeline-server`'s own
  port is not published to the host; never suggest a direct `:8081` URL.
- If a REST call hangs or gets an unrelated `403`/proxy error even though the
  stack is healthy, a shell-level `http_proxy`/`https_proxy` is routing
  local/LAN traffic through a corporate proxy. Bypass it per call:
  `curl -k -s --noproxy '*' "https://${HOST_IP}/pipelines/status"`. See
  `docs/user-guide/how-to-guides/troubleshooting.md#pipelines`.
- `GET /pipelines/status` retains every instance's history (`COMPLETED`,
  `ERROR`, `ABORTED`) until the container restarts — it never shrinks back
  down on its own. Any script that counts/stops pipelines must filter on
  `state`, never trust raw array length: `state in ("RUNNING", "QUEUED",
  "STARTING")` for active/stoppable instances, `state == "RUNNING"` only
  when averaging FPS/throughput.
- Never add, remove, or rename a pipeline just to support a new camera
  combination that's actually a `configs/cameras-*.yaml` concern — check
  with `uav-manage-cameras`'s scope first; only touch `config-*.json` when
  an element's *behaviour* must change for everyone using that pipeline.
- Anything in the GStreamer string that is not a `{parameters[x]}`
  placeholder is fixed and can only be changed by editing the file — do not
  try to override it from a start request.
- Validate a hand-edited GStreamer string with `gst-launch-1.0` (placeholders
  replaced with real values) before saving it — a bad string only fails at
  pipeline *start*, not at config load, so a mistake is otherwise invisible
  until someone arms the vehicle.
- After any `configs/config-*.json` edit, recreate the container
  (`make pymav-down && make pymav-up`, or the `uavsdk` equivalent) — its
  pipeline root is a tmpfs volume, and `restart` alone keeps the stale
  config; then `make start-rtsp` to restart the pipeline manager.
- Stopping a pipeline through the manager means disarming the vehicle. Stopping the manager
  itself (Ctrl+C, `docker stop`, `pkill -TERM -f pipeline_manager.py`) also stops every camera
  it started — it does not leave them running. To stop pipelines while the manager keeps
  waiting for the vehicle, use the REST stop-all loop documented in
  `docs/user-guide/how-to-customize/pipeline-management/manage-pipelines.md`
  (section "Stop all running pipelines"; there is no single stop-all endpoint, and
  `pipeline_manager.py` has no `--stop-all` flag — only `--config`, `--start-now`, `--status`),
  not `docker stop` on the container.
- `make start-rtsp` runs `docker exec -it ...` and needs a real terminal —
  launched from a non-interactive context (a background script, `nohup`,
  a non-tty SSH session) it fails with "cannot attach stdin to a TTY-enabled
  container" and, because the Makefile recipe is prefixed `-` (ignore
  errors), `make` still exits `0`, silently leaving no manager running.
  For non-interactive use, start the manager with
  `docker exec -d -e HOST_IP="$HOST_IP" uav-va-dlstreamer-pipeline-server python3
  /home/pipeline-server/scripts/pipeline_manager.py --start-now` instead (no
  vehicle arming required — see `references/CAMERAS.md`), and confirm with
  `make cameras-status`, not by trusting the launch command's own exit code.
- Report exact REST calls and file edits made; never run
  `make pymav-down`/`make uavsdk-down` without the user's confirmation, since
  it drops every currently-streaming camera.

## Completion Criteria

1. For a manual start: the REST call returns an `instance_id`, and
   `GET /pipelines/{instance_id}/status` reports `RUNNING`.
2. For a manual stop: `DELETE /pipelines/{instance_id}` succeeds and a
   subsequent status check shows that `id`'s `state` as `ABORTED`/`COMPLETED`,
   not `RUNNING`/`QUEUED`/`STARTING` — the entry itself never disappears from
   `/pipelines/status` (history is retained until container restart), so
   "no longer in the list" is the wrong check; "no longer counted as active"
   is the right one.
3. For an element/parameter edit: the container was recreated (not just
   restarted), the pipeline manager was restarted with a method appropriate
   to how it's being run (interactive `make start-rtsp`, or `docker exec -d
   ... --start-now` for non-interactive validation), and `make
   cameras-status` shows the affected camera(s) running the updated pipeline.
4. For a new parameter: a start request setting it is accepted (no `400`),
   and the resulting pipeline behaves as expected (verified via RTSP output,
   MQTT metadata, or the detection log as appropriate).
5. No pipeline name/path regression for cameras not in scope of the change.
