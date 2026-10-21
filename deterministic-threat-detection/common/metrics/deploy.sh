#!/usr/bin/env bash
# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Start / stop the metrics-manager on the machines that run nothing else of the demo (machine-4), over ssh.
#   ./deploy.sh up | down | status
#
# Machine-1 gets its metrics-manager from ../../dashboard, machine-2/3 from ../../usecase1/edge.
# Environment overrides: METRICS_HOSTS="user@host ..." (default: SSH_USER@M4_LAB_IP from lab.env)
#   METRICS_PORT=19090  IMAGE=docker.io/intel/metrics-manager:2026.2.0
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
[ ! -f "$ROOT/lab.env" ] || { set -a; . "$ROOT/lab.env"; set +a; }
METRICS_HOSTS=${METRICS_HOSTS:-${SSH_USER:+${M4_LAB_IP:+$SSH_USER@$M4_LAB_IP}}}
METRICS_PORT=${METRICS_PORT:-19090}
[ -n "$METRICS_HOSTS" ] || { echo "metrics: no host (set SSH_USER and M4_LAB_IP in lab.env); skipping"; exit 0; }

SSH=(ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new)

IMAGE=${IMAGE:-docker.io/intel/metrics-manager:2026.2.0}
NAME=tsn-metrics-manager

# Plain docker run: machine-4 has no docker compose plugin and installing one needs sudo.
up_one() {
  local host=$1
  echo "[$host] starting $NAME"
  "${SSH[@]}" "$host" "docker rm -f $NAME metrics-manager >/dev/null 2>&1; docker pull -q $IMAGE >/dev/null && \
    docker run -d --name $NAME --restart unless-stopped --privileged --pid host -v /sys:/sys:ro \
    -p $METRICS_PORT:9090 $IMAGE >/dev/null && echo started" 2>&1 | tail -2 | sed "s/^/[$host] /"
}
down_one() { "${SSH[@]}" "$1" "docker rm -f $NAME" 2>&1 | tail -1 | sed "s/^/[$1] removed /"; }
status_one() { echo "== $1"; "${SSH[@]}" "$1" "docker ps -a --filter name=$NAME --format '{{.Names}}\t{{.Status}}'" || true; }

each() { local h; for h in $METRICS_HOSTS; do "$1" "$h" || true; done; }
case "${1:-}" in
  up) each up_one ;;
  down) each down_one ;;
  status) each status_one ;;
  *) sed -n '4,6p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
