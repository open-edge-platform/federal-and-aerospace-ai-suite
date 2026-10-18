# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def client():
    with TestClient(create_app(start_mqtt=False)) as c:
        yield c


def test_status_and_config(client):
    assert client.get("/api/config").json()["qbv_port"] == 1
    body = client.get("/api/status").json()
    assert body["sources"] == {} and body["qbv"]["enabled"] is False


def test_traffic_rate_is_clamped(client):
    assert client.post("/api/traffic", json={"rate_mbps": 250}).json()["rate_mbps"] == 250
    assert client.post("/api/traffic", json={"rate_mbps": 99999}).json()["rate_mbps"] == 900
    assert client.post("/api/traffic", json={"rate_mbps": -1}).status_code == 422
    assert client.post("/api/traffic", json={"rate_mbps": 0}).json()["running"] is False


def test_qbv_applies_asynchronously_and_rejects_overlap(client):
    client.app.state.switch.apply_delay_s = 0.2
    assert client.post("/api/qbv", json={"enabled": True}).json()["busy"] is True
    assert client.post("/api/qbv", json={"enabled": False}).status_code == 409
    time.sleep(0.4)
    state = client.get("/api/status").json()["qbv"]
    assert state["enabled"] is True and state["busy"] is False


def test_history_shows_added_samples(client):
    client.app.state.tracker.add("Cam_x1_0", 0.012, recv_time=time.time())
    points = client.get("/api/history").json()["points"]
    assert len(points["Cam_x1_0"]) == 1
    assert client.get("/api/status").json()["sources"]["Cam_x1_0"]["count"] == 1
    client.post("/api/reset")
    assert client.get("/api/status").json()["sources"] == {}


def test_traffic_command_uses_vlan5_addresses(client):
    cmd = client.app.state.traffic.command(300)
    assert cmd[0:2] == ["ssh", "-tt"] and cmd[-2] == "tsndemo@10.106.147.208"  # lab address, not VLAN 1
    assert "-B 192.168.5.14" in cmd[-1] and "-c 192.168.5.11" in cmd[-1] and "-b 300M" in cmd[-1]
    assert "timeout " in cmd[-1] and "-t 3600" in cmd[-1]
