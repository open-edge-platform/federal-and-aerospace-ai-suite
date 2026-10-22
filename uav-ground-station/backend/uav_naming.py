# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Shared host/stream naming + registry for multi-UAV support.

The ground station can be connected to more than one UAV companion board at
once (one dashboard tab per host). Every one of those hosts' cameras gets
registered as its own VSS live stream (see vss_live_sync.py); those streams
need a name that is unique *across hosts*, both so two drones that happen to
use the same camera name (e.g. both configured with a "uav-front-camera" in
their own configs/cameras-*.yaml) don't collide in VSS, and so vss_search.py
can filter search results back down to "only this UAV's footage".

Unlike a fixed cpu/gpu/npu device set, camera names here are arbitrary,
operator-chosen strings (``CAMERA_PATTERN`` in main.py/vss_summary.py), so a
single combined string like ``uav-<host_tag>-<camera>`` cannot be reliably
split back into its two parts by regex alone (both halves can contain
dashes). Rather than guessing, this module keeps a small in-memory registry,
written by vss_live_sync.py as it registers/deregisters streams and read by
vss_search.py to resolve a VSS stream_name back to (host, camera) -- kept
here, rather than in either of those modules, so both can import it without a
circular dependency (vss_live_sync.py already imports vss_search.py).
"""

from __future__ import annotations

import re
from typing import Optional

_SANITIZE = re.compile(r"[^a-z0-9]+")

# Loose "looks like a stream this feature manages" check -- not meant to be
# parsed back into (host_tag, camera); use the registry functions below for
# that. Generous length bound: host_tag + "--" + a 48-char camera name.
MANAGED_NAME = re.compile(r"^uav-[a-z0-9-]{1,40}--[A-Za-z0-9_-]{1,48}$")

# Pre-multi-UAV stream name convention (bare camera name, no embedded host).
# Kept recognizable so the live-sync loop still manages/cleans up streams
# registered under this older convention, but -- having no embedded host --
# it can never match a host-scoped search filter; see vss_search.py.
LEGACY_NAME = re.compile(r"^uav-[A-Za-z0-9_-]{1,44}$")


def host_tag(host: str) -> str:
    """Sanitize a hostname/IP into a VSS-stream-name-safe, unique-enough tag."""
    tag = _SANITIZE.sub("-", (host or "").strip().lower()).strip("-")
    return tag or "host"


def stream_name(host: str, camera: str) -> str:
    return f"uav-{host_tag(host)}--{camera}"


def is_managed_name(name: str) -> bool:
    return bool(MANAGED_NAME.fullmatch(name or "") or LEGACY_NAME.fullmatch(name or ""))


# --- (host, camera) registry, authoritative source for "whose stream is this" ---
# stream_name -> (host, camera). Written by vss_live_sync.py on every
# reconciliation pass; read by vss_search.py when a request asks to be
# scoped to one host's footage, or to attach camera/host metadata to a
# result so the UI can show "which drone/camera did this clip come from".
_registry: dict = {}


def register(name: str, host: str, camera: str) -> None:
    _registry[name] = (host, camera)


def unregister(name: str) -> None:
    _registry.pop(name, None)


def replace_host_registry(host: str, entries: dict) -> None:
    """Replace every registered entry for `host` with `entries`
    (stream_name -> camera) in one go -- used at the end of each
    reconciliation pass so a camera that stopped being registered (pipeline
    stopped, camera removed from config) drops out of the registry too."""
    for name, (h, _camera) in list(_registry.items()):
        if h == host:
            del _registry[name]
    for name, camera in entries.items():
        _registry[name] = (host, camera)


def info_for(name: str) -> Optional[tuple]:
    """(host, camera) for a managed stream_name, or None if unknown (not
    registered by this feature, or registered before a restart of this
    container -- registry is in-memory only)."""
    return _registry.get(name)


def stream_names_for_host(host: str) -> set:
    return {name for name, (h, _camera) in _registry.items() if h == host}
