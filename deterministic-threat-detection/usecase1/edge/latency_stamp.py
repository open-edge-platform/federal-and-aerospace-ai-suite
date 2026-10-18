# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""gvapython elements for the latency demo (one module, two instances in the pipeline).

LatencyStamp  - first in the pipeline: remembers when each frame entered it (capture_ts).
PublishResult - last in the pipeline: publishes the detections itself over MQTT and stamps
                send_ts immediately before publishing, so the dashboard can split
                  processing = send_ts - capture_ts      (decode + inference, machine dependent)
                  network    = arrival - send_ts         (what TSN is about)
The system clock is disciplined by PTP (ptp4l + phc2sys), so no offset correction is needed.
"""

import json
import os
import time

import paho.mqtt.client as mqtt

_counter = {"seq": 0}


class LatencyStamp:
    def process(self, frame):
        seq = _counter["seq"]
        _counter["seq"] += 1
        # Travels with the frame as metadata, so it survives drops and reordering downstream.
        frame.add_message(json.dumps({"capture_ts": time.time(), "capture_seq": seq}))
        return True


def _stamp(frame):
    """Return (capture_ts, seq) added by LatencyStamp, or (None, None)."""
    try:
        for text in reversed(list(frame.messages())):
            data = json.loads(text)
            if isinstance(data, dict) and "capture_ts" in data:
                return data["capture_ts"], data.get("capture_seq")
    except Exception:  # metadata API differences must not stop the pipeline
        pass
    return None, None


class PublishResult:
    def __init__(self, topic):
        self.topic = topic
        self.cam = topic.split("/")[1] if topic.count("/") >= 2 else topic
        self.dropped = 0
        # The pipeline-server image ships paho-mqtt 1.x (no CallbackAPIVersion); 2.x needs it.
        if hasattr(mqtt, "CallbackAPIVersion"):
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        else:
            self.client = mqtt.Client()
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)
        # paho sends a PINGREQ every <keepalive> seconds even while publishing, and each one delays the
        # next publish by ~10-25 ms (measured: spikes every 7 s with keepalive 7). A long keepalive
        # keeps those out of the latency numbers; a dead link is still noticed by the TCP reset.
        self.client.connect_async(
            os.environ.get("MQTT_HOST", "127.0.0.1"), int(os.environ.get("MQTT_PORT", "1884")),
            keepalive=int(os.environ.get("MQTT_KEEPALIVE", "3600")),
        )
        self.client.loop_start()

    @staticmethod
    def _objects(frame):
        out = []
        try:
            for region in frame.regions():
                rect = region.rect()
                out.append({"label": region.label(), "conf": round(region.confidence(), 3),
                            "x": rect.x, "y": rect.y, "w": rect.w, "h": rect.h})
        except Exception:  # detection metadata is optional for the latency demo
            pass
        return out[:20]

    def process(self, frame):
        capture_ts, seq = _stamp(frame)
        objects = self._objects(frame)
        message = {
            "cam": self.cam,
            "metadata": {"ptp_timestamp": capture_ts, "seq": seq, "objects": len(objects)},
            "objects": objects,
        }
        # Stamp last, right before the publish call, to keep processing time out of the network number.
        message["metadata"]["send_timestamp"] = time.time()
        info = self.client.publish(self.topic, json.dumps(message), qos=0)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            self.dropped += 1
        return True
