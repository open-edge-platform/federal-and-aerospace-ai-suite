// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

(() => {
  const hostInput = document.getElementById("host-input");
  const connectBtn = document.getElementById("connect-btn");
  const refreshBtn = document.getElementById("refresh-btn");
  const connStatus = document.getElementById("conn-status");
  const cardsContainer = document.getElementById("cards-container");

  let metricsSource = null;
  let localMetricsSource = null;
  let pipelinePollTimer = null;
  let currentHost = null;
  let isConnected = false; // true once at least one camera card is live
  let remoteHttpsPort = 443; // overwritten by /api/runtime-config
  let mediamtxWebrtcHost = "127.0.0.1"; // overwritten by /api/runtime-config
  let mediamtxWebrtcPort = 8889; // overwritten by /api/runtime-config

  // camera (RTSP stream path) -> { wrap, videoContainer, video, chipTtft, chipTpot, chipThroughput, chipLag,
  //             captionStatus, captionTimeline, captionHistory,
  //             lastCaptionReceivedAt, captionsSource, titleEl, metaEl }
  const cards = new Map();


  function setStatus(state) {
    connStatus.classList.remove("pill-off", "pill-on", "pill-pending");
    if (state === "connected") {
      connStatus.classList.add("pill-on");
      connStatus.textContent = "connected";
      isConnected = true;
      connectBtn.textContent = "Disconnect";
    } else if (state === "connecting") {
      connStatus.classList.add("pill-pending");
      connStatus.textContent = "connecting…";
    } else {
      connStatus.classList.add("pill-off");
      connStatus.textContent = "disconnected";
      isConnected = false;
      connectBtn.textContent = "Connect";
    }
  }

  function renderEmptyState(message) {
    cardsContainer.innerHTML = "";
    if (!message) return;
    const empty = document.createElement("div");
    empty.className = "cards-empty";
    empty.textContent = message;
    cardsContainer.appendChild(empty);
  }

  function clearEmptyState() {
    const empty = cardsContainer.querySelector(".cards-empty");
    if (empty) empty.remove();
  }

  // --- Caption formatting (mirrors live-video-captioning's run-card timeline) -
  const MAX_CAPTION_BUFFER = 20;
  const VISIBLE_CAPTION_LIMIT = MAX_CAPTION_BUFFER;

  function formatStreamSeconds(seconds) {
    if (!Number.isFinite(seconds)) return "—";
    const safeSeconds = Math.max(0, seconds);
    const minutes = Math.floor(safeSeconds / 60);
    const remaining = safeSeconds - minutes * 60;
    const secondsText = remaining.toFixed(2).padStart(5, "0");
    return `${String(minutes).padStart(2, "0")}:${secondsText}`;
  }

  function formatTimelinePositionLabel(index) {
    return index === 0 ? "Latest" : `latest -${index}`;
  }

  function formatCaptionTimestamp(data) {
    if (data && data.timestamp_seconds !== undefined) {
      return formatStreamSeconds(data.timestamp_seconds);
    }
    if (data && data.timestamp) {
      return `at ${new Date(data.timestamp).toLocaleTimeString()}`;
    }
    return `at ${new Date().toLocaleTimeString()}`;
  }

  function renderCaptionTimeline(card) {
    const entries = card.captionHistory.slice(0, VISIBLE_CAPTION_LIMIT);
    card.captionTimeline.innerHTML = "";
    if (entries.length === 0) {
      const empty = document.createElement("div");
      empty.className = "caption-entry caption-entry-placeholder";
      empty.textContent = "Waiting for captions…";
      card.captionTimeline.appendChild(empty);
      return;
    }
    entries.forEach((item, index) => {
      const row = document.createElement("article");
      row.className = "caption-entry";

      const meta = document.createElement("div");
      meta.className = "caption-entry-meta";
      meta.textContent = `${formatTimelinePositionLabel(index)} • ${item.timestampLabel}`;

      const text = document.createElement("p");
      text.className = "caption-entry-text";
      text.textContent = item.captionText;

      row.appendChild(meta);
      row.appendChild(text);
      card.captionTimeline.appendChild(row);
    });
  }

  function updateCaptionHistory(card, data, captionText) {
    card.captionHistory.unshift({
      captionText,
      timestampLabel: formatCaptionTimestamp(data),
    });
    if (card.captionHistory.length > MAX_CAPTION_BUFFER) {
      card.captionHistory.length = MAX_CAPTION_BUFFER;
    }
    renderCaptionTimeline(card);
  }

  // Update every card's lag chip every 100ms, same cadence as
  // live-video-captioning (it does the same thing across all its run cards).
  setInterval(() => {
    const now = Date.now();
    for (const card of cards.values()) {
      if (card.lastCaptionReceivedAt === null) continue;
      const lagSeconds = (now - card.lastCaptionReceivedAt) / 1000;
      card.chipLag.textContent = `${lagSeconds.toFixed(2)}s`;
    }
  }, 100);

  // --- Pipeline auto-detection -----------------------------------------------
  // Finds every camera (a RUNNING pipeline with an RTSP stream) on the host,
  // so the user never has to pick one manually, and so every camera gets its
  // own card.
  async function detectPipelines(host) {
    try {
      const res = await fetch(`/api/detect-pipelines?host=${encodeURIComponent(host)}`);
      return await res.json();
    } catch (err) {
      return { reachable: false, cameras: [] };
    }
  }

  async function loadRuntimeConfig() {
    try {
      const res = await fetch("/api/runtime-config");
      const cfg = await res.json();
      hostInput.value = cfg.defaultHost || "127.0.0.1";
      hostInput.placeholder = cfg.defaultHost || "127.0.0.1";
      if (cfg.remoteHttpsPort) remoteHttpsPort = cfg.remoteHttpsPort;
      if (cfg.mediamtxWebrtcHost) mediamtxWebrtcHost = cfg.mediamtxWebrtcHost;
      if (cfg.mediamtxWebrtcPort) mediamtxWebrtcPort = cfg.mediamtxWebrtcPort;
      return cfg;
    } catch (err) {
      hostInput.value = "127.0.0.1";
      return {};
    }
  }

  // --- Card creation/teardown ------------------------------------------------
  function createCard(cam) {
    const wrap = document.createElement("section");
    wrap.className = "device-card panel";

    const header = document.createElement("div");
    header.className = "device-card-header";
    const title = document.createElement("div");
    title.className = "device-card-title";
    const cameraName = document.createElement("span");
    cameraName.className = "camera-name";
    cameraName.textContent = cam.title || cam.camera;
    const badges = document.createElement("span");
    badges.className = "device-badges";
    title.appendChild(cameraName);
    title.appendChild(badges);
    const meta = document.createElement("div");
    meta.className = "device-card-meta";
    meta.textContent = "—";
    // Expands the live video to the whole screen (Esc returns). Fullscreens
    // our own container rather than relying on the remote viewer page's
    // controls.
    const expandBtn = document.createElement("button");
    expandBtn.type = "button";
    expandBtn.className = "btn btn-ghost btn-icon-only device-expand-btn";
    expandBtn.title = "Full screen";
    expandBtn.setAttribute("aria-label", `View ${cam.title || cam.camera} video full screen`);
    expandBtn.disabled = true;
    expandBtn.innerHTML = '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>';
    const headerRight = document.createElement("div");
    headerRight.className = "device-card-header-right";
    headerRight.appendChild(meta);
    headerRight.appendChild(expandBtn);
    header.appendChild(title);
    header.appendChild(headerRight);

    // Holds either an <iframe> (the local mediamtx's WHEP viewer for the
    // H.264 relay) or a placeholder <div> (no stream published) -- swapped
    // by syncVideoMode() below.
    const videoContainer = document.createElement("div");
    videoContainer.className = "device-video-container";
    // Enabled only while a live video iframe is mounted (not a placeholder).
    new MutationObserver(() => {
      expandBtn.disabled = !videoContainer.querySelector("iframe");
    }).observe(videoContainer, { childList: true });
    // videoContainer's children are replaced on every mode switch, so the
    // full-screen target is a stable wrapper that also holds the exit button.
    const videoStage = document.createElement("div");
    videoStage.className = "device-video-stage";
    const exitBtn = document.createElement("button");
    exitBtn.type = "button";
    exitBtn.className = "btn btn-ghost device-exit-fullscreen";
    exitBtn.textContent = `${cam.title || cam.camera} \u2022 Exit full screen (Esc)`;
    exitBtn.addEventListener("click", () => document.exitFullscreen().catch(() => {}));
    videoStage.appendChild(videoContainer);
    videoStage.appendChild(exitBtn);
    expandBtn.addEventListener("click", () => {
      if (videoStage.requestFullscreen) videoStage.requestFullscreen().catch(() => {});
    });

    const captionPanel = document.createElement("div");
    captionPanel.className = "caption-panel";
    const chipsRow = document.createElement("div");
    chipsRow.className = "chips-row";
    const chips = document.createElement("div");
    chips.className = "chips";

    function makeChip(label) {
      const chip = document.createElement("span");
      chip.className = "chip";
      const strong = document.createElement("strong");
      strong.textContent = label;
      const value = document.createElement("span");
      value.textContent = "—";
      chip.appendChild(strong);
      chip.appendChild(value);
      chips.appendChild(chip);
      return value;
    }

    const chipTtft = makeChip("TTFT");
    const chipTpot = makeChip("TPOT");
    const chipThroughput = makeChip("Throughput");
    const chipLag = makeChip("Lag");

    const captionStatus = document.createElement("div");
    captionStatus.className = "caption-status";
    captionStatus.textContent = "—";

    chipsRow.appendChild(chips);
    chipsRow.appendChild(captionStatus);

    const captionTimeline = document.createElement("div");
    captionTimeline.className = "caption-timeline";

    captionPanel.appendChild(chipsRow);
    captionPanel.appendChild(captionTimeline);

    wrap.appendChild(header);
    wrap.appendChild(videoStage);
    wrap.appendChild(captionPanel);

    const card = {
      camera: cam.camera,
      topic: null,
      captioning: false,
      captionPanel,
      badgesEl: badges,
      cameraNameEl: cameraName,
      wrap,
      titleEl: title,
      metaEl: meta,
      videoContainer,
      captionStatus,
      captionTimeline,
      chipTtft,
      chipTpot,
      chipThroughput,
      chipLag,
      captionHistory: [],
      lastCaptionReceivedAt: null,
      captionsSource: null,
    };
    renderCaptionTimeline(card);
    renderBadges(card, cam);
    return card;
  }

  // Devices of the camera's pipeline as badges: detection device, VLM device (when captioning) and
  // whether detections are drawn on the stream.
  function renderBadges(card, info) {
    card.badgesEl.innerHTML = "";
    const add = (text, cls, tip) => {
      const badge = document.createElement("span");
      badge.className = `device-badge ${cls}`;
      badge.textContent = text;
      if (tip) badge.title = tip;
      card.badgesEl.appendChild(badge);
    };
    if (info.detection_device) {
      add(info.detection_device.toUpperCase(), `device-badge-${info.detection_device}`,
        `Object detection on ${info.detection_device.toUpperCase()}${info.detection_model ? ` (${info.detection_model})` : ""}`);
    }
    if (info.captioning) {
      add(info.vlm_device ? `VLM ${info.vlm_device.toUpperCase()}` : "VLM", "device-badge-vlm",
        `Captions by ${info.vlm_model || "the VLM"}${info.vlm_device ? ` on ${info.vlm_device.toUpperCase()}` : ""}`);
    }
    if (info.device) add("LIVE", "device-badge-live", `Live camera ${info.device}${info.camera_size ? ` (${info.camera_size})` : ""}`);
    if (info.overlay === false) add("no overlay", "device-badge-off", "Detection boxes and telemetry text are not drawn on this stream");
  }

  // Shows the caption panel and listens to the camera's MQTT topic only while the pipeline captions.
  function applyCaptionState(host, card, topic) {
    card.topic = topic || null;
    card.captioning = !!topic;
    card.captionPanel.hidden = !card.captioning;
    if (card.captioning) {
      startCaptionsStream(host, card);
    } else if (card.captionsSource) {
      card.captionsSource.close();
      card.captionsSource = null;
    }
  }

  function teardownCard(card) {
    if (card.captionsSource) card.captionsSource.close();
    card.wrap.remove();
  }

  // --- Video modes -----------------------------------------------------
  // "H.264 Relay" is the only video path: whenever a remote pipeline is
  // publishing RTSP for this camera (see "rtsp_available"; uav-vision-analytics
  // publishes H.264), the local viz-backend configures a mediamtx sidecar
  // (docker-compose-mediamtx.yml, always brought up alongside this service
  // -- see `make up`) to pull that RTSP stream on demand and re-serve it as
  // WebRTC -- pure remux, no transcoding -- then this iframes mediamtx's
  // own WHEP viewer page.
  async function startH264RelayStream(host, card) {
    card.videoContainer.innerHTML = "";
    const loading = document.createElement("div");
    loading.className = "device-video-placeholder";
    loading.textContent = "Starting H.264 relay…";
    card.videoContainer.appendChild(loading);
    try {
      const res = await fetch(
        `/api/relay-path?host=${encodeURIComponent(host)}&camera=${encodeURIComponent(card.camera)}`,
        { method: "POST" },
      );
      if (!res.ok) throw new Error(`relay-path ${res.status}`);
      const { path } = await res.json();
      // Only swap the DOM in if this card is still in relay mode and
      // pointed at the same host -- avoids a slow response clobbering a
      // newer mode switch that happened while this fetch was in flight.
      if (card.activeVideoMode !== "relay" || card.relayHost !== host) return;
      card.videoContainer.innerHTML = "";
      const iframe = document.createElement("iframe");
      iframe.className = "device-video device-video-webrtc";
      iframe.allow = "autoplay; fullscreen";
      iframe.allowFullscreen = true;
      iframe.src = `http://${mediamtxWebrtcHost}:${mediamtxWebrtcPort}/${path}/`;
      card.videoContainer.appendChild(iframe);
      setStatus("connected");
    } catch (err) {
      card.videoContainer.innerHTML = "";
      const placeholder = document.createElement("div");
      placeholder.className = "device-video-placeholder";
      placeholder.textContent = "H.264 relay unavailable — is docker-compose-mediamtx.yml running?";
      card.videoContainer.appendChild(placeholder);
    }
  }

  function showNoStreamPlaceholder(card) {
    card.videoContainer.innerHTML = "";
    const placeholder = document.createElement("div");
    placeholder.className = "device-video-placeholder";
    placeholder.textContent = "No video stream — start this camera's pipeline on the remote host.";
    card.videoContainer.appendChild(placeholder);
  }

  // --- Pipeline/model info (shown compactly in the card header) ------------
  async function refreshPipelineInfo(host, card) {
    try {
      const res = await fetch(`/api/pipeline-info?host=${encodeURIComponent(host)}&camera=${encodeURIComponent(card.camera)}`);
      const info = await res.json();
      const state = info.reachable ? (info.state || "unknown") : "unreachable";
      const parts = [state];
      if (info.pipeline_name) parts.push(info.pipeline_name);
      // Header shows only state + pipeline; the rest stays available on hover.
      const details = [];
      if (info.detection_device) details.push(`detection ${info.detection_device.toUpperCase()}${info.detection_model ? ` ${info.detection_model}` : ""}`);
      details.push(info.captioning
        ? `captions ${info.vlm_device ? info.vlm_device.toUpperCase() + " " : ""}${info.vlm_model || ""}`.trim()
        : "captioning off");
      if (info.prompt) details.push(`prompt: ${info.prompt}`);
      details.push(info.overlay === false ? "overlay off" : "overlay on");
      if (info.video) details.push(`video ${info.video}`);
      if (info.device) details.push(`live camera ${info.device}${info.camera_size ? ` ${info.camera_size}` : ""}`);
      if (info.frame_rate !== null && info.frame_rate !== undefined) details.push(`${info.frame_rate} fps`);
      details.push(info.rtsp_available ? "H.264 Relay" : "no video stream");
      card.metaEl.textContent = parts.join(" • ");
      card.metaEl.title = [...parts, ...details].join(" • ");
      card.rtspPath = info.rtsp_path || card.camera;
      if (info.rtsp_available) {
        renderBadges(card, info);
        // The same stream path can be served by another pipeline after the configuration changed.
        const topic = info.captioning ? info.caption_topic : null;
        if (topic !== card.topic) applyCaptionState(host, card, topic);
      }
      syncVideoMode(host, card, info.rtsp_available);
    } catch (err) {
      card.metaEl.textContent = "error";
    }
  }

  // Starts/swaps the card's video element to match whether the remote
  // pipeline is publishing, without restarting anything that's already
  // active and still correct (avoids tearing down a working WebRTC session
  // on every 5s pipeline-info poll). Shows the H.264 Relay (local mediamtx
  // remux) when a stream is published, otherwise a placeholder.
  function syncVideoMode(host, card, streamAvailable) {
    const mode = streamAvailable ? "relay" : "none";
    if (card.activeVideoMode === mode && card.relayHost === host) return;
    card.activeVideoMode = mode;
    card.relayHost = host;

    if (mode === "relay") {
      startH264RelayStream(host, card);
    } else {
      showNoStreamPlaceholder(card);
    }
  }

  // --- Metrics (CPU/GPU/NPU via metrics-manager SSE proxy, host-level) -----
  ChartManager.createConsolidatedChart('statsChart', [
    { key: 'cpu', label: 'CPU %', color: '#1ad0ff' },
    { key: 'mem', label: 'RAM %', color: '#8ca0c2' },
    { key: 'npu', label: 'NPU %', color: '#b388ff' },
  ]);

  // --- Metrics (this ground-station machine's own gs-metrics-manager) -----
  // Independent of the remote "connect" lifecycle -- always shows how much
  // local compute is spent on H.264 Relay remuxing / WHEP viewing here.
  // Same image/metric set as the remote chart, so it reuses applyMetricsTo.
  const GroundStationChartManager = createChartManager();
  GroundStationChartManager.createConsolidatedChart('gsStatsChart', [
    { key: 'cpu', label: 'CPU %', color: '#1ad0ff' },
    { key: 'mem', label: 'RAM %', color: '#8ca0c2' },
    { key: 'npu', label: 'NPU %', color: '#b388ff' },
  ]);

  function startLocalMetricsStream() {
    if (localMetricsSource) return;
    localMetricsSource = new EventSource('/api/local-metrics-stream');
    localMetricsSource.onmessage = (evt) => {
      let payload;
      try {
        payload = JSON.parse(evt.data);
      } catch (err) {
        return;
      }
      applyMetricsTo(payload.metrics || [], GroundStationChartManager, 'gs');
    };
  }

  function startMetricsStream(host) {
    if (metricsSource) metricsSource.close();
    ChartManager.resetChart();
    metricsSource = new EventSource(`/api/metrics-stream?host=${encodeURIComponent(host)}`);
    metricsSource.onmessage = (evt) => {
      let payload;
      try {
        payload = JSON.parse(evt.data);
      } catch (err) {
        return;
      }
      applyMetricsTo(payload.metrics || [], ChartManager, '');
    };
  }

  function setHeaderValue(id, value) {
    const el = document.getElementById(id);
    if (!el || value === undefined || value === null || Number.isNaN(value)) return;
    el.textContent = `${Math.max(0, Math.min(100, value)).toFixed(0)}%`;
  }

  function resetMetricsHeader() {
    const cpuVal = document.getElementById("cpuVal");
    if (cpuVal) cpuVal.textContent = "—";
    const ramVal = document.getElementById("ramVal");
    if (ramVal) ramVal.textContent = "—";
    const npuVal = document.getElementById("npuVal");
    if (npuVal) npuVal.textContent = "—";
    const npuStat = document.getElementById("npuStat");
    if (npuStat) npuStat.style.display = "none";
    const gpuValues = document.getElementById("gpuValues");
    if (gpuValues) {
      gpuValues.innerHTML = "";
      gpuValues.style.display = "none";
    }
  }

  // Shared metrics-manager payload parser -- `idPrefix` picks which panel's
  // DOM ids to update ("" for the remote "UAV Companion Board" panel's
  // cpuVal/ramVal/npuVal/npuStat/gpuValues, "gs" for this ground station's
  // own gsCpuVal/gsRamVal/gsNpuVal/gsNpuStat/gsGpuValues).
  function applyMetricsTo(metrics, chartManager, idPrefix) {
    // "" (remote panel) uses lowerCamelCase ids (cpuVal, npuStat, ...);
    // "gs" (ground station panel) prefixes the capitalized suffix (gsCpuVal, gsNpuStat, ...).
    const id = (suffix) => (idPrefix ? `${idPrefix}${suffix}` : suffix.charAt(0).toLowerCase() + suffix.slice(1));
    const frameSamples = {};
    const gpuUsageByDevice = new Map();

    for (const m of metrics) {
      if (m.name === "cpu_usage_user") {
        frameSamples.cpu = m.value;
        setHeaderValue(id("CpuVal"), m.value);
      }
      if (m.name === "mem_used_percent") {
        frameSamples.mem = m.value;
        setHeaderValue(id("RamVal"), m.value);
      }
      if (m.name === "npu_utilization") {
        frameSamples.npu = m.value;
        setHeaderValue(id("NpuVal"), m.value);
        const npuStat = document.getElementById(id("NpuStat"));
        if (npuStat) npuStat.style.display = "";
      }
      if (m.name === "gpu_engine_usage_usage") {
        const gpuId = String((m.labels && m.labels.gpu_id) || "0");
        gpuUsageByDevice.set(gpuId, Math.max(gpuUsageByDevice.get(gpuId) || 0, m.value));
      }
    }

    if (gpuUsageByDevice.size > 0) {
      const gpuValues = document.getElementById(id("GpuValues"));
      if (gpuValues) gpuValues.innerHTML = "";
      Array.from(gpuUsageByDevice.entries())
        .sort(([a], [b]) => (Number(a) || 0) - (Number(b) || 0))
        .forEach(([gpuId, usage]) => {
          const key = `gpu:${gpuId}`;
          frameSamples[key] = usage;
          if (gpuValues) {
            const chip = document.createElement("span");
            chip.className = "gpu-value-chip";
            chip.style.color = chartManager.getSeriesColor(key);
            chip.textContent = `GPU-${gpuId} ${usage.toFixed(0)}%`;
            gpuValues.appendChild(chip);
          }
        });
      if (gpuValues) gpuValues.style.display = "";
    }

    if (Object.keys(frameSamples).length > 0) {
      chartManager.pushStatFrame(frameSamples);
    }
  }


  // --- Captions (MQTT bridged via SSE) --------------------------------------
  // Payload shape (from the gvagenai -> MQTTPublisher gvapython stage):
  //   { "metadata": { "result": "<caption text>", "timestamp_seconds": <float>,
  //                    "timestamp": <int ns>, "metrics": {...}, ... }, "blob": "" }
  function startCaptionsStream(host, card) {
    if (card.captionsSource) card.captionsSource.close();
    card.captionHistory = [];
    card.lastCaptionReceivedAt = null;
    renderCaptionTimeline(card);
    card.chipTtft.textContent = "—";
    card.chipTpot.textContent = "—";
    card.chipThroughput.textContent = "—";
    card.chipLag.textContent = "—";
    card.captionsSource = new EventSource(`/api/captions-stream?host=${encodeURIComponent(host)}&topic=${encodeURIComponent(card.topic)}`);
    card.captionsSource.onmessage = (evt) => {
      let payload;
      try {
        payload = JSON.parse(evt.data);
      } catch (err) {
        return;
      }
      const data = (payload && typeof payload === "object" && payload.metadata) ? payload.metadata : payload;
      const captionText = data && typeof data === "object" && data.result
        ? data.result
        : (typeof data === "string" ? data : JSON.stringify(data));
      updateCaptionHistory(card, data, captionText);

      const metrics = (data && typeof data === "object" && data.metrics) ? data.metrics : {};
      card.chipTtft.textContent = Number.isFinite(metrics.ttft_mean) ? `${metrics.ttft_mean.toFixed(0)} ms` : "—";
      card.chipTpot.textContent = Number.isFinite(metrics.tpot_mean) ? `${metrics.tpot_mean.toFixed(2)} ms` : "—";
      card.chipThroughput.textContent = Number.isFinite(metrics.throughput_mean) ? `${metrics.throughput_mean.toFixed(2)} tok/s` : "—";
      card.lastCaptionReceivedAt = Date.now();
      card.chipLag.textContent = "0.00s";

      card.captionStatus.textContent = data && data.timestamp_seconds !== undefined
        ? `Updated ${data.timestamp_seconds.toFixed(2)}s into stream`
        : data && data.timestamp
          ? `Updated at ${new Date(data.timestamp).toLocaleTimeString()}`
          : "—";
    };
    card.captionsSource.addEventListener("connected", () => {
      card.captionStatus.textContent = "Listening for captions…";
    });
  }

  function stopAllStreams() {
    if (metricsSource) { metricsSource.close(); metricsSource = null; }
    if (pipelinePollTimer) { clearInterval(pipelinePollTimer); pipelinePollTimer = null; }
    for (const card of cards.values()) teardownCard(card);
    cards.clear();
  }

  function connectCard(host, card, cam) {
    // Video is started by refreshPipelineInfo()'s syncVideoMode() once we
    // know whether a pipeline is publishing for this camera;
    // card.activeVideoMode starts unset so that first call always (re)starts
    // it.
    card.activeVideoMode = null;
    applyCaptionState(host, card, cam.captioning ? cam.mqtt_topic : null);
    refreshPipelineInfo(host, card);
  }

  // Reconciles the card grid against the currently-detected running cameras:
  //  - a camera that's newly running -> add a card, start its streams.
  //  - a camera that's no longer running -> remove its card, stop its streams.
  //  - a camera still running -> just refresh its pipeline-info text.
  // (Metrics are host-level, not camera-level, so they're left untouched.)
  function syncCards(host, detectedCameras) {
    const detectedSet = new Set(detectedCameras.map((c) => c.camera));

    for (const [camera, card] of Array.from(cards.entries())) {
      if (!detectedSet.has(camera)) {
        teardownCard(card);
        cards.delete(camera);
      } else {
        refreshPipelineInfo(host, card);
      }
    }

    // Insert new cards at their position in the backend's camera order, so a
    // camera whose pipeline starts late doesn't end up last.
    detectedCameras.forEach((cam, idx) => {
      if (!cards.has(cam.camera)) {
        clearEmptyState();
        const card = createCard(cam);
        const next = detectedCameras.slice(idx + 1).map((c) => cards.get(c.camera)).find(Boolean);
        cardsContainer.insertBefore(card.wrap, next ? next.wrap : null);
        cards.set(cam.camera, card);
        connectCard(host, card, cam);
      }
    });

    if (cards.size === 0) {
      renderEmptyState("No running pipeline detected on this host.");
      setStatus("off");
    } else {
      setStatus("connected");
    }
  }

  async function pollAndReconcile(host) {
    const detected = await detectPipelines(host);
    if (!detected.reachable) {
      // Host went unreachable -- leave existing cards as-is (video/caption
      // streams will show their own connection errors) rather than tearing
      // everything down on a possibly-transient network blip.
      return;
    }
    syncCards(host, detected.cameras || []);
  }

  async function connectNow() {
    const host = (hostInput.value || "127.0.0.1").trim();
    currentHost = host;
    stopAllStreams();
    setStatus("connecting");
    renderEmptyState("Detecting running pipelines…");
    startMetricsStream(host);

    const detected = await detectPipelines(host);
    if (!detected.reachable) {
      renderEmptyState("Host unreachable.");
      setStatus("off");
    } else {
      syncCards(host, detected.cameras || []);
    }
    pipelinePollTimer = setInterval(() => pollAndReconcile(host), 5000);
    // search.js registers this host's running pipelines for VSS live search.
    document.dispatchEvent(new CustomEvent("uav:connected", { detail: { host } }));
  }

  function disconnectNow() {
    stopAllStreams();
    ChartManager.resetChart();
    resetMetricsHeader();
    renderEmptyState(null);
    setStatus("off");
    document.dispatchEvent(new CustomEvent("uav:disconnected"));
  }

  connectBtn.addEventListener("click", () => {
    if (isConnected) {
      disconnectNow();
    } else {
      connectNow();
    }
  });

  refreshBtn.addEventListener("click", () => {
    if (!isConnected || !currentHost) return;
    pollAndReconcile(currentHost);
  });

  loadRuntimeConfig();
  startLocalMetricsStream();
})();
