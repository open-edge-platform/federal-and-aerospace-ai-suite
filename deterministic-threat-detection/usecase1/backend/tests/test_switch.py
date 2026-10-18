# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
import time

import pytest

from app.controllers.switch import MoxaSwitch, SimSwitch, parse_schedule, parse_tas

CURRENT = """port 1: config-change=True cycle=100000000 ns (100000 us)
  slot 0: interval=90000 us gates=0x43 queues=q6, q1, q0
  slot 1: interval=10000 us gates=0x23 queues=q5, q1, q0
"""
EMPTY = "port 4: config-change=False cycle=1000000 ns (1000 us)\n"


def test_parse_tas_enabled_and_empty():
    tas = parse_tas(CURRENT)
    assert tas["enabled"] and tas["cycle_us"] == 100000
    assert tas["slots"] == [{"interval_us": 90000, "queues": [6, 1, 0]},
                            {"interval_us": 10000, "queues": [5, 1, 0]}]
    assert not parse_tas(EMPTY)["enabled"]
    with pytest.raises(ValueError):
        parse_tas("garbage")


def test_parse_schedule():
    assert parse_schedule("90000:6,1,0 10000:5,1,0") == ["--slot", "90000:6,1,0", "--slot", "10000:5,1,0"]
    with pytest.raises(ValueError):
        parse_schedule("90000:")


def test_port_2_is_refused():
    with pytest.raises(ValueError):
        MoxaSwitch(2, "host", "~/moxa", "100:1")


def test_moxa_is_read_only_by_default_and_never_writes():
    calls = []
    sw = MoxaSwitch(1, "host", "~/moxa", "90000:6,1,0", run=lambda a, timeout=60: calls.append(a) or CURRENT)
    sw.refresh()
    assert sw.state()["enabled"] and sw.state()["read_only"]
    with pytest.raises(PermissionError):
        sw.set_enabled(False)
    assert calls == [["get", "--port", "1"]]  # no set/clear was issued


def test_moxa_write_issues_set_or_clear_then_rereads():
    state = {"out": EMPTY}
    calls = []

    def run(args, timeout=60):
        calls.append(args)
        if args[0] == "set":
            state["out"] = CURRENT
        if args[0] == "clear":
            state["out"] = EMPTY
        return state["out"]

    sw = MoxaSwitch(1, "host", "~/moxa", "90000:6,1,0 10000:5,1,0", allow_write=True, run=run)
    sw.refresh()
    assert not sw.state()["enabled"]
    sw.set_enabled(True)
    for _ in range(50):
        if not sw.busy:
            break
        time.sleep(0.02)
    assert sw.state()["enabled"]
    assert ["set", "--port", "1", "--slot", "90000:6,1,0", "--slot", "10000:5,1,0"] in calls
    sw.set_enabled(False)
    for _ in range(50):
        if not sw.busy:
            break
        time.sleep(0.02)
    assert not sw.state()["enabled"] and ["clear", "--port", "1"] in calls


def test_moxa_read_failure_is_reported_not_raised():
    def run(args, timeout=60):
        raise RuntimeError("ssh: connect timed out")

    sw = MoxaSwitch(1, "host", "~/moxa", "100:1", run=run)
    sw.refresh()
    assert "read failed" in sw.state()["error"] and sw.state()["known"] is False


def test_sim_switch_state_shape():
    assert SimSwitch().state()["read_only"] is False
