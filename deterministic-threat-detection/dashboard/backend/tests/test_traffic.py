# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
import time

from app.controllers.traffic import IperfServer, TrafficController, parse_server_line

INTERVAL = "[  5]   3.00-4.00   sec  11.2 MBytes  94.0 Mbits/sec  0.045 ms  3/8133 (0.037%)  "
SUMMARY = "[  5]   0.00-10.00  sec   112 MBytes  94.0 Mbits/sec  0.040 ms  30/81330 (0.037%)  receiver"
OTHER = "[  5] local srv-noise port 5201 connected to inj-noise port 41234"


def test_parse_server_interval_line():
    rep = parse_server_line(INTERVAL)
    assert rep == {"mbps": 94.0, "jitter_ms": 0.045, "lost": 3, "total": 8133, "loss_pct": 0.037}


def test_summary_and_noise_lines_are_ignored():
    assert parse_server_line(SUMMARY) is None
    assert parse_server_line(OTHER) is None
    assert parse_server_line("") is None


def test_measured_goes_stale():
    server = IperfServer("srv-noise")
    server.last, server.last_time = parse_server_line(INTERVAL), 100.0
    assert server.measured(now=102.0)["mbps"] == 94.0
    assert server.measured(now=105.0) is None


def test_missing_binary_is_reported():
    server = IperfServer("srv-noise", binary="definitely-not-iperf3")
    server.start()
    assert "not found" in server.state()["error"] and not server.state()["running"]


def test_iperf_mode_launches_and_stops_the_client(monkeypatch):
    launched = []

    class FakeProc:
        returncode = None

        def __init__(self, cmd, **kw):
            launched.append((cmd, kw))

        def poll(self):
            return None if self.returncode is None else self.returncode

        def terminate(self):
            self.returncode = -15

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr("app.controllers.traffic.subprocess.Popen", FakeProc)
    t = TrafficController("iperf", 900, "srv-noise", "u@h", "inj-noise", guard_s=60)
    assert t.set_rate(400) == 400 and len(launched) == 1
    assert t.state()["running"] is True
    assert t.set_rate(2000) == 900 and len(launched) == 2  # restarted at the capped rate
    assert t.set_rate(0) == 0 and len(launched) == 2  # 0 stops, nothing new is started
    assert t.state()["running"] is False


def test_client_that_exits_is_reported(monkeypatch):
    class Dead:
        returncode = 255

        def __init__(self, *a, **k):
            pass

        def poll(self):
            return 255

    monkeypatch.setattr("app.controllers.traffic.subprocess.Popen", Dead)
    t = TrafficController("iperf", 900, "s", "u@h", "c")
    t.set_rate(100)
    state = t.state()
    assert state["running"] is False and "exited with code 255" in state["error"]
