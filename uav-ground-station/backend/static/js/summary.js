// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

// "Flight Summary": modal with a small form (host/cameras/window) that calls
// viz-backend's /api/summary (JSON, rendered inline) and exposes a matching
// /api/summary.pdf link for download. Independent of VSS -- works whenever a
// camera has been started with captioning on, since it's built entirely from
// the MQTT caption stream (see backend/caption_log.py + vss_summary.py), not
// a VSS deployment.
//
// Unlike the earlier device-based (cpu/gpu/npu) design, cameras here are a
// dynamic, per-deployment set of names (e.g. "uav-front-camera"), so the
// camera checkbox list is populated on the fly from /api/detect-pipelines
// instead of being a fixed markup block.
(() => {
  const modal = document.getElementById("summary-modal");
  const openBtn = document.getElementById("topbar-summary-btn");
  const closeBtn = document.getElementById("summary-modal-close");
  const form = document.getElementById("summary-form");
  const hostInput = document.getElementById("summary-host-input");
  const cameraChecks = document.getElementById("summary-camera-checks");
  const windowInput = document.getElementById("summary-window-input");
  const highlightsInput = document.getElementById("summary-highlights-input");
  const generateBtn = document.getElementById("summary-generate-btn");
  const downloadBtn = document.getElementById("summary-download-btn");
  const body = document.getElementById("summary-body");

  let lastFocus = null;
  let inFlight = null;
  let camerasLoadedForHost = null;

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function selectedCameras() {
    return Array.from(cameraChecks.querySelectorAll('input[name="summary-camera"]:checked')).map((cb) => cb.value);
  }

  function currentHost() {
    // Prefill from the main host field, same pattern arch.js uses, but let
    // the user override it (e.g. to summarize a different host than the one
    // currently shown in the video cards).
    if (hostInput.value.trim()) return hostInput.value.trim();
    const main = document.getElementById("host-input");
    return main ? main.value.trim() : "";
  }

  async function populateCameras(host, { force = false } = {}) {
    if (!host) {
      cameraChecks.replaceChildren(el("span", "muted", "Enter a UAV host above to list its cameras\u2026"));
      camerasLoadedForHost = null;
      return;
    }
    if (!force && camerasLoadedForHost === host) return;
    cameraChecks.replaceChildren(el("span", "muted", "Looking up cameras\u2026"));
    try {
      const res = await fetch(`/api/detect-pipelines?host=${encodeURIComponent(host)}`);
      const data = await res.json();
      const cameras = Array.isArray(data.cameras) ? data.cameras : [];
      if (!data.reachable) {
        cameraChecks.replaceChildren(el("span", "muted", `Could not reach ${host}.`));
        camerasLoadedForHost = null;
        return;
      }
      const captioning = cameras.filter((c) => c.captioning);
      if (!captioning.length) {
        cameraChecks.replaceChildren(el("span", "muted",
          "No camera on this host is currently captioning -- start a pipeline with captioning enabled first."));
        camerasLoadedForHost = host;
        return;
      }
      cameraChecks.replaceChildren();
      captioning.forEach((cam, i) => {
        const label = el("label");
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.name = "summary-camera";
        cb.value = cam.camera;
        cb.checked = true; // default: summarize every captioning camera found
        label.appendChild(cb);
        label.appendChild(document.createTextNode(` ${cam.title || cam.camera}`));
        cameraChecks.appendChild(label);
      });
      camerasLoadedForHost = host;
    } catch (err) {
      cameraChecks.replaceChildren(el("span", "muted", "Couldn't look up cameras for this host."));
      camerasLoadedForHost = null;
    }
  }

  function renderMessage(kind, title, detail) {
    const wrap = el("div", `summary-state summary-state-${kind}`);
    if (kind === "loading") wrap.appendChild(el("div", "spinner"));
    wrap.appendChild(el("div", "summary-state-title", title));
    if (detail) wrap.appendChild(el("div", "summary-state-detail muted", detail));
    body.replaceChildren(wrap);
  }

  function renderReport(report) {
    const wrap = el("div", "summary-report");

    const meta = el("div", "summary-meta muted",
      `${report.host} \u00b7 ${report.cameras.join(", ")} \u00b7 last ${report.window_minutes} min \u00b7 generated ${new Date(report.generated_at).toLocaleString()}`);
    wrap.appendChild(meta);

    wrap.appendChild(el("h3", "summary-section-title", "Overview"));
    wrap.appendChild(el("p", "summary-overview", report.overview));

    if (report.keywords && report.keywords.length) {
      const kwWrap = el("div", "summary-keywords");
      report.keywords.forEach((k) => kwWrap.appendChild(el("span", "summary-keyword", k)));
      wrap.appendChild(kwWrap);
    }

    wrap.appendChild(el("h3", "summary-section-title",
      `Timeline highlights (${report.highlights.length} of ${report.highlights_total_scenes} scenes)`));

    // Grouped by camera -- all of one camera's highlights, chronologically,
    // under its own subheading, then the next camera's -- rather than one
    // feed interleaved by arrival time across cameras (which reads as
    // "camera A, camera B, camera C, camera A, ..." when several cameras
    // are captioning at once, and is hard to follow).
    const groups = (report.highlights_by_camera || []).filter((g) => g.highlights && g.highlights.length);
    if (!groups.length) {
      wrap.appendChild(el("p", "muted", "No scene captions were available for this window."));
    } else {
      groups.forEach((group) => {
        wrap.appendChild(el("h4", "summary-camera-title", group.camera));
        const list = el("ul", "summary-highlights");
        group.highlights.forEach((h) => {
          const item = el("li", "summary-highlight");
          const when = new Date(h.start).toLocaleTimeString();
          const rep = h.occurrences > 1 ? ` (\u00d7${h.occurrences})` : "";
          item.appendChild(el("span", "summary-highlight-meta", `${when}${rep}`));
          item.appendChild(el("span", "summary-highlight-text", h.text));
          list.appendChild(item);
        });
        wrap.appendChild(list);
      });
    }

    const counts = el("div", "summary-device-breakdown muted");
    counts.textContent = Object.entries(report.camera_breakdown)
      .map(([camera, c]) => `${camera}: ${c.captions} caption(s), ${c.scenes} scene(s)`)
      .join(" \u00b7 ");
    wrap.appendChild(counts);

    body.replaceChildren(wrap);
  }

  function pdfUrl(host, cameras, windowMinutes, maxHighlights) {
    const params = new URLSearchParams({
      host,
      cameras: cameras.join(","),
      window_minutes: String(windowMinutes),
      max_highlights: String(maxHighlights),
    });
    return `/api/summary.pdf?${params.toString()}`;
  }

  async function generate() {
    const host = currentHost();
    const cameras = selectedCameras();
    const windowMinutes = Number(windowInput.value) || 15;
    const maxHighlights = Number(highlightsInput.value) || 20;

    downloadBtn.classList.add("hidden");

    if (!host) {
      renderMessage("error", "No UAV host set", "Connect to a UAV companion board first, or enter its IP above.");
      return;
    }
    if (!cameras.length) {
      renderMessage("error", "No camera selected", "Pick at least one camera that is currently captioning.");
      return;
    }

    renderMessage("loading", "Building summary\u2026");
    generateBtn.disabled = true;

    const controller = new AbortController();
    inFlight = controller;
    try {
      const res = await fetch("/api/summary", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          host,
          cameras,
          window_minutes: windowMinutes,
          max_highlights: maxHighlights,
        }),
        signal: controller.signal,
      });
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status}${detail ? `: ${detail}` : ""}`);
      }
      const report = await res.json();
      renderReport(report);
      downloadBtn.href = pdfUrl(host, cameras, windowMinutes, maxHighlights);
      downloadBtn.classList.remove("hidden");
    } catch (err) {
      if (err.name === "AbortError") return;
      renderMessage("error", "Couldn't build the summary",
        "Check that the host is reachable and at least one camera was started with captioning enabled.");
    } finally {
      if (inFlight === controller) inFlight = null;
      generateBtn.disabled = false;
    }
  }

  function open() {
    lastFocus = document.activeElement;
    if (!hostInput.value.trim()) {
      const main = document.getElementById("host-input");
      if (main && main.value.trim()) hostInput.value = main.value.trim();
    }
    modal.classList.remove("hidden");
    renderMessage("idle", "Build a flight summary", "Pick cameras and a time window, then Generate.");
    downloadBtn.classList.add("hidden");
    populateCameras(hostInput.value.trim());
    hostInput.focus();
  }

  function close() {
    if (inFlight) inFlight.abort();
    modal.classList.add("hidden");
    if (lastFocus) lastFocus.focus();
  }

  openBtn.addEventListener("click", open);
  closeBtn.addEventListener("click", close);
  modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.classList.contains("hidden")) close();
  });
  form.addEventListener("submit", (e) => { e.preventDefault(); generate(); });
  hostInput.addEventListener("change", () => populateCameras(hostInput.value.trim(), { force: true }));
  // If the main dashboard's connect/host context changes while this modal is
  // closed, drop the cached camera list so the next open re-fetches instead
  // of showing a stale/empty one for the new host.
  document.addEventListener("uav:connected", () => { camerasLoadedForHost = null; });
  document.addEventListener("uav:tab-switched", () => { camerasLoadedForHost = null; });
})();
