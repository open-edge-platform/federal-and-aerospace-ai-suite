# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Use case 1 (latency): the camera side on machine-2 and machine-3 - a DL Streamer pipeline per camera that
# publishes detections plus the decoded frame over MQTT to the dashboard host. The dashboard itself is in
# ../dashboard; ../Makefile starts everything.
#   make up | down | status     start / stop / show the camera pipelines over ssh
#   STREAMS=0 make up           do not (re)start the RTSP publishers (common/streams) first

SHELL := /bin/bash
STREAMS ?= 1
export STREAMS

.PHONY: up down status

up:
	edge/deploy.sh up

down:
	edge/deploy.sh down

status:
	edge/deploy.sh status
