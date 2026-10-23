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
# UC2 camera source (video|basler); defaults to what src/scene/.env holds. The dashboard diagram follows it.
SOURCE ?= $(or $(shell sed -n 's/^SOURCE=//p' src/scene/.env 2>/dev/null),video)
export SOURCE
-include lab.env
# This machine is machine-1, so its lab address is M1_LAB_IP (falls back to the default-route address)
LAB_IP ?= $(or $(M1_LAB_IP),$(shell ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($$i=="src") print $$(i+1)}'))
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
	@echo ""
	@echo "Everything is up."
	@echo "  Dashboard:  https://$(LAB_IP)/dashboard/   (self-signed certificate: accept the browser warning)"
	@echo "  SceneScape: https://$(LAB_IP)/"

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
