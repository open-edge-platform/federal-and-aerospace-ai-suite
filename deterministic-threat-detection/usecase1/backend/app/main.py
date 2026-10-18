# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Dashboard backend: MQTT latency feed, SSE stream, traffic and Qbv controls."""

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .controllers.switch import create_switch
from .controllers.traffic import IperfServer, TrafficController
from .latency import LatencyTracker
from .mqtt_source import MqttSource

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
PUSH_INTERVAL_S = 0.5


class TrafficRequest(BaseModel):
    rate_mbps: int = Field(ge=0)


class QbvRequest(BaseModel):
    enabled: bool


def create_app(start_mqtt=True):
    tracker = LatencyTracker(
        history_s=config.HISTORY_S,
        window_s=config.STATS_WINDOW_S,
        stall_after_s=config.STALL_AFTER_S,
        max_latency_s=config.MAX_PLAUSIBLE_LATENCY_S,
    )
    server = IperfServer(config.TRAFFIC_SERVER_IP, config.IPERF3_BIN) if config.TRAFFIC_MODE == "iperf" else None
    traffic = TrafficController(
        config.TRAFFIC_MODE,
        config.TRAFFIC_MAX_MBPS,
        config.TRAFFIC_SERVER_IP,
        config.TRAFFIC_CLIENT_TARGET,
        config.TRAFFIC_CLIENT_IP,
        server=server,
        guard_s=config.TRAFFIC_GUARD_S,
    )
    switch = create_switch(config)
    source = MqttSource(tracker, config.MQTT_HOST, config.MQTT_PORT, config.MQTT_TOPIC)

    @asynccontextmanager
    async def lifespan(app):
        if start_mqtt:
            source.start()
        switch.start()
        traffic.start()
        yield
        traffic.shutdown()
        switch.stop()
        if start_mqtt:
            source.stop()

    app = FastAPI(title="Deterministic Threat Detection", lifespan=lifespan)
    app.state.tracker, app.state.traffic = tracker, traffic
    app.state.switch, app.state.source = switch, source

    def status():
        return {
            "mqtt_connected": source.connected,
            "bad_messages": source.bad_messages,
            "traffic": traffic.state(),
            "qbv": switch.state(),
        }

    @app.get("/api/config")
    def get_config():
        return {
            "window_s": config.STATS_WINDOW_S,
            "history_s": config.HISTORY_S,
            "traffic_max_mbps": config.TRAFFIC_MAX_MBPS,
            "traffic_mode": config.TRAFFIC_MODE,
            "switch_mode": config.SWITCH_MODE,
            "qbv_port": switch.port,
        }

    @app.get("/api/history")
    def history():
        return {"now": time.time(), "points": tracker.history()}

    @app.get("/api/status")
    def get_status():
        return {"sources": tracker.snapshot(), **status()}

    @app.post("/api/traffic")
    def set_traffic(req: TrafficRequest):
        traffic.set_rate(req.rate_mbps)
        return traffic.state()

    @app.get("/api/qbv")
    def get_qbv():
        return switch.state()

    @app.post("/api/qbv")
    def set_qbv(req: QbvRequest):
        try:
            switch.set_enabled(req.enabled)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return switch.state()

    @app.post("/api/reset")
    def reset():
        tracker.reset()
        return {"ok": True}

    @app.get("/api/stream")
    async def stream():
        async def events():
            last = time.time()
            while True:
                now = time.time()
                body = {
                    "now": now,
                    "points": tracker.points_since(last),
                    "sources": tracker.snapshot(now),
                    **status(),
                }
                last = now
                yield f"data: {json.dumps(body)}\n\n"
                await asyncio.sleep(PUSH_INTERVAL_S)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


app = create_app()
