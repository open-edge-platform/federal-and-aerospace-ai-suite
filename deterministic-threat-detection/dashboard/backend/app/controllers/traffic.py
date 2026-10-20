# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Background traffic injector: iperf3 UDP from machine-4 to machine-1 over VLAN 5.

The client is started over ssh on the *lab* network (so control never depends on the TSN path);
the iperf3 server runs here, on machine-1's VLAN 5 address, and reports what actually arrived.
"""

import logging
import re
import shlex
import shutil
import subprocess
import threading
import time

log = logging.getLogger("traffic")

# UDP server interval line: [  5]   0.00-1.00   sec  11.2 MBytes  94.0 Mbits/sec  0.045 ms  0/8133 (0%)
SERVER_LINE = re.compile(
    r"\s(\d+\.\d+)-(\d+\.\d+)\s+sec\s+[\d.]+\s+\w+Bytes\s+([\d.]+)\s+Mbits/sec"
    r"\s+([\d.]+)\s+ms\s+(\d+)/(\d+)\s+\(([\d.e+-]+)%\)"
)


def parse_server_line(line):
    """Return {'mbps','jitter_ms','lost','total','loss_pct'} for an interval line, else None."""
    m = SERVER_LINE.search(line)
    if not m or "receiver" in line or "sender" in line:
        return None
    start, end = float(m[1]), float(m[2])
    if end - start > 1.5:  # the final summary line spans the whole test
        return None
    return {"mbps": float(m[3]), "jitter_ms": float(m[4]), "lost": int(m[5]),
            "total": int(m[6]), "loss_pct": float(m[7])}


class IperfServer:
    """Managed 'iperf3 -s' bound to the VLAN 5 address; keeps the latest interval report."""

    def __init__(self, bind_ip, binary="iperf3"):
        self.bind_ip, self.binary = bind_ip, binary
        self.error = None
        self.last = None
        self.last_time = 0.0
        self._proc = None
        self._thread = None

    def start(self):
        if self._proc is not None:
            return
        if shutil.which(self.binary) is None:
            self.error = f"{self.binary} not found on this machine (install iperf3)"
            log.error(self.error)
            return
        cmd = [self.binary, "-s", "-B", self.bind_ip, "-i", "1", "-f", "m", "--forceflush"]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()
        time.sleep(0.3)
        if self._proc.poll() is not None:
            self.error = f"iperf3 server exited: {self._proc.stdout.read().strip()[-200:]}"
            self._proc = None
            log.error(self.error)

    def _read(self):
        for line in self._proc.stdout:
            report = parse_server_line(line)
            if report:
                self.last, self.last_time = report, time.time()

    def stop(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def measured(self, now=None, max_age_s=3.0):
        now = now if now is not None else time.time()
        if self.last and now - self.last_time <= max_age_s:
            return self.last
        return None

    def state(self):
        return {"running": self._proc is not None and self._proc.poll() is None, "error": self.error}


class TrafficController:
    """Rate in Mbit/s; 0 stops the load. mode 'sim' only records the request."""

    def __init__(self, mode, max_mbps, server_ip, client_target, client_ip,
                 server=None, guard_s=3600, ssh_opts=None):
        self.mode = mode
        self.max_mbps = max_mbps
        self.server_ip, self.client_target, self.client_ip = server_ip, client_target, client_ip
        self.server = server
        self.guard_s = guard_s
        self.ssh_opts = ssh_opts or [
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=accept-new"]
        self.rate_mbps = 0
        self.error = None
        self._proc = None
        self._lock = threading.Lock()

    def command(self, rate_mbps):
        """ssh command that runs the iperf3 UDP client on the injector.

        -tt gives the remote process a terminal, so it gets SIGHUP and stops if this ssh
        connection drops; 'timeout' and iperf3's own -t bound it if even that fails.
        """
        remote = (
            f"timeout {self.guard_s + 5} iperf3 -c {self.server_ip} -B {self.client_ip} -u "
            f"-b {int(rate_mbps)}M -t {self.guard_s} -f m"
        )
        return ["ssh", "-tt", *self.ssh_opts, self.client_target, remote]

    def start(self):
        if self.server:
            self.server.start()

    def set_rate(self, rate_mbps):
        rate = max(0, min(int(rate_mbps), self.max_mbps))
        with self._lock:
            if self.mode == "iperf":
                self._stop_locked()
                if rate > 0:
                    try:
                        cmd = self.command(rate)
                        log.info("starting load: %s", shlex.join(cmd))
                        self._proc = subprocess.Popen(
                            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
                        self.error = None
                    except OSError as exc:
                        self.error = str(exc)
                        rate = 0
            self.rate_mbps = rate
        return rate

    def _stop_locked(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def state(self):
        running = self.rate_mbps > 0
        if self.mode == "iperf" and self.rate_mbps > 0 and self._proc is not None \
                and self._proc.poll() is not None:
            running = False
            self.error = f"iperf3 client exited with code {self._proc.returncode}"
        server = self.server.state() if self.server else None
        if self.mode == "iperf" and server and server["error"] and not self.error:
            self.error = server["error"]
        return {
            "mode": self.mode,
            "rate_mbps": self.rate_mbps,
            "max_mbps": self.max_mbps,
            "running": running,
            "error": self.error,
            "measured": self.server.measured() if self.server else None,
        }

    def shutdown(self):
        with self._lock:
            self._stop_locked()
        if self.server:
            self.server.stop()
