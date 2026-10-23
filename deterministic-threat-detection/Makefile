# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Deterministic Threat Detection: TSN demonstration for Intel NIC.
#
#   make up        start everything: the RTSP streams on the camera machines, the dashboard (with the MQTT
#                  broker), the load agent on machine-4, the camera pipelines on the camera machines and the
#                  scene stack (SceneScape, DL Streamer, mediamtx)
#   make down      stop everything (reverse order)
#   make status    what is running
#   make help
#
#
#

SHELL := /bin/bash
STREAMS ?= 1
STREAMS_SCRIPT := src/camera-node/streams/start-synced-streams.sh

.PHONY: help up down status test test-e2e streams-up streams-down streams-status

help:
	@sed -n '4,15p' Makefile | sed 's/^# \{0,1\}//'

up:
	@[ "$(STREAMS)" != 1 ] || $(MAKE) streams-up
	# the dashboard mounts the SceneScape broker's CA certificate, which the secrets step creates
	$(MAKE) -C src/scene secrets
	$(MAKE) -C src/dashboard up
	src/traffic-node/deploy.sh up
	STREAMS=0 src/camera-node/pipeline/deploy.sh up
	$(MAKE) -C src/scene up STREAMS=0
	@echo "Everything is up. Dashboard: see the address printed above; SceneScape: https://localhost/"

down:
	-$(MAKE) -C src/scene down STREAMS=0
	-STREAMS=0 src/camera-node/pipeline/deploy.sh down
	-$(MAKE) -C src/dashboard down
	-src/traffic-node/deploy.sh down
	@[ "$(STREAMS)" != 1 ] || $(MAKE) streams-down

status:
	@echo "== dashboard"; $(MAKE) -s -C src/dashboard status
	@echo "== traffic node: metrics-manager + load agent (machine-4)"; src/traffic-node/deploy.sh status
	@echo "== camera nodes (machine-2/3)"; src/camera-node/pipeline/deploy.sh status
	@echo "== scene stack"; $(MAKE) -s -C src/scene status

test:
	$(MAKE) -C src/dashboard test

test-e2e:
	$(MAKE) -C src/scene test

streams-up:
	$(STREAMS_SCRIPT) up

streams-down:
	$(STREAMS_SCRIPT) down

streams-status:
	$(STREAMS_SCRIPT) status
