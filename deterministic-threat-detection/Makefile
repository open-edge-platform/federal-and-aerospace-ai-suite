# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Deterministic Threat Detection: both use cases behind one web dashboard.
#
#   make up        start everything: the RTSP streams on the camera machines, the dashboard (with the MQTT
#                  broker), use case 1 (camera pipelines on the camera machines) and use case 2 (SceneScape)
#   make down      stop everything (reverse order)
#   make status    what is running
#   make test      unit tests of the dashboard backend
#   make test-e2e  end-to-end test of use case 2 through the SceneScape UI (needs the stack up)
#   make help
#
# Run one part on its own with its own Makefile:
#   common/streams/start-synced-streams.sh up|down|status    RTSP "cameras" on the camera machines
#   make -C dashboard ...    the shared UI + backend + MQTT broker
#   make -C usecase1 ...     use case 1: camera pipelines on the camera machines
#   make -C usecase2 ...     use case 2: SceneScape + the mediamtx relay on this machine
#
# STREAMS=0 skips the RTSP publishers (they must already be running).

SHELL := /bin/bash
STREAMS ?= 1
STREAMS_SCRIPT := common/streams/start-synced-streams.sh

.PHONY: help up down status test test-e2e streams-up streams-down streams-status

help:
	@sed -n '4,19p' Makefile | sed 's/^# \{0,1\}//'

up:
	@[ "$(STREAMS)" != 1 ] || $(MAKE) streams-up
	# the dashboard mounts the SceneScape broker's CA certificate, which the secrets step creates
	$(MAKE) -C usecase2 secrets
	$(MAKE) -C dashboard up
	$(MAKE) -C usecase1 up STREAMS=0
	$(MAKE) -C usecase2 up STREAMS=0
	@echo "Everything is up. Dashboard: see the address printed above; SceneScape: https://localhost/"

down:
	-$(MAKE) -C usecase2 down STREAMS=0
	-$(MAKE) -C usecase1 down STREAMS=0
	-$(MAKE) -C dashboard down
	@[ "$(STREAMS)" != 1 ] || $(MAKE) streams-down

status:
	@echo "== dashboard"; $(MAKE) -s -C dashboard status
	@echo "== use case 1 (camera machines)"; $(MAKE) -s -C usecase1 status STREAMS=0
	@echo "== use case 2"; $(MAKE) -s -C usecase2 status

test:
	$(MAKE) -C dashboard test

test-e2e:
	$(MAKE) -C usecase2 test

streams-up:
	$(STREAMS_SCRIPT) up

streams-down:
	$(STREAMS_SCRIPT) down

streams-status:
	$(STREAMS_SCRIPT) status
