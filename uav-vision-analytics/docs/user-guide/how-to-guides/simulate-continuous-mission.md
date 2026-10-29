<!--
SPDX-FileCopyrightText: (C) 2026 Intel Corporation
SPDX-License-Identifier: Apache-2.0
-->

# Testing Against a Simulated, Continuously-Armed Mission

PX4 SITL auto-disarms after a short idle period with no RC/GCS input. Both
`pipeline_manager.py`'s ARMED-triggered auto-start (standalone mode) and the
UAV Mission Compute SDK's arm-gated RTSP publishing depend on the vehicle
staying armed. If you're testing pipelines interactively — not flying a
scripted mission — you will otherwise hit unexplained stream drop-outs.

> [!IMPORTANT]
> This tutorial describes **simulation-only** testing conveniences for
> interactive development against PX4 SITL. It is not a change to, and must
> never be applied to, real flight safety/arming logic.

## Prerequisites

- A running simulated stack — standalone mode (`make pymav-up`) or UAV
  Mission Compute SDK mode (SDK's `make up-sim-camera` + `make uavsdk-up`).
- QGroundControl connected, if you also want to observe arming state visually
  — see the [QGroundControl guide](./qgroundcontrol.md).

## Why PX4 SITL auto-disarms

PX4's safety logic auto-disarms when it detects no active RC/GCS input for a
timeout period — this exists to prevent a real vehicle from remaining armed
unattended, and PX4 SITL faithfully reproduces it. During interactive
pipeline testing (manually starting/stopping pipelines, checking overlays,
tailing logs) rather than flying a scripted mission, that idle window is
often exceeded, so the vehicle disarms and dependent pipelines/streams stop.

## Steps

### Standalone (pymavlink) mode — keep-alive pattern

Re-issue an arm command periodically in a background loop while you do other
testing in a separate terminal:

```bash
while true; do
  curl -s -X POST http://localhost:8080/action/arm > /dev/null 2>&1 \
    || true   # ignore errors if already armed or endpoint differs per SITL setup
  sleep 20
done
```

> [!NOTE]
> The exact re-arm mechanism depends on how you normally arm in your setup
> (QGroundControl click, MAVLink command, or a REST endpoint like the
> UAVSDK's `/action/arm`). Use whichever method you already use to arm, just
> on a repeating timer shorter than the idle-disarm timeout.

### UAV Mission Compute SDK mode — keep-alive pattern

The SDK exposes a REST action endpoint. Loop it the same way:

```bash
while true; do
  curl -sf -X POST http://localhost:8080/action/arm > /dev/null 2>&1 || true
  sleep 20
done
```

Run this in its own terminal so it keeps running while you separately start
pipelines and inspect streams/logs in other terminals.

## Verify

```bash
curl -k -s https://<HOST_IP>/pipelines/status | python3 -m json.tool
```

Confirm the expected pipeline(s) stay `RUNNING` for longer than the normal
idle-disarm timeout, instead of stopping a few tens of seconds in.

## Troubleshooting

Arm/disarm flapping that leaves a stream down is covered in
[Troubleshooting — Rapid arm/disarm flapping](./troubleshooting.md#rapid-armdisarm-flapping-leaves-a-stream-down-sitl).
This keep-alive pattern is for SITL testing only; do not work around PX4's
idle-disarm safety behaviour on real flight hardware.
