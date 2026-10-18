# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Runtime settings, read from environment variables."""

import os


def _int(name, default):
    return int(os.environ.get(name, default))


def _float(name, default):
    return float(os.environ.get(name, default))


MQTT_HOST = os.environ.get("MQTT_HOST", "127.0.0.1")
MQTT_PORT = _int("MQTT_PORT", 1883)
# Topics are tsn_demo/<source>/inference; the middle part names the chart series.
MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "tsn_demo/+/inference")

# Rolling window used for the KPI numbers (mean / p95 / max).
STATS_WINDOW_S = _float("STATS_WINDOW_S", 10)
# How much history the server keeps per source for the chart.
HISTORY_S = _float("HISTORY_S", 120)
# A source with no message for this long is shown as stalled.
STALL_AFTER_S = _float("STALL_AFTER_S", 2)
# Messages with an absurd latency (clock not synchronised) are flagged, not plotted.
MAX_PLAUSIBLE_LATENCY_S = _float("MAX_PLAUSIBLE_LATENCY_S", 60)

# "sim" only records the request; "iperf" drives iperf3 from the injector host.
TRAFFIC_MODE = os.environ.get("TRAFFIC_MODE", "sim")
# iperf3 -b counts UDP payload; 1000M would exceed 1 Gbit/s on the wire.
TRAFFIC_MAX_MBPS = _int("TRAFFIC_MAX_MBPS", 900)
# "sim" fakes the switch; "moxa" drives it through the Moxa scripts on a control host.
SWITCH_MODE = os.environ.get("SWITCH_MODE", "sim")
SWITCH_PORT = _int("SWITCH_PORT", 1)
# Machine-2 on the lab network: its port and NIC carry none of the injected load.
SWITCH_SSH_TARGET = os.environ.get("SWITCH_SSH_TARGET", "tsndemo@10.106.147.105")
SWITCH_REMOTE_DIR = os.environ.get("SWITCH_REMOTE_DIR", "~/moxa")
# Reads are always allowed; enabling/disabling the shaper needs SWITCH_ALLOW_WRITE=1.
SWITCH_ALLOW_WRITE = os.environ.get("SWITCH_ALLOW_WRITE", "0") == "1"
# Gate control list used for "Qbv on": INTERVAL_US:QUEUES per slot (same as port 1 today).
SWITCH_SCHEDULE = os.environ.get("SWITCH_SCHEDULE", "90000:6,1,0 10000:5,1,0")

TRAFFIC_SERVER_IP = os.environ.get("TRAFFIC_SERVER_IP", "192.168.5.11")
# Machine-4 on the lab network (control path); the traffic itself leaves via VLAN 5.
TRAFFIC_CLIENT_TARGET = os.environ.get("TRAFFIC_CLIENT_TARGET", "tsndemo@10.106.147.208")
TRAFFIC_CLIENT_IP = os.environ.get("TRAFFIC_CLIENT_IP", "192.168.5.14")
IPERF3_BIN = os.environ.get("IPERF3_BIN", "iperf3")
TRAFFIC_GUARD_S = _int("TRAFFIC_GUARD_S", 3600)
