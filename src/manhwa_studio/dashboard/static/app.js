// Manhwa Story Studio Pro - Frontend Dashboard Controller

let appState = {
  system: {},
  series: [],
  marathons: [],
  queue: { paused: false, wait_for_external: true, external_processes: [], jobs: [] },
};

let activeJobLogId = null;

function showToast(msg) {
  const container = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

function switchTab(tabId) {
  document.querySelectorAll(".tab-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === tabId);
  });
  document.querySelectorAll(".tab-panel").forEach((p) => {
    p.classList.toggle("active", p.id === tabId);
  });
  if (tabId === "tab-env") {
    loadGeminiKeysList();
  }
}

async function apiGet(url) {
  const res = await fetch(url, { cache: "no-store" });
  return await res.json();
}

async function apiPost(url, payload) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return await res.json();
}

async function refreshAll(manual = false) {
  try {
    const data = await apiGet("/api/state");
    appState = data;
    renderHeaderAndBanners();
    populateSeriesSelects();
    renderMatrixTable();
    renderMarathonsTab();
    renderInstagramExports();
    renderQueueTab();
    updateMarathonReadiness();
    if (activeJobLogId) {
      await pollActiveJobLogs(activeJobLogId);
    }
    if (manual) showToast("Workspace refreshed");
  } catch (err) {
    console.error("Failed to refresh dashboard state:", err);
  }
}

function renderHeaderAndBanners() {
  const sys = appState.system || {};
  const q = appState.queue || {};
  const ext = q.external_processes || [];
  const jobs = q.jobs || [];

  // Disk, GPU & Gemini
  document.getElementById("txt-disk").textContent = `Disk: ${sys.disk_free_gb ?? "--"} GB free`;
  const dotGpu = document.getElementById("dot-gpu");
  const txtGpu = document.getElementById("txt-gpu");
  if (dotGpu && txtGpu) {
    if (sys.gpu_nvenc_enabled) {
      dotGpu.className = "dot green";
      txtGpu.textContent = `GPU (${sys.video_encoder || "NVENC"})`;
    } else {
      dotGpu.className = "dot amber";
      txtGpu.textContent = "CPU (libx264)";
    }
  }
  const dotGem = document.getElementById("dot-gemini");
  const txtGem = document.getElementById("txt-gemini");
  if (sys.gemini_key_configured) {
    dotGem.className = "dot green";
    txtGem.textContent = "Gemini API Ready";
  } else {
    dotGem.className = "dot red";
    txtGem.textContent = "Gemini Key Missing";
  }

  // External Terminal Processes
  const dotExt = document.getElementById("dot-external");
  const txtExt = document.getElementById("txt-external");
  const banner = document.getElementById("external-banner");
  const extList = document.getElementById("external-list");

  if (ext.length > 0) {
    dotExt.className = "dot amber";
    txtExt.textContent = `${ext.length} Active Terminal Job${ext.length > 1 ? "s" : ""}`;
    banner.classList.add("active");
    extList.innerHTML = ext
      .map(
        (p) =>
          `<div class="ext-item">
            <span class="badge badge-running">PID ${p.pid} &bull; ${p.lane.toUpperCase()} LANE</span>
            <span>${escapeHtml(p.args_summary)}</span>
          </div>`
      )
      .join("");
  } else {
    dotExt.className = "dot green";
    txtExt.textContent = "0 External Terminal Jobs";
    banner.classList.remove("active");
    extList.innerHTML = "";
  }

  document.getElementById("chk-wait-external").checked = !!q.wait_for_external;

  // Queue Status Pill
  const runningCount = jobs.filter((j) => j.status === "running").length;
  const queuedCount = jobs.filter((j) => j.status === "queued").length;
  const dotQ = document.getElementById("dot-queue");
  const txtQ = document.getElementById("txt-queue");
  if (q.paused) {
    dotQ.className = "dot amber";
    txtQ.textContent = `Queue Paused (${queuedCount} waiting)`;
  } else if (runningCount > 0 || queuedCount > 0) {
    dotQ.className = "dot cyan";
    txtQ.textContent = `Queue: ${runningCount} running, ${queuedCount} waiting`;
  } else {
    dotQ.className = "dot green";
    txtQ.textContent = "Queue Idle";
  }

  document.getElementById("badge-series-count").textContent = (appState.series || []).length;
  document.getElementById("badge-marathon-count").textContent = (appState.marathons || []).length;
  document.getElementById("badge-queue-count").textContent = runningCount + queuedCount;
}

function populateSeriesSelects() {
  const seriesList = appState.series || [];
  const matrixSel = document.getElementById("matrix-series-select");
  const studioSel = document.getElementById("studio-series-select");

  const currentMatrixVal = matrixSel.value;
  const currentStudioVal = studioSel.value;

  const optsHtml = seriesList
    .map(
      (s) =>
        `<option value="${escapeHtml(s.series_slug)}">${escapeHtml(s.series_name)} (${s.total_chapters} ch)</option>`
    )
    .join("");

  if (matrixSel.innerHTML !== optsHtml) {
    matrixSel.innerHTML = optsHtml;
    if (currentMatrixVal && seriesList.some((s) => s.series_slug === currentMatrixVal)) {
      matrixSel.value = currentMatrixVal;
    }
  }

  if (studioSel.innerHTML !== optsHtml) {
    studioSel.innerHTML = optsHtml;
    if (currentStudioVal && seriesList.some((s) => s.series_slug === currentStudioVal)) {
      studioSel.value = currentStudioVal;
    }
    populateStudioChapters();
  }

  const socialSel = document.getElementById("social-series-select");
  if (socialSel) {
    const currentSocialVal = socialSel.value;
    if (socialSel.innerHTML !== optsHtml) {
      socialSel.innerHTML = optsHtml;
      if (currentSocialVal && seriesList.some((s) => s.series_slug === currentSocialVal)) {
        socialSel.value = currentSocialVal;
      }
      populateSocialChapters();
    }
  }

  const igSel = document.getElementById("ig-series-select");
  if (igSel) {
    const curIg = igSel.value;
    if (igSel.innerHTML !== optsHtml) {
      igSel.innerHTML = optsHtml;
      if (curIg && seriesList.some((s) => s.series_slug === curIg)) {
        igSel.value = curIg;
      }
    }
  }

  const ytBatchSel = document.getElementById("yt-batch-series");
  if (ytBatchSel) {
    const curYt = ytBatchSel.value;
    if (ytBatchSel.innerHTML !== optsHtml) {
      ytBatchSel.innerHTML = optsHtml;
      if (curYt && seriesList.some((s) => s.series_slug === curYt)) {
        ytBatchSel.value = curYt;
      }
    }
  }

  const ytShortsSel = document.getElementById("yt-shorts-series");
  if (ytShortsSel) {
    const curYs = ytShortsSel.value;
    if (ytShortsSel.innerHTML !== optsHtml) {
      ytShortsSel.innerHTML = optsHtml;
      if (curYs && seriesList.some((s) => s.series_slug === curYs)) {
        ytShortsSel.value = curYs;
      }
    }
  }

  const igMarathonSel = document.getElementById("ig-marathon-select");
  if (igMarathonSel) {
    const curM = igMarathonSel.value;
    const marathons = appState.marathons || [];
    const mHtml = marathons
      .map((m) => `<option value="${escapeHtml(m.path)}">${escapeHtml(m.filename)} (${m.size_mb} MB)</option>`)
      .join("");
    if (igMarathonSel.innerHTML !== mHtml) {
      igMarathonSel.innerHTML = mHtml;
      if (curM && marathons.some((m) => m.path === curM)) {
        igMarathonSel.value = curM;
      }
    }
  }

  const ytMarathonSel = document.getElementById("yt-marathon-select");
  if (ytMarathonSel) {
    const curYm = ytMarathonSel.value;
    const marathons = appState.marathons || [];
    const mHtml = marathons
      .map((m) => `<option value="${escapeHtml(m.path)}">${escapeHtml(m.filename)} (${m.size_mb} MB)</option>`)
      .join("");
    if (ytMarathonSel.innerHTML !== mHtml) {
      ytMarathonSel.innerHTML = mHtml;
      if (curYm && marathons.some((m) => m.path === curYm)) {
        ytMarathonSel.value = curYm;
      }
    }
  }

  loadSocialHandlesLocal();
}

function getSelectedSeriesObj() {
  const slug = document.getElementById("matrix-series-select").value;
  return (appState.series || []).find((s) => s.series_slug === slug) || (appState.series || [])[0];
}

function renderMatrixTable() {
  const sObj = getSelectedSeriesObj();
  const tbody = document.getElementById("matrix-tbody");
  if (!sObj) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;">No series found in workspace.</td></tr>`;
    return;
  }

  document.getElementById("stat-total-chapters").textContent = sObj.total_chapters;
  document.getElementById("stat-inbox-chapters").textContent = sObj.inbox_only_count;
  document.getElementById("stat-script-chapters").textContent = sObj.script_ready_count;
  document.getElementById("stat-rendered-chapters").textContent = sObj.rendered_count;

  const cleanBtn = document.getElementById("btn-clean-series-temp");
  if (cleanBtn) {
    const mb = sObj.reclaimable_temp_mb || 0;
    cleanBtn.textContent = mb > 0 ? `🧹 Clean Temp (${mb} MB)` : "🧹 Clean Temp (0 MB)";
  }

  const filterMode = document.getElementById("matrix-filter-select").value;
  let chapters = sObj.chapters || [];
  if (filterMode === "inbox") {
    chapters = chapters.filter((c) => c.overall_status === "inbox_only" || c.in_inbox);
  } else if (filterMode === "script_no_render") {
    chapters = chapters.filter((c) => c.has_script && (!c.rendered_variants || c.rendered_variants.length === 0));
  } else if (filterMode === "rendered") {
    chapters = chapters.filter((c) => c.rendered_variants && c.rendered_variants.length > 0);
  }

  if (chapters.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:var(--text-secondary);">No chapters match the current filter.</td></tr>`;
    return;
  }

  tbody.innerHTML = chapters
    .map((c) => {
      // Status badge
      let statusBadge = "";
      if (c.overall_status.startsWith("running:")) {
        statusBadge = `<span class="badge badge-running">&#9889; ${escapeHtml(c.overall_status.toUpperCase())}</span>`;
      } else if (c.overall_status === "rendered") {
        statusBadge = `<span class="badge badge-rendered">&#10003; Rendered</span>`;
      } else if (c.overall_status === "script_ready" || c.overall_status === "audio_ready") {
        statusBadge = `<span class="badge badge-script">&#128221; Script Ready</span>`;
      } else if (c.overall_status === "inbox_only") {
        statusBadge = `<span class="badge badge-inbox">&#128229; In Inbox</span>`;
      } else {
        statusBadge = `<span class="badge">${escapeHtml(c.overall_status)}</span>`;
      }

      if (c.in_inbox && c.overall_status !== "inbox_only") {
        statusBadge += ` <span class="badge badge-inbox" title="Raw files still in assets/inbox">Inbox</span>`;
      }

      // Speeds
      const speedsHtml =
        c.rendered_variants && c.rendered_variants.length > 0
          ? c.rendered_variants
              .map(
                (v) =>
                  `<button class="badge badge-speed" style="cursor:pointer;" onclick="openVideoModal('${escapeJs(
                    v.path
                  )}', '${escapeJs(sObj.series_name)} Ch.${c.chapter} (${v.speed})')">&#9654; ${v.speed} (${
                    v.size_mb
                  }MB)</button>`
              )
              .join(" ")
          : `<span style="color:var(--text-muted); font-size:12px;">—</span>`;

      // Assets
      const thumbBtn = c.thumbnail_path
        ? `<button class="btn btn-sm" onclick="inspectChapterInStudio('${escapeJs(sObj.series_slug)}', ${c.chapter})">&#128444; Thumb</button>`
        : "";
      const kitBtn = c.youtube_kit_path
        ? `<button class="btn btn-sm" onclick="inspectChapterInStudio('${escapeJs(sObj.series_slug)}', ${c.chapter})">&#128196; YT Kit</button>`
        : "";

      // Quick Actions
      let actionsHtml = "";
      if (c.overall_status === "inbox_only") {
        const folderParts = (c.inbox_info?.folder_path || "").split(/[/\\]/).filter(Boolean);
        const inboxDir = folderParts.length >= 3 ? folderParts.slice(0, 3).join("/") : "";
        actionsHtml = `
          <button class="btn btn-sm btn-cyan" onclick="queueSingleInbox('${escapeJs(
            sObj.series_name
          )}', ${c.chapter}, '${escapeJs(inboxDir)}')">Process Inbox</button>
          <button class="btn btn-sm btn-primary" onclick="openGeminiProImporterForChapter('${escapeJs(
            sObj.series_slug
          )}', '${escapeJs(sObj.series_name)}', ${c.chapter})" title="Write script free using your Gemini AI Pro web chat">&#10024; Gemini Pro (Free)</button>
        `;
      } else {
        actionsHtml = `
          <button class="btn btn-sm btn-emerald" onclick="queueSingleProRender('${escapeJs(
            sObj.series_slug
          )}', '${escapeJs(sObj.series_name)}', ${c.chapter}, 1.25, 'local')" title="Render on Local PC GPU (1 job at a time)">&#128421; Local 1.25x</button>
          <button class="btn btn-sm btn-primary" onclick="queueSingleProRender('${escapeJs(
            sObj.series_slug
          )}', '${escapeJs(sObj.series_name)}', ${c.chapter}, 1.25, 'cloud')" title="Offload render to Colab T4 Cloud GPU (1 job at a time)">&#9729; Cloud 1.25x</button>
          <button class="btn btn-sm" onclick="inspectChapterInStudio('${escapeJs(sObj.series_slug)}', ${
          c.chapter
        })">Studio</button>
          <button class="btn btn-sm btn-cyan" onclick="openChapterInSocialStudio('${escapeJs(sObj.series_slug)}', ${
          c.chapter
        })" title="Create YouTube Community Post & Instagram Reel/Carousel">&#128241; Social</button>
        `;
      }

      const durMin = c.estimated_duration_sec
        ? `${Math.floor(c.estimated_duration_sec / 60)}m ${Math.round(c.estimated_duration_sec % 60)}s`
        : "—";

      return `
        <tr>
          <td><strong>Ch.${c.chapter}</strong></td>
          <td>${escapeHtml(c.title)}</td>
          <td>${statusBadge}</td>
          <td>${c.artwork_count} panels / ${c.scene_count} scenes</td>
          <td>${durMin}</td>
          <td>${speedsHtml}</td>
          <td>${thumbBtn} ${kitBtn}</td>
          <td><div style="display:flex; gap:6px; flex-wrap:wrap;">${actionsHtml}</div></td>
        </tr>
      `;
    })
    .join("");
}

// Quick Fill Helpers from Matrix Tab
function quickFillInboxForSeries() {
  const sObj = getSelectedSeriesObj();
  if (!sObj) return;
  const inboxChs = (sObj.chapters || []).filter((c) => c.overall_status === "inbox_only").map((c) => c.chapter);
  document.getElementById("pi-series").value = sObj.series_name;
  document.getElementById("pi-inbox").value = `assets/inbox/${sObj.series_name}`;
  if (inboxChs.length > 0) {
    document.getElementById("pi-start").value = Math.min(...inboxChs);
    document.getElementById("pi-end").value = Math.max(...inboxChs);
  }
  updateInboxPreview();
  switchTab("tab-builder");
}

function quickFillRenderMissing() {
  const sObj = getSelectedSeriesObj();
  if (!sObj) return;
  const unrendered = (sObj.chapters || [])
    .filter((c) => c.has_script && (!c.rendered_variants || c.rendered_variants.length === 0))
    .map((c) => c.chapter);
  document.getElementById("pr-series").value = sObj.series_slug;
  if (unrendered.length > 0) {
    document.getElementById("pr-start").value = Math.min(...unrendered);
    document.getElementById("pr-end").value = Math.max(...unrendered);
  }
  updateProRenderPreview();
  switchTab("tab-builder");
}

function quickFillMarathonForSeries() {
  const sObj = getSelectedSeriesObj();
  if (!sObj) return;
  document.getElementById("ma-series").value = sObj.series_name;
  const rendered = (sObj.chapters || []).filter((c) => c.rendered_variants && c.rendered_variants.length > 0);
  if (rendered.length > 0) {
    const nums = rendered.map((c) => c.chapter);
    document.getElementById("ma-start").value = Math.min(...nums);
    document.getElementById("ma-end").value = Math.max(...nums);
    updateMarathonRangeHelper();
  }
  switchTab("tab-builder");
}

// Command Preview Updaters
function updateInboxPreview() {
  const series = document.getElementById("pi-series").value.trim();
  const inbox = document.getElementById("pi-inbox").value.trim();
  const start = document.getElementById("pi-start").value;
  const end = document.getElementById("pi-end").value;
  const approve = document.getElementById("pi-approve").checked;

  let cmd = `.\\.venv\\Scripts\\python -m manhwa_studio.cli process-inbox --inbox "${inbox}" --series "${series}" --chapter-start ${start} --chapter-end ${end}`;
  if (approve) cmd += " --auto-approve";
  document.getElementById("pi-cmd-preview").textContent = cmd;
}

function updateProRenderPreview() {
  const series = document.getElementById("pr-series").value.trim();
  const speed = document.getElementById("pr-speed").value;
  const start = document.getElementById("pr-start").value;
  const end = document.getElementById("pr-end").value;
  const burn = document.getElementById("pr-burn-subs").checked;
  const caps = document.getElementById("pr-thumb-caps").checked;
  const cold = document.getElementById("pr-cold-open").checked;
  const rebuild = document.getElementById("pr-rebuild").checked;

  let cmd = `.\\.venv\\Scripts\\python -m manhwa_studio.cli pro-render-range --series ${series} --chapter-start ${start} --chapter-end ${end} --speed ${speed}`;
  if (burn) cmd += " --burn-subtitles";
  if (caps) cmd += " --thumbnail-captions";
  if (cold) cmd += " --cold-open";
  if (rebuild) cmd += " --rebuild-segments";
  document.getElementById("pr-cmd-preview").textContent = cmd;
}

function updateMarathonRangeHelper() {
  const start = parseInt(document.getElementById("ma-start").value || "1", 10);
  const end = parseInt(document.getElementById("ma-end").value || "1", 10);
  const series = document.getElementById("ma-series").value.trim();
  const speed = document.getElementById("ma-speed").value;
  const slug = series.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");

  if (end >= start && end - start <= 100) {
    const list = [];
    for (let i = start; i <= end; i++) list.push(i);
    document.getElementById("ma-chapters").value = list.join(",");
    const spSuffix = speed !== "1.0" ? `_${speed}x` : "";
    document.getElementById("ma-output").value = `exports/marathons/${slug}_ch${start}_to_ch${end}_movie${spSuffix}.mp4`;
  }
  updateMarathonPreview();
}

function updateMarathonPreview() {
  const series = document.getElementById("ma-series").value.trim();
  const chapters = document.getElementById("ma-chapters").value.trim();
  const speed = document.getElementById("ma-speed").value;
  const output = document.getElementById("ma-output").value.trim();

  let cmd = `.\\.venv\\Scripts\\python -m manhwa_studio.cli marathon --series "${series}" --chapters "${chapters}"`;
  if (speed !== "1.0") cmd += ` --speed ${speed}`;
  if (output) cmd += ` -o ${output}`;
  document.getElementById("ma-cmd-preview").textContent = cmd;
  updateMarathonReadiness();
}

function updateMarathonReadiness() {
  const box = document.getElementById("ma-readiness-box");
  if (!box) return;
  const seriesName = document.getElementById("ma-series").value.trim().toLowerCase();
  const speedTag = `${parseFloat(document.getElementById("ma-speed").value)}x`;
  const chNums = document
    .getElementById("ma-chapters")
    .value.split(",")
    .map((x) => parseInt(x.trim(), 10))
    .filter((x) => !isNaN(x));

  const sObj = (appState.series || []).find(
    (s) => s.series_name.toLowerCase() === seriesName || s.series_slug === seriesName.replace(/\s+/g, "_")
  );
  if (!sObj || chNums.length === 0) {
    box.innerHTML = "";
    return;
  }

  const missing = [];
  for (const num of chNums) {
    const ch = (sObj.chapters || []).find((c) => c.chapter === num);
    if (!ch || !(ch.speeds_available || []).includes(speedTag)) {
      missing.push(num);
    }
  }

  if (missing.length === 0) {
    box.innerHTML = `<span style="color:var(--accent-emerald);">&#10003; All ${chNums.length} chapters have rendered ${speedTag} videos ready!</span>`;
  } else {
    box.innerHTML = `<span style="color:var(--accent-amber);">&#9888; Missing ${speedTag} renders for chapters: ${missing.join(
      ", "
    )} (Render them first or queue a chain).</span>`;
  }
}

function updateSpeedVideoPreview() {
  const inp = document.getElementById("sv-input").value.trim() || "<input.mp4>";
  const speed = document.getElementById("sv-speed").value;
  const out = document.getElementById("sv-output").value.trim();
  let cmd = `.\\.venv\\Scripts\\python -m manhwa_studio.cli speed-video --input "${inp}" --speed ${speed}`;
  if (out) cmd += ` --output "${out}"`;
  document.getElementById("sv-cmd-preview").textContent = cmd;
}

// Job Queue Submissions
async function enqueueInboxJob() {
  const payload = {
    action: "process-inbox",
    series_name: document.getElementById("pi-series").value.trim(),
    inbox_path: document.getElementById("pi-inbox").value.trim(),
    chapter_start: parseInt(document.getElementById("pi-start").value, 10),
    chapter_end: parseInt(document.getElementById("pi-end").value, 10),
    auto_approve: document.getElementById("pi-approve").checked,
  };
  const res = await apiPost("/api/jobs/enqueue", payload);
  if (res.ok) {
    showToast("Queued Inbox Processing job!");
    await refreshAll();
    switchTab("tab-queue");
  }
}

async function enqueueProRenderRangeJob() {
  const gpuEl = document.getElementById("pr-gpu-target");
  const gpuTarget = gpuEl ? gpuEl.value : "local";
  const payload = {
    action: "pro-render-range",
    series_slug: document.getElementById("pr-series").value.trim(),
    series_name: document.getElementById("pr-series").value.trim(),
    chapter_start: parseInt(document.getElementById("pr-start").value, 10),
    chapter_end: parseInt(document.getElementById("pr-end").value, 10),
    speed: parseFloat(document.getElementById("pr-speed").value),
    burn_subtitles: document.getElementById("pr-burn-subs").checked,
    thumbnail_captions: document.getElementById("pr-thumb-caps").checked,
    cold_open: document.getElementById("pr-cold-open").checked,
    rebuild_segments: document.getElementById("pr-rebuild").checked,
    gpu_target: gpuTarget,
  };
  const res = await apiPost("/api/jobs/enqueue", payload);
  if (res.ok) {
    const label = gpuTarget === "auto_split" ? "Both GPUs Parallel" : gpuTarget === "cloud" ? "Cloud T4 GPU" : "Local GPU";
    showToast(`Queued Pro Render Range on ${label}!`);
    await refreshAll();
    switchTab("tab-queue");
  }
}

async function enqueueFullPipelineChain() {
  const jobs = [
    {
      action: "process-inbox",
      series_name: document.getElementById("pi-series").value.trim(),
      inbox_path: document.getElementById("pi-inbox").value.trim(),
      chapter_start: parseInt(document.getElementById("pr-start").value, 10),
      chapter_end: parseInt(document.getElementById("pr-end").value, 10),
      auto_approve: true,
    },
    {
      action: "pro-render-range",
      series_slug: document.getElementById("pr-series").value.trim(),
      series_name: document.getElementById("pi-series").value.trim(),
      chapter_start: parseInt(document.getElementById("pr-start").value, 10),
      chapter_end: parseInt(document.getElementById("pr-end").value, 10),
      speed: parseFloat(document.getElementById("pr-speed").value),
      burn_subtitles: document.getElementById("pr-burn-subs").checked,
      thumbnail_captions: document.getElementById("pr-thumb-caps").checked,
      cold_open: document.getElementById("pr-cold-open").checked,
      rebuild_segments: document.getElementById("pr-rebuild").checked,
    },
  ];
  const res = await apiPost("/api/jobs/enqueue", { jobs });
  if (res.ok) {
    showToast("Chained Inbox + Pro Render Range in Queue!");
    await refreshAll();
    switchTab("tab-queue");
  }
}

async function enqueueFullArcAutopilot() {
  const seriesName = document.getElementById("pi-series").value.trim();
  const seriesSlug = document.getElementById("pr-series").value.trim();
  const start = parseInt(document.getElementById("pr-start").value, 10);
  const end = parseInt(document.getElementById("pr-end").value, 10);
  const speed = parseFloat(document.getElementById("pr-speed").value);

  const chList = [];
  for (let i = start; i <= end; i++) chList.push(i);
  const spSuffix = speed !== 1.0 ? `_${speed}x` : "";
  const outMarathon = `exports/marathons/${seriesSlug}_ch${start}_to_ch${end}_movie${spSuffix}.mp4`;

  const jobs = [
    {
      action: "process-inbox",
      series_name: seriesName,
      inbox_path: document.getElementById("pi-inbox").value.trim(),
      chapter_start: start,
      chapter_end: end,
      auto_approve: true,
    },
    {
      action: "pro-render-range",
      series_slug: seriesSlug,
      series_name: seriesName,
      chapter_start: start,
      chapter_end: end,
      speed: speed,
      burn_subtitles: document.getElementById("pr-burn-subs").checked,
      thumbnail_captions: document.getElementById("pr-thumb-caps").checked,
      cold_open: document.getElementById("pr-cold-open").checked,
      rebuild_segments: document.getElementById("pr-rebuild").checked,
    },
    {
      action: "marathon",
      series_name: seriesName,
      chapters: chList.join(","),
      speed: speed,
      output_path: outMarathon,
    },
  ];

  const res = await apiPost("/api/jobs/enqueue", { jobs });
  if (res.ok) {
    showToast(`3-Step Autopilot Queued (Ch.${start}–${end} → Marathon ${speed}x)!`);
    await refreshAll();
    switchTab("tab-queue");
  }
}

async function cleanTempSegmentsForSeries(allSeries = false) {
  const sObj = getSelectedSeriesObj();
  const payload = allSeries || !sObj ? {} : { series_slug: sObj.series_slug };
  const res = await apiPost("/api/clean-temp-segments", payload);
  if (res.ok) {
    showToast(`Cleaned ${res.cleaned_chapters} chapters (Freed ${res.freed_mb} MB)!`);
    await refreshAll();
  }
}

async function modernizeAllUnrenderedForSeries(mode = "rewrite") {
  const sObj = getSelectedSeriesObj();
  if (!sObj) return;
  const res = await apiPost("/api/jobs/enqueue", {
    action: "modernize-scripts",
    series_slug: sObj.series_slug,
    series_name: sObj.series_name,
    mode: mode,
  });
  if (res.ok) {
    showToast(`Queued Hinglish Script Upgrade (${mode}) for all unrendered chapters in ${sObj.series_name}!`);
    await refreshAll();
    switchTab("tab-queue");
  }
}

async function modernizeCurrentStudioChapter(mode = "rewrite") {
  const slug = document.getElementById("studio-series-select")?.value;
  const ch = parseInt(document.getElementById("studio-chapter-select")?.value || "1", 10);
  if (!slug || isNaN(ch)) return;
  const res = await apiPost("/api/jobs/enqueue", {
    action: "modernize-scripts",
    series_slug: slug,
    series_name: slug,
    chapter: ch,
    mode: mode,
  });
  if (res.ok) {
    showToast(`Queued Hinglish Script Upgrade (${mode}) for ${slug} Ch.${ch}!`);
    await refreshAll();
    switchTab("tab-queue");
  }
}

async function enqueueMarathonJob() {
  const payload = {
    action: "marathon",
    series_name: document.getElementById("ma-series").value.trim(),
    chapters: document.getElementById("ma-chapters").value.trim(),
    speed: parseFloat(document.getElementById("ma-speed").value),
    output_path: document.getElementById("ma-output").value.trim(),
  };
  const res = await apiPost("/api/jobs/enqueue", payload);
  if (res.ok) {
    showToast("Queued Marathon Compilation!");
    await refreshAll();
    switchTab("tab-queue");
  }
}

async function enqueueSpeedVideoJob() {
  const inp = document.getElementById("sv-input").value.trim();
  if (!inp) {
    showToast("Please provide an input MP4 path");
    return;
  }
  const payload = {
    action: "speed-video",
    input_video: inp,
    speed: parseFloat(document.getElementById("sv-speed").value),
    output_video: document.getElementById("sv-output").value.trim(),
  };
  const res = await apiPost("/api/jobs/enqueue", payload);
  if (res.ok) {
    showToast("Queued Video Speed Conversion!");
    await refreshAll();
    switchTab("tab-queue");
  }
}

async function queueSingleInbox(seriesName, chapter, inboxPath) {
  const res = await apiPost("/api/jobs/enqueue", {
    action: "process-inbox",
    series_name: seriesName,
    inbox_path: inboxPath || `assets/inbox/${seriesName}`,
    chapter: chapter,
    auto_approve: true,
  });
  if (res.ok) {
    showToast(`Queued Inbox Processing for ${seriesName} Ch.${chapter}`);
    await refreshAll();
  }
}

async function queueSingleProRender(seriesSlug, seriesName, chapter, speed, gpuTarget = "local") {
  const res = await apiPost("/api/jobs/enqueue", {
    action: "pro-render",
    series_slug: seriesSlug,
    series_name: seriesName,
    chapter: chapter,
    speed: speed,
    gpu_target: gpuTarget,
  });
  if (res.ok) {
    const gpuLabel = gpuTarget === "cloud" ? "☁️ Cloud T4" : "🖥️ Local GPU";
    showToast(`Queued ${gpuLabel} Render (${speed}x) for ${seriesName} Ch.${chapter}`);
    await refreshAll();
  }
}

// =========================================================================
// Cloud GPU (Colab T4) Connection & Live Limit Monitor
// =========================================================================

function toggleCloudGpuPanel() {
  const panel = document.getElementById("cloud-gpu-panel");
  if (!panel) return;
  const open = panel.style.display === "none" || !panel.style.display;
  panel.style.display = open ? "block" : "none";
  if (open) {
    refreshCloudGpuStatus(false);
  }
}

async function saveCloudGpuConfig() {
  const url = (document.getElementById("cloud-gpu-url")?.value || "").trim();
  const token = (document.getElementById("cloud-gpu-token")?.value || "").trim();
  const res = await apiPost("/api/cloud-gpu/config", { url, token });
  if (res && res.ok) {
    renderCloudGpuStatus(res);
    showToast(res.connected ? `Connected to Cloud GPU: ${res.gpu_name}` : "Saved Cloud URL (worker currently offline)");
  }
}

async function refreshCloudGpuStatus(showFeedback = false) {
  try {
    const resp = await fetch("/api/cloud-gpu/status");
    const data = await resp.json();
    renderCloudGpuStatus(data);
    if (showFeedback) {
      showToast(data.connected ? `Cloud GPU OK (${data.gpu_name})` : (data.error || "Cloud GPU offline"));
    }
  } catch (e) {
    // Ignore transient local polling errors
  }
}

function renderCloudGpuStatus(data) {
  const dot = document.getElementById("dot-cloud-gpu");
  const txt = document.getElementById("txt-cloud-gpu");
  const tel = document.getElementById("cloud-gpu-telemetry");
  const warnBox = document.getElementById("cloud-gpu-warnings");
  const urlInput = document.getElementById("cloud-gpu-url");
  if (urlInput && data.url && !urlInput.value) {
    urlInput.value = data.url;
  }
  if (!dot || !txt) return;

  if (!data.configured) {
    dot.className = "dot";
    txt.textContent = "Cloud GPU: Off";
    if (warnBox) warnBox.style.display = "none";
    return;
  }

  if (data.connected) {
    const warns = Array.isArray(data.warnings) ? data.warnings : [];
    dot.className = warns.length > 0 ? "dot yellow" : "dot green";
    const stateLabel = data.busy ? "Busy (1/1)" : "Ready";
    txt.textContent = `Cloud ${data.gpu_name || "GPU"}: ${stateLabel}`;
    if (tel) {
      const vram = `${data.vram_used_mb || 0}/${data.vram_total_mb || 0} MB`;
      const upH = ((data.uptime_minutes || 0) / 60).toFixed(1);
      tel.innerHTML = `<span style="color:#4ade80;">&#9679; Connected</span> &bull; <strong>${escapeHtml(data.gpu_name || "GPU")}</strong> &bull; VRAM: ${vram} (${data.gpu_util_pct || 0}%) &bull; Disk Free: <strong>${data.disk_free_gb || 0} GB</strong> &bull; Uptime: ${upH}h &bull; Completed: ${data.jobs_completed || 0}`;
    }
    if (warnBox) {
      if (warns.length > 0) {
        warnBox.style.display = "block";
        warnBox.innerHTML = "<strong>&#9888; Colab Limit Warning:</strong> " + warns.map(escapeHtml).join(" | ");
      } else {
        warnBox.style.display = "none";
      }
    }
  } else {
    dot.className = data.limit_alert ? "dot red" : "dot";
    txt.textContent = data.limit_alert ? "Cloud GPU: LIMIT/OFFLINE" : "Cloud GPU: Offline";
    if (tel) {
      tel.innerHTML = `<span style="color:#f87171;">&#9679; Disconnected</span> — ${escapeHtml(data.error || "Check Colab session")}`;
    }
    if (warnBox) {
      if (data.limit_alert) {
        warnBox.style.display = "block";
        warnBox.innerHTML = `<strong>&#9888; Action Needed:</strong> ${escapeHtml(data.error || "Colab runtime stopped — reconnect or reset runtime in Colab.")}`;
      } else {
        warnBox.style.display = "none";
      }
    }
  }
}

// Auto-poll Cloud GPU telemetry every 25s (only triggers network call if configured)
setInterval(() => refreshCloudGpuStatus(false), 25000);
setTimeout(() => refreshCloudGpuStatus(false), 1500);

// Marathons Tab
function renderMarathonsTab() {
  const container = document.getElementById("marathons-list-container");
  const marathons = appState.marathons || [];
  if (marathons.length === 0) {
    container.innerHTML = `<p style="color:var(--text-secondary); font-size:13px;">No compiled marathon movies found in exports/marathons/ yet.</p>`;
    return;
  }

  container.innerHTML = marathons
    .map(
      (m, idx) => `
      <div class="stat-box" style="margin-bottom:12px;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px;">
          <div>
            <strong style="font-size:14px; color:var(--accent-cyan);">${escapeHtml(m.filename)}</strong>
            <span class="badge badge-rendered" style="margin-left:8px;">${m.size_mb} MB</span>
            <div style="font-size:12px; color:var(--text-secondary); margin-top:2px;">Path: ${escapeHtml(m.path)}</div>
          </div>
          <div style="display:flex; gap:8px; flex-wrap:wrap;">
            <button class="btn btn-sm btn-primary" onclick="openVideoModal('${escapeJs(m.path)}', '${escapeJs(
        m.filename
      )}')">&#9654; Watch Marathon</button>
            <button class="btn btn-sm btn-cyan" onclick="openMarathonInInstagramExporter('${escapeJs(m.path)}')">&#128247; Split for Instagram (9:16)</button>
            <button class="btn btn-sm" onclick="openWorkspaceFolder('${escapeJs(m.path)}')">&#128193; Show in Explorer</button>
          </div>
        </div>
        ${
          m.timestamps_text
            ? `<details style="margin-top:10px;">
                <summary style="cursor:pointer; font-size:12px; color:var(--text-secondary);">YouTube Description &amp; Timestamps</summary>
                <pre class="cmd-preview" id="marathon-ts-${idx}" style="white-space:pre-wrap; margin-top:6px;">${escapeHtml(
                m.timestamps_text
              )}</pre>
                <button class="btn btn-sm" onclick="copyText('marathon-ts-${idx}')">Copy Timestamps</button>
              </details>`
            : ""
        }
      </div>
    `
    )
    .join("");
}

// Scene & Thumbnail Studio Tab
function populateStudioChapters() {
  const slug = document.getElementById("studio-series-select").value;
  const sObj = (appState.series || []).find((s) => s.series_slug === slug);
  const chSel = document.getElementById("studio-chapter-select");
  if (!sObj) {
    chSel.innerHTML = "";
    return;
  }
  const projectChs = (sObj.chapters || []).filter((c) => c.project_path);
  chSel.innerHTML = projectChs
    .map((c) => `<option value="${c.chapter}">Ch.${c.chapter} — ${escapeHtml(c.title)}</option>`)
    .join("");
  if (projectChs.length > 0) {
    loadStudioChapter();
  }
}

async function inspectChapterInStudio(seriesSlug, chapter) {
  switchTab("tab-studio");
  const sSel = document.getElementById("studio-series-select");
  sSel.value = seriesSlug;
  populateStudioChapters();
  const cSel = document.getElementById("studio-chapter-select");
  cSel.value = String(chapter);
  await loadStudioChapter();
}

async function loadStudioChapter() {
  const slug = document.getElementById("studio-series-select").value;
  const ch = document.getElementById("studio-chapter-select").value;
  if (!slug || !ch) return;

  try {
    const detail = await apiGet(`/api/chapter-detail?series=${encodeURIComponent(slug)}&chapter=${ch}`);
    // Thumbnail preview
    const thumbBox = document.getElementById("studio-thumb-preview");
    if (detail.thumbnail_path) {
      thumbBox.innerHTML = `<img src="/api/media?path=${encodeURIComponent(
        detail.thumbnail_path
      )}&t=${Date.now()}" style="max-width:100%; max-height:280px; object-fit:contain;" />`;
    } else {
      thumbBox.innerHTML = `<span style="color:var(--text-muted); font-size:13px;">No thumbnail generated yet</span>`;
    }

    // YouTube kit
    document.getElementById("studio-yt-kit-box").value = detail.youtube_kit_text || "No YouTube upload kit generated yet.";

    // Scenes
    const scenes = detail.scenes || [];
    document.getElementById("studio-scene-count").textContent = scenes.length;
    const grid = document.getElementById("studio-scene-grid");

    if (scenes.length === 0) {
      grid.innerHTML = `<p style="color:var(--text-secondary); font-size:13px;">No scene_manifest.json scenes found for this chapter.</p>`;
      return;
    }

    grid.innerHTML = scenes
      .map((s) => {
        const imgRel = `${detail.project_path}/artwork/${s.image_file}`;
        const hasSceneAudio = !!s.actual_audio_path;
        const sceneMp3Rel = `${detail.project_path}/audio/${s.scene_id}.mp3`;
        return `
          <div class="scene-card" data-scene-id="${escapeHtml(s.scene_id)}">
            <img src="/api/media?path=${encodeURIComponent(imgRel)}" loading="lazy" alt="${escapeHtml(
          s.scene_id
        )}" onclick="selectSceneForThumbnail('${escapeJs(s.scene_id)}', '${escapeJs(
          s.image_file
        )}', '${escapeJs(s.narration_text || "")}')" title="Click image to set as Thumbnail scene" />
            <div class="scene-card-body">
              <div>
                <div style="display:flex; justify-content:space-between; align-items:center; gap:6px; margin-bottom:6px;">
                  <strong style="color:var(--accent-cyan);">${escapeHtml(s.scene_id)}</strong>
                  <input type="text" class="scene-speaker-input" value="${escapeHtml(
                    s.speaker || "Narrator"
                  )}" style="width:125px; padding:3px 6px; font-size:11px;" title="Speaker / Character Role" />
                </div>
                <textarea class="scene-narration-input" rows="3" style="font-size:11.5px; padding:5px; resize:vertical;">${escapeHtml(
                  s.narration_text || ""
                )}</textarea>
              </div>
              <div style="color:var(--text-muted); font-size:11px; display:flex; justify-content:space-between; align-items:center; gap:4px; margin-top:4px;">
                <span>${escapeHtml(s.image_file)} (${(s.actual_audio_duration || s.duration || 0).toFixed(1)}s)</span>
                <button class="btn btn-sm btn-cyan" onclick="playOrSynthesizeSceneAudio(this, '${escapeJs(
                  sceneMp3Rel
                )}', ${hasSceneAudio})" title="Listen to this scene's voiceover">&#128266; Hear</button>
              </div>
            </div>
          </div>
        `;
      })
      .join("");
  } catch (err) {
    console.error("Error loading chapter detail:", err);
  }
}

async function saveStudioManifestEdits() {
  const slug = document.getElementById("studio-series-select").value;
  const ch = parseInt(document.getElementById("studio-chapter-select").value, 10);
  if (!slug || isNaN(ch)) return;

  const cards = document.querySelectorAll("#studio-scene-grid .scene-card");
  const scenes = [];
  cards.forEach((card) => {
    const sceneId = card.getAttribute("data-scene-id");
    const speaker = card.querySelector(".scene-speaker-input")?.value || "Narrator";
    const narration = card.querySelector(".scene-narration-input")?.value || "";
    if (sceneId) {
      scenes.push({
        scene_id: sceneId,
        speaker: speaker,
        narration_text: narration,
      });
    }
  });

  const res = await apiPost("/api/manifest/update", {
    series_slug: slug,
    chapter: ch,
    scenes: scenes,
  });
  if (res.ok) {
    showToast(`Saved ${res.updated_scenes} scenes to scene_manifest.json!`);
  } else {
    showToast(`Error saving manifest: ${res.error || "Unknown"}`);
  }
}

// =========================================================================
// Gemini AI Pro Web-Chat Script Importer (₹0 Unlimited)
// =========================================================================
let _lastGeminiProSheetsDir = "";

function toggleGeminiProImporter() {
  const box = document.getElementById("gemini-pro-importer");
  if (!box) return;
  box.style.display = box.style.display === "none" || !box.style.display ? "block" : "none";
}

async function openGeminiProImporterForChapter(seriesSlug, seriesName, chapter) {
  switchTab("tab-studio");
  const seriesSel = document.getElementById("studio-series-select");
  if (seriesSel) {
    seriesSel.value = seriesSlug;
    populateStudioChapters();
  }
  const chSel = document.getElementById("studio-chapter-select");
  if (chSel) {
    let found = false;
    for (const opt of chSel.options) {
      if (parseInt(opt.value, 10) === chapter) {
        found = true;
        break;
      }
    }
    if (!found) {
      const opt = document.createElement("option");
      opt.value = String(chapter);
      opt.textContent = `Ch.${chapter} (Inbox)`;
      chSel.appendChild(opt);
    }
    chSel.value = String(chapter);
  }
  const box = document.getElementById("gemini-pro-importer");
  if (box) box.style.display = "block";
  await prepareGeminiProPack();
}

async function prepareGeminiProPack() {
  const seriesSel = document.getElementById("studio-series-select");
  const slug = seriesSel?.value;
  const seriesName = seriesSel?.options[seriesSel.selectedIndex]?.text || slug;
  const ch = parseInt(document.getElementById("studio-chapter-select")?.value, 10);
  if (!slug || isNaN(ch)) {
    showToast("Select a series and chapter first!");
    return;
  }
  const statusEl = document.getElementById("gpro-status");
  if (statusEl) statusEl.innerHTML = `<span style="color:#38bdf8;">Preparing numbered panel sheets for ${escapeHtml(seriesName)} Ch.${ch}...</span>`;

  const res = await apiPost("/api/studio/gemini-pro-pack", {
    series_slug: slug,
    series_name: seriesName,
    chapter: ch,
  });
  if (res && res.ok) {
    _lastGeminiProSheetsDir = res.sheets_dir;
    const promptBox = document.getElementById("gpro-prompt-box");
    if (promptBox) promptBox.value = res.prompt;
    const openBtn = document.getElementById("btn-open-gpro-sheets");
    if (openBtn) openBtn.disabled = false;
    if (statusEl) {
      statusEl.innerHTML = `<span style="color:#4ade80;">&#9989; Ready!</span> Created <strong>${res.sheet_files.length} numbered sheets</strong> (${res.panel_count} panels) in <code>${escapeHtml(res.sheets_dir)}</code>. Click <strong>Copy Prompt</strong> + <strong>Open Sheets Folder</strong>, drop the sheets into Gemini Pro, and paste the JSON on the right!`;
    }
    showToast(`Created ${res.sheet_files.length} numbered panel sheets!`);
  } else {
    if (statusEl) statusEl.innerHTML = `<span style="color:#f87171;">Error: ${escapeHtml(res?.error || "Failed to prepare sheets")}</span>`;
  }
}

function openGeminiProSheetsFolder() {
  if (_lastGeminiProSheetsDir) {
    openWorkspaceFolder(_lastGeminiProSheetsDir);
  }
}

async function importGeminiProScript() {
  const seriesSel = document.getElementById("studio-series-select");
  const slug = seriesSel?.value;
  const seriesName = seriesSel?.options[seriesSel.selectedIndex]?.text || slug;
  const ch = parseInt(document.getElementById("studio-chapter-select")?.value, 10);
  const rawJson = (document.getElementById("gpro-json-input")?.value || "").trim();
  if (!slug || isNaN(ch) || !rawJson) {
    showToast("Select a chapter and paste the JSON from Gemini Pro first!");
    return;
  }
  const res = await apiPost("/api/studio/gemini-pro-import", {
    series_slug: slug,
    series_name: seriesName,
    chapter: ch,
    raw_json: rawJson,
  });
  if (res && res.ok) {
    showToast(`Imported ${res.scene_count} scenes for Ch.${ch} ("${res.title}")! Ready to Render!`);
    document.getElementById("gpro-json-input").value = "";
    await loadStudioChapter();
    await refreshAll();
  } else {
    showToast(`Import error: ${res?.error || "Invalid JSON"}`);
  }
}

// Voice Cast & Series Profile Editor
let loadedProfiles = [];

async function loadAllVoiceProfiles() {
  try {
    const res = await apiGet("/api/profiles");
    loadedProfiles = res.profiles || [];
    const sel = document.getElementById("voice-profile-select");
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = loadedProfiles
      .map((p) => `<option value="${escapeHtml(p.series_slug)}">${escapeHtml(p.series_name)} (${escapeHtml(p.genre)})</option>`)
      .join("");
    if (current && loadedProfiles.some((p) => p.series_slug === current)) {
      sel.value = current;
    }
    loadSelectedVoiceProfile();
  } catch (err) {
    console.error("Failed to load voice profiles:", err);
  }
}

function loadSelectedVoiceProfile() {
  const sel = document.getElementById("voice-profile-select");
  if (!sel) return;
  const slug = sel.value;
  const prof = loadedProfiles.find((p) => p.series_slug === slug);
  if (!prof) return;

  document.getElementById("vp-series-name").value = prof.series_name || "";
  document.getElementById("vp-genre").value = prof.genre || "murim";
  document.getElementById("vp-bgm-duck").value = prof.bgm_ducking_volume ?? 0.12;
  document.getElementById("vp-bgm-norm").value = prof.bgm_normal_volume ?? 0.35;

  const nav = prof.narrator_voice || {};
  document.getElementById("vp-narrator-voice").value = nav.voice_id || "gemini:Puck";
  document.getElementById("vp-narrator-rate").value = nav.rate || "+2%";
  document.getElementById("vp-narrator-pitch").value = nav.pitch || "+0Hz";

  const tbody = document.getElementById("vp-characters-tbody");
  const chars = prof.character_voices || {};
  tbody.innerHTML = Object.entries(chars)
    .map(([cName, v]) => renderCharacterVoiceRowHtml(cName, v.voice_id, v.rate, v.pitch, v.description))
    .join("");
}

function renderCharacterVoiceRowHtml(name = "", voiceId = "gemini:Puck", rate = "+2%", pitch = "+0Hz", desc = "") {
  return `
    <tr class="vp-char-row">
      <td><input type="text" class="vp-c-name" value="${escapeHtml(name)}" placeholder="e.g. Cheon Yeo-Woon" /></td>
      <td>
        <select class="vp-c-voice">
          <option value="gemini:Puck" ${voiceId === "gemini:Puck" || voiceId === "Puck" ? "selected" : ""}>&#127470;&#127475;&#10024; Gemini Indian Human: Puck (Young Expressive Male LLM)</option>
          <option value="gemini:Charon" ${voiceId === "gemini:Charon" || voiceId === "Charon" ? "selected" : ""}>&#127470;&#127475;&#10024; Gemini Indian Human: Charon (Deep Storyteller Male LLM)</option>
          <option value="hi-IN-MadhurNeural" ${voiceId === "hi-IN-MadhurNeural" ? "selected" : ""}>&#127470;&#127475; Indian Human: MadhurNeural (Warm Hindi Storyteller Male)</option>
          <option value="mr-IN-ManoharNeural" ${voiceId === "mr-IN-ManoharNeural" ? "selected" : ""}>&#127470;&#127475; Indian Human: ManoharNeural (Young 20yo Hero Male)</option>
          <option value="en-IN-PrabhatNeural" ${voiceId === "en-IN-PrabhatNeural" ? "selected" : ""}>&#127470;&#127475; Indian Human: PrabhatNeural (Urban Indian Hinglish Male)</option>
          <option value="ne-NP-SagarNeural" ${voiceId === "ne-NP-SagarNeural" ? "selected" : ""}>&#127470;&#127475; Indian/Devanagari Human: SagarNeural (Deep Lord / Swordsman Male)</option>
          <option value="hi-IN-SwaraNeural" ${voiceId === "hi-IN-SwaraNeural" ? "selected" : ""}>&#127470;&#127475; Indian Human: SwaraNeural (Attractive Hindi Female / System AI)</option>
          <option value="mr-IN-AarohiNeural" ${voiceId === "mr-IN-AarohiNeural" ? "selected" : ""}>&#127470;&#127475; Indian Human: AarohiNeural (Sweet Young Indian Heroine Female)</option>
          <option value="en-IN-NeerjaNeural" ${voiceId === "en-IN-NeerjaNeural" ? "selected" : ""}>&#127470;&#127475; Indian Human: NeerjaNeural (Sleek Modern Indian Hinglish Female)</option>
          <option value="gemini:Fenrir" ${voiceId === "gemini:Fenrir" || voiceId === "Fenrir" ? "selected" : ""}>&#127470;&#127475;&#10024; Gemini Indian Human: Fenrir (Intense Action Male LLM)</option>
          <option value="gemini:Kore" ${voiceId === "gemini:Kore" || voiceId === "Kore" ? "selected" : ""}>&#127470;&#127475;&#10024; Gemini Indian Human: Kore (Warm Natural Female LLM)</option>
          <option value="gemini:Aoede" ${voiceId === "gemini:Aoede" || voiceId === "Aoede" ? "selected" : ""}>&#127470;&#127475;&#10024; Gemini Indian Human: Aoede (Expressive Heroine Female LLM)</option>
          <option value="en-US-AndrewMultilingualNeural" ${voiceId === "en-US-AndrewMultilingualNeural" ? "selected" : ""}>&#127757; Global Human V2: AndrewMultilingual (Storyteller Male)</option>
          <option value="en-US-BrianMultilingualNeural" ${voiceId === "en-US-BrianMultilingualNeural" ? "selected" : ""}>&#127757; Global Human V2: BrianMultilingual (Young Hero Male)</option>
          <option value="en-US-AvaMultilingualNeural" ${voiceId === "en-US-AvaMultilingualNeural" ? "selected" : ""}>&#127757; Global Human V2: AvaMultilingual (Natural Female)</option>
          <option value="en-US-EmmaMultilingualNeural" ${voiceId === "en-US-EmmaMultilingualNeural" ? "selected" : ""}>&#127757; Global Human V2: EmmaMultilingual (Young Heroine Female)</option>
        </select>
      </td>
      <td><input type="text" class="vp-c-rate" value="${escapeHtml(rate)}" style="width:90px;" /></td>
      <td><input type="text" class="vp-c-pitch" value="${escapeHtml(pitch)}" style="width:90px;" /></td>
      <td><input type="text" class="vp-c-desc" value="${escapeHtml(desc)}" placeholder="Role notes" /></td>
      <td><button class="btn btn-sm btn-cyan" onclick="previewCharacterRowVoice(this)">&#128266; Hear</button></td>
      <td><button class="btn btn-sm" onclick="this.closest('tr').remove()">&#10005;</button></td>
    </tr>
  `;
}

async function runVoicePreviewRequest(payload, btnEl = null) {
  const statusEl = document.getElementById("vp-preview-status");
  const player = document.getElementById("vp-audio-player");
  const origBtnHtml = btnEl ? btnEl.innerHTML : null;
  if (btnEl) {
    btnEl.disabled = true;
    btnEl.textContent = "⏳...";
  }
  if (statusEl) {
    statusEl.textContent = `Synthesizing ${payload.speaker || "Voice"} (${payload.voice_id}, rate=${payload.rate}, pitch=${payload.pitch})...`;
  }

  try {
    const res = await apiPost("/api/voice-preview", payload);
    if (res.ok && res.audio_path) {
      const audioUrl = `/api/media?path=${encodeURIComponent(res.audio_path)}&t=${Date.now()}`;
      if (player) {
        player.src = audioUrl;
        player.play().catch(() => {});
      } else {
        const tempAudio = new Audio(audioUrl);
        tempAudio.play().catch(() => {});
      }
      if (statusEl) {
        statusEl.innerHTML = `<span style="color:var(--accent-emerald);">&#9654; Playing <strong>${escapeHtml(
          res.speaker
        )}</strong> (${escapeHtml(res.voice_id)}, ${escapeHtml(res.rate)}, ${escapeHtml(res.pitch)}): "${escapeHtml(
          res.text
        )}"</span>`;
      }
      showToast(`Playing voice: ${res.speaker}`);
    } else {
      showToast(`Voice preview error: ${res.error || "Failed"}`);
    }
  } catch (err) {
    showToast("Failed to synthesize voice preview");
  } finally {
    if (btnEl && origBtnHtml) {
      btnEl.disabled = false;
      btnEl.innerHTML = origBtnHtml;
    }
  }
}

async function previewNarratorVoice() {
  const voiceId = document.getElementById("vp-narrator-voice").value;
  const rate = document.getElementById("vp-narrator-rate").value.trim() || "+6%";
  const pitch = document.getElementById("vp-narrator-pitch").value.trim() || "+0Hz";
  const customText = document.getElementById("vp-sample-text")?.value.trim() || "";
  await runVoicePreviewRequest({
    speaker: "Narrator",
    voice_id: voiceId,
    rate: rate,
    pitch: pitch,
    description: "Main Studio Narrator",
    text: customText,
  });
}

async function previewCharacterRowVoice(btnEl) {
  const tr = btnEl.closest("tr");
  if (!tr) return;
  const speaker = tr.querySelector(".vp-c-name")?.value.trim() || "Character";
  const voiceId = tr.querySelector(".vp-c-voice")?.value || "gemini:Puck";
  const rate = tr.querySelector(".vp-c-rate")?.value.trim() || "+2%";
  const pitch = tr.querySelector(".vp-c-pitch")?.value.trim() || "+0Hz";
  const desc = tr.querySelector(".vp-c-desc")?.value.trim() || "";
  const customText = document.getElementById("vp-sample-text")?.value.trim() || "";

  await runVoicePreviewRequest(
    {
      speaker: speaker,
      voice_id: voiceId,
      rate: rate,
      pitch: pitch,
      description: desc,
      text: customText,
    },
    btnEl
  );
}

async function playOrSynthesizeSceneAudio(btnEl, sceneMp3Rel, hasExistingAudio) {
  const card = btnEl.closest(".scene-card");
  const speaker = card?.querySelector(".scene-speaker-input")?.value.trim() || "Narrator";
  const narration = card?.querySelector(".scene-narration-input")?.value.trim() || "";

  const spkL = speaker.toLowerCase();
  let defaultVid = "gemini:Puck";
  if (spkL.includes("girl") || spkL.includes("nano") || spkL.includes("lady") || spkL.includes("system") || spkL.includes("queen") || spkL.includes("alicia")) {
    defaultVid = "gemini:Kore";
  } else if (spkL.includes("javier") || spkL.includes("count") || spkL.includes("lord") || spkL.includes("elder")) {
    defaultVid = "gemini:Charon";
  }

  await runVoicePreviewRequest(
    {
      speaker: speaker,
      voice_id: defaultVid,
      rate: "+2%",
      pitch: "+0Hz",
      description: speaker,
      text: narration,
    },
    btnEl
  );
}

function addCharacterVoiceRow() {
  const tbody = document.getElementById("vp-characters-tbody");
  tbody.insertAdjacentHTML("afterbegin", renderCharacterVoiceRowHtml("", "gemini:Puck", "+2%", "+0Hz", "Custom Character"));
}

function openNewSeriesModal() {
  const modal = document.getElementById("new-series-modal");
  if (modal) modal.classList.add("open");
}

function closeNewSeriesModal() {
  const modal = document.getElementById("new-series-modal");
  if (modal) modal.classList.remove("open");
}

async function submitNewSeriesOnboard() {
  const name = document.getElementById("ns-name")?.value.trim();
  const genre = document.getElementById("ns-genre")?.value || "murim";
  const useAi = document.getElementById("ns-ai-cast")?.checked ?? true;
  const btn = document.getElementById("btn-create-series");
  if (!name) {
    showToast("Please enter a Manhwa Series Name");
    return;
  }
  const origHtml = btn ? btn.innerHTML : "";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "⏳ Onboarding & Casting Voices...";
  }
  try {
    const res = await apiPost("/api/series/onboard", {
      series_name: name,
      genre: genre,
      use_ai_cast: useAi,
      refresh_existing: false,
    });
    if (res.ok && res.profile) {
      closeNewSeriesModal();
      showToast(`Onboarded '${name}'! Drop chapters into ${res.inbox_path}`);
      await loadAllVoiceProfiles();
      await refreshAll();
      const sel = document.getElementById("voice-profile-select");
      if (sel) {
        sel.value = res.profile.series_slug;
        loadSelectedVoiceProfile();
      }
      switchTab("tab-voices");
    } else {
      showToast(`Error onboarding series: ${res.error || "Unknown"}`);
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  }
}

async function autoCastCurrentProfileVoices(btnEl) {
  const name = document.getElementById("vp-series-name")?.value.trim();
  const genre = document.getElementById("vp-genre")?.value || "murim";
  if (!name) return;
  const origHtml = btnEl ? btnEl.innerHTML : "";
  if (btnEl) {
    btnEl.disabled = true;
    btnEl.textContent = "⏳ Casting 5 Neural Voices...";
  }
  try {
    const res = await apiPost("/api/series/onboard", {
      series_name: name,
      genre: genre,
      use_ai_cast: true,
      refresh_existing: true,
    });
    if (res.ok && res.profile) {
      showToast(`Upgraded '${name}' with ${Object.keys(res.profile.character_voices || {}).length} multi-voice characters!`);
      await loadAllVoiceProfiles();
      const sel = document.getElementById("voice-profile-select");
      if (sel) {
        sel.value = res.profile.series_slug;
        loadSelectedVoiceProfile();
      }
    } else {
      showToast(`Failed to auto-cast: ${res.error || "Unknown"}`);
    }
  } finally {
    if (btnEl) {
      btnEl.disabled = false;
      btnEl.innerHTML = origHtml;
    }
  }
}

async function saveCurrentVoiceProfile() {
  const slug = document.getElementById("voice-profile-select").value;
  const prof = loadedProfiles.find((p) => p.series_slug === slug);
  if (!prof) return;

  prof.series_name = document.getElementById("vp-series-name").value.trim() || prof.series_name;
  prof.genre = document.getElementById("vp-genre").value;
  prof.bgm_ducking_volume = parseFloat(document.getElementById("vp-bgm-duck").value || "0.16");
  prof.bgm_normal_volume = parseFloat(document.getElementById("vp-bgm-norm").value || "0.40");

  const navVid = document.getElementById("vp-narrator-voice").value;
  prof.narrator_voice = {
    provider: navVid.startsWith("gemini:") ? "gemini" : "edge-tts",
    voice_id: navVid,
    rate: document.getElementById("vp-narrator-rate").value.trim() || "+4%",
    pitch: document.getElementById("vp-narrator-pitch").value.trim() || "+0Hz",
    volume: "+0%",
    description: "Realistic Human Studio Narrator Voice",
  };

  const charMap = {};
  document.querySelectorAll("#vp-characters-tbody .vp-char-row").forEach((tr) => {
    const cName = tr.querySelector(".vp-c-name")?.value.trim();
    if (!cName) return;
    const cVid = tr.querySelector(".vp-c-voice")?.value || "mr-IN-ManoharNeural";
    charMap[cName] = {
      provider: cVid.startsWith("gemini:") ? "gemini" : "edge-tts",
      voice_id: cVid,
      rate: tr.querySelector(".vp-c-rate")?.value.trim() || "+6%",
      pitch: tr.querySelector(".vp-c-pitch")?.value.trim() || "+0Hz",
      volume: "+0%",
      description: tr.querySelector(".vp-c-desc")?.value.trim() || "",
    };
  });
  prof.character_voices = charMap;

  const res = await apiPost("/api/profiles/save", { profile: prof });
  if (res.ok) {
    showToast(`Saved voice profile for ${prof.series_name}!`);
    await loadAllVoiceProfiles();
  } else {
    showToast(`Failed to save profile: ${res.error}`);
  }
}

async function applyVoiceToAllSeries() {
  const voiceId = document.getElementById("vp-narrator-voice")?.value || "gemini:Puck";
  const rate = document.getElementById("vp-narrator-rate")?.value.trim() || "+2%";
  const pitch = document.getElementById("vp-narrator-pitch")?.value.trim() || "+0Hz";
  const bgmDuck = parseFloat(document.getElementById("vp-bgm-duck")?.value || "0.12");
  const bgmNorm = parseFloat(document.getElementById("vp-bgm-norm")?.value || "0.35");

  await saveCurrentVoiceProfile();
  const res = await apiPost("/api/profiles/apply-global", {
    voice_id: voiceId,
    rate: rate,
    pitch: pitch,
    bgm_ducking_volume: bgmDuck,
    bgm_normal_volume: bgmNorm,
  });
  if (res.ok) {
    showToast(`Applied ${voiceId} (${rate}, ${pitch}) to ALL ${res.updated_profiles} Manhwa Series!`);
    await loadAllVoiceProfiles();
  }
}

// Dynamic .env Studio Settings Editor
async function loadStudioEnvConfig() {
  try {
    const res = await apiGet("/api/env-config");
    const cfg = res.config || {};
    document.getElementById("env-default-series").value = cfg.default_series || "Nano Machine";
    document.getElementById("env-llm-provider").value = cfg.llm_provider || "gemini";
    document.getElementById("env-gemini-models").value = (cfg.gemini_models || []).join(",");
    document.getElementById("env-batch-size").value = cfg.llm_batch_size ?? 8;
    document.getElementById("env-thumb-size").value = cfg.vision_thumb_size ?? 512;
    document.getElementById("env-batch-delay").value = cfg.batch_delay_sec ?? 2.0;
    document.getElementById("env-cooldown-sec").value = cfg.rate_limit_cooldown_sec ?? 45.0;
    document.getElementById("env-max-attempts").value = cfg.max_batch_attempts ?? 4;

    document.getElementById("env-pro-width").value = cfg.pro_width ?? 1920;
    document.getElementById("env-pro-height").value = cfg.pro_height ?? 1080;
    document.getElementById("env-pro-fps").value = cfg.pro_fps ?? 30;
    document.getElementById("env-video-quality").value = cfg.video_quality ?? 19;
    document.getElementById("env-default-speed").value = cfg.default_speed ?? 1.25;
    document.getElementById("env-auto-clean").checked = !!cfg.auto_clean_segments;
    document.getElementById("env-disable-gpu").checked = !!cfg.disable_gpu;
    if (document.getElementById("env-ambient-aura")) {
      document.getElementById("env-ambient-aura").checked = cfg.enable_ambient_aura !== false;
    }
    if (document.getElementById("env-microfade")) {
      document.getElementById("env-microfade").checked = cfg.enable_scene_microfade !== false;
    }

    document.getElementById("env-min-scene-sec").value = cfg.min_scene_sec ?? 3.2;
    document.getElementById("env-scene-buffer-sec").value = cfg.scene_buffer_sec ?? 0.45;
    document.getElementById("env-target-lufs").value = cfg.target_lufs ?? -16.0;
    document.getElementById("env-default-bgm").value = cfg.default_bgm_file || "assets/audio/bgm/suspense_theme.wav";
    if (document.getElementById("env-sfx-vol")) {
      document.getElementById("env-sfx-vol").value = cfg.sfx_volume ?? 0.28;
    }
    if (document.getElementById("env-enable-sfx")) {
      document.getElementById("env-enable-sfx").checked = cfg.enable_sfx !== false;
    }

    document.getElementById("env-bumper-dur").value = cfg.bumper_duration_sec ?? 2.5;
    document.getElementById("env-font-latin").value = cfg.font_latin || "C:\\Windows\\Fonts\\arialbd.ttf";
    document.getElementById("env-font-hindi").value = cfg.font_hindi || "C:\\Windows\\Fonts\\mangal.ttf";
  } catch (err) {
    console.error("Failed to load .env studio config:", err);
  }
}

async function saveStudioEnvConfig() {
  const payload = {
    default_series: document.getElementById("env-default-series").value.trim(),
    llm_provider: document.getElementById("env-llm-provider").value,
    gemini_models: document
      .getElementById("env-gemini-models")
      .value.split(",")
      .map((s) => s.trim())
      .filter(Boolean),
    llm_batch_size: parseInt(document.getElementById("env-batch-size").value || "8", 10),
    vision_thumb_size: parseInt(document.getElementById("env-thumb-size").value || "512", 10),
    batch_delay_sec: parseFloat(document.getElementById("env-batch-delay").value || "2.0"),
    rate_limit_cooldown_sec: parseFloat(document.getElementById("env-cooldown-sec").value || "45.0"),
    max_batch_attempts: parseInt(document.getElementById("env-max-attempts").value || "4", 10),

    pro_width: parseInt(document.getElementById("env-pro-width").value || "1920", 10),
    pro_height: parseInt(document.getElementById("env-pro-height").value || "1080", 10),
    pro_fps: parseInt(document.getElementById("env-pro-fps").value || "30", 10),
    video_quality: parseInt(document.getElementById("env-video-quality").value || "19", 10),
    default_speed: parseFloat(document.getElementById("env-default-speed").value || "1.25"),
    auto_clean_segments: document.getElementById("env-auto-clean").checked,
    disable_gpu: document.getElementById("env-disable-gpu").checked,
    enable_ambient_aura: document.getElementById("env-ambient-aura") ? document.getElementById("env-ambient-aura").checked : true,
    enable_scene_microfade: document.getElementById("env-microfade") ? document.getElementById("env-microfade").checked : true,

    min_scene_sec: parseFloat(document.getElementById("env-min-scene-sec").value || "3.2"),
    scene_buffer_sec: parseFloat(document.getElementById("env-scene-buffer-sec").value || "0.45"),
    target_lufs: parseFloat(document.getElementById("env-target-lufs").value || "-16.0"),
    default_bgm_file: document.getElementById("env-default-bgm").value.trim(),
    enable_sfx: document.getElementById("env-enable-sfx") ? document.getElementById("env-enable-sfx").checked : true,
    sfx_volume: document.getElementById("env-sfx-vol") ? parseFloat(document.getElementById("env-sfx-vol").value || "0.28") : 0.28,

    bumper_duration_sec: parseFloat(document.getElementById("env-bumper-dur").value || "2.5"),
    font_latin: document.getElementById("env-font-latin").value.trim(),
    font_hindi: document.getElementById("env-font-hindi").value.trim(),
  };

  const res = await apiPost("/api/env-config/save", { config: payload });
  if (res.ok) {
    showToast("Saved runtime configuration to .env!");
    await loadStudioEnvConfig();
    await refreshAll();
  } else {
    showToast(`Failed to save .env: ${res.error || "Unknown error"}`);
  }
}

// =========================================================================
// Gemini API Keys & Live TTS Support Checker
// =========================================================================
let envGeminiKeysCache = [];
let envGeminiProbeById = {};
let precheckRawKeyById = {};

function renderTtsBadgeHtml(r) {
  if (!r || !r.tts_status) {
    return `<span class="badge">Not Tested</span>`;
  }
  const msTxt = r.tts_ms ? ` &bull; ${r.tts_ms}ms` : "";
  const detail = escapeHtml(r.tts_detail || "");
  if (r.tts_status === "ok") {
    return `<span class="badge badge-rendered">&#10004; TTS Ready${msTxt}</span><div style="font-size:11px; color:var(--text-secondary); margin-top:3px;">${detail}</div>`;
  }
  if (r.tts_status === "quota_429") {
    return `<span class="badge badge-inbox">&#9203; TTS Supported (429 Quota${msTxt})</span><div style="font-size:11px; color:var(--text-secondary); margin-top:3px;">${detail}</div>`;
  }
  if (r.tts_status === "tts38_only") {
    return `<span class="badge badge-script">&#9888; Supports 3.8 TTS Only${msTxt}</span><div style="font-size:11px; color:var(--text-secondary); margin-top:3px;">${detail}</div>`;
  }
  return `<span class="badge" style="background:rgba(225,29,72,0.18);color:#fda4af;border:1px solid rgba(225,29,72,0.4);">&#10006; Not Supported (${escapeHtml(r.tts_status)})</span><div style="font-size:11px; color:#fda4af; margin-top:3px;">${detail}</div>`;
}

function renderScriptBadgeHtml(r) {
  if (!r || !r.script_status) {
    return `<span class="badge">Not Tested</span>`;
  }
  const msTxt = r.script_ms ? ` &bull; ${r.script_ms}ms` : "";
  if (r.script_status === "ok") {
    return `<span class="badge badge-rendered">&#10004; Script OK${msTxt}</span>`;
  }
  if (r.script_status === "quota_429") {
    return `<span class="badge badge-inbox">&#9203; Supported (429 Quota)</span>`;
  }
  return `<span class="badge" style="background:rgba(225,29,72,0.18);color:#fda4af;border:1px solid rgba(225,29,72,0.4);">&#10006; ${escapeHtml(r.script_status)}</span><div style="font-size:11px; color:#fda4af; margin-top:3px;">${escapeHtml(r.script_detail || "")}</div>`;
}

function renderEnvGeminiKeysTable() {
  const tbody = document.getElementById("gk-keys-tbody");
  const summaryBar = document.getElementById("gk-summary-bar");
  if (!tbody || !summaryBar) return;

  if (!envGeminiKeysCache.length) {
    summaryBar.innerHTML = `<span style="color:#fda4af;">No Gemini API keys configured in .env yet. Paste an AQ. or AIza key above to test and add it.</span>`;
    tbody.innerHTML = `<tr><td colspan="6" style="color:var(--text-secondary); text-align:center;">No keys found in .env</td></tr>`;
    return;
  }

  const testedRows = envGeminiKeysCache.map((k) => envGeminiProbeById[k.key_id]).filter(Boolean);
  if (testedRows.length > 0) {
    const readyCnt = testedRows.filter((r) => r.tts_ready).length;
    const supCnt = testedRows.filter((r) => r.tts_supported).length;
    const scrCnt = testedRows.filter((r) => r.script_ready).length;
    summaryBar.innerHTML = `${envGeminiKeysCache.length} Key(s) in <code>.env</code> &bull; Tested ${testedRows.length}: <strong style="color:#6ee7b7;">${readyCnt} TTS Ready Now</strong> | <strong style="color:#67e8f9;">${supCnt} Support TTS</strong> | <strong>${scrCnt} Script OK</strong>`;
  } else {
    summaryBar.innerHTML = `${envGeminiKeysCache.length} Gemini Key(s) saved in <code>.env</code> &mdash; Click <strong>"Test All .env Keys"</strong> to verify live TTS &amp; Script support.`;
  }

  tbody.innerHTML = envGeminiKeysCache
    .map((k) => {
      const probe = envGeminiProbeById[k.key_id];
      return `
        <tr>
          <td><strong>#${k.index}</strong></td>
          <td><code>${escapeHtml(k.masked)}</code></td>
          <td><span class="badge ${k.key_type.includes("AQ.") ? "badge-script" : "badge-running"}">${escapeHtml(k.key_type)}</span></td>
          <td>${renderTtsBadgeHtml(probe)}</td>
          <td>${renderScriptBadgeHtml(probe)}</td>
          <td style="white-space:nowrap;">
            <button class="btn btn-sm btn-cyan" onclick="checkSingleEnvGeminiKey('${escapeJs(k.key_id)}')">&#129514; Test</button>
            <button class="btn btn-sm" style="color:#fda4af;" onclick="removeEnvGeminiKey('${escapeJs(k.key_id)}', '${escapeJs(k.masked)}')">&#128465; Remove</button>
          </td>
        </tr>
      `;
    })
    .join("");
}

async function loadGeminiKeysList() {
  try {
    const res = await apiGet("/api/gemini-keys");
    if (res.ok) {
      envGeminiKeysCache = res.keys || [];
      renderEnvGeminiKeysTable();
    }
  } catch (err) {
    console.error("Failed to load Gemini keys list:", err);
  }
}

async function checkAllEnvGeminiKeys() {
  const btn = document.getElementById("btn-test-all-keys");
  const orig = btn ? btn.textContent : "";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Testing all keys...";
  }
  const summaryBar = document.getElementById("gk-summary-bar");
  if (summaryBar) summaryBar.textContent = "Running live TTS & Script probes across all keys in .env...";
  try {
    const res = await apiPost("/api/gemini-keys/check", { mode: "env" });
    if (res.ok) {
      (res.results || []).forEach((r) => {
        envGeminiProbeById[r.key_id] = r;
      });
      renderEnvGeminiKeysTable();
      const s = res.summary || {};
      showToast(`Checked ${s.total || 0} keys: ${s.tts_ready || 0} TTS Ready now (${s.tts_supported || 0} support TTS)`);
    } else {
      showToast(`Key check failed: ${res.error || "Unknown error"}`);
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = orig;
    }
  }
}

async function checkSingleEnvGeminiKey(keyId) {
  showToast("Testing single key for Gemini 2.5 Puck TTS...");
  const res = await apiPost("/api/gemini-keys/check", { key_id: keyId });
  if (res.ok && res.results && res.results.length) {
    const r = res.results[0];
    envGeminiProbeById[r.key_id] = r;
    renderEnvGeminiKeysTable();
    showToast(`${r.masked}: ${r.tts_ready ? "TTS Ready!" : r.tts_status}`);
  } else {
    showToast(`Failed to test key: ${res.error || "Unknown error"}`);
  }
}

async function checkNewGeminiKeys() {
  const inputEl = document.getElementById("gk-new-keys-input");
  const statusEl = document.getElementById("gk-new-status");
  const boxEl = document.getElementById("gk-precheck-box");
  const tbody = document.getElementById("gk-precheck-tbody");
  const btn = document.getElementById("btn-test-new-keys");
  const rawVal = (inputEl ? inputEl.value : "").trim();

  if (!rawVal) {
    showToast("Paste one or more Gemini API keys first.");
    return;
  }

  const tokens = rawVal.split(/[\s,;]+/).map((s) => s.trim().replace(/^["']|["']$/g, "")).filter(Boolean);
  if (btn) btn.disabled = true;
  if (statusEl) statusEl.textContent = `Testing ${tokens.length} key(s) against Gemini 2.5 Puck TTS & Script LLM...`;

  try {
    const res = await apiPost("/api/gemini-keys/check", { mode: "custom", keys: rawVal });
    if (!res.ok) {
      if (statusEl) statusEl.textContent = res.error || "Failed to test key(s).";
      showToast(res.error || "Key test failed");
      return;
    }

    const results = res.results || [];
    precheckRawKeyById = {};
    results.forEach((r, idx) => {
      if (tokens[idx]) precheckRawKeyById[r.key_id] = tokens[idx];
    });

    if (boxEl) boxEl.style.display = "block";
    if (tbody) {
      tbody.innerHTML = results
        .map((r) => {
          const actionBtn = r.already_in_env
            ? `<span class="badge badge-script">Already in .env</span>`
            : r.tts_supported
            ? `<button class="btn btn-sm btn-emerald" onclick="addVerifiedKeyById('${escapeJs(r.key_id)}')">&#10133; Add to .env</button>`
            : `<button class="btn btn-sm" onclick="addVerifiedKeyById('${escapeJs(r.key_id)}')">&#10133; Force Add</button>`;
          return `
            <tr>
              <td><code>${escapeHtml(r.masked)}</code></td>
              <td><span class="badge ${r.key_type.includes("AQ.") ? "badge-script" : "badge-running"}">${escapeHtml(r.key_type)}</span></td>
              <td>${renderTtsBadgeHtml(r)}</td>
              <td>${renderScriptBadgeHtml(r)}</td>
              <td>${actionBtn}</td>
            </tr>
          `;
        })
        .join("");
    }

    const s = res.summary || {};
    if (statusEl) {
      statusEl.innerHTML = `<strong style="color:${s.tts_supported > 0 ? "#6ee7b7" : "#fda4af"};">${s.tts_ready}/${s.total} Ready for Gemini 2.5 Puck TTS (${s.tts_supported}/${s.total} support TTS, ${s.script_ready}/${s.total} Script OK)</strong>`;
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function addVerifiedKeyById(keyId) {
  const rawTok = precheckRawKeyById[keyId];
  if (!rawTok) return;
  const res = await apiPost("/api/gemini-keys/add", { keys: rawTok });
  if (res.ok) {
    showToast(`Added key to .env (${res.total} total keys saved)!`);
    await loadGeminiKeysList();
    await refreshAll();
    await checkNewGeminiKeys();
  } else {
    showToast(`Failed to add key: ${res.error || "Unknown error"}`);
  }
}

async function addNewGeminiKeysToEnv() {
  const inputEl = document.getElementById("gk-new-keys-input");
  const statusEl = document.getElementById("gk-new-status");
  const rawVal = (inputEl ? inputEl.value : "").trim();
  if (!rawVal) {
    showToast("Paste key(s) first before adding to .env.");
    return;
  }

  const res = await apiPost("/api/gemini-keys/add", { keys: rawVal });
  if (res.ok) {
    if (inputEl) inputEl.value = "";
    if (statusEl) {
      statusEl.innerHTML = `<strong style="color:#6ee7b7;">Added ${res.added} new key(s) to .env${res.skipped_duplicates ? ` (${res.skipped_duplicates} duplicate skipped)` : ""}. Total: ${res.total}.</strong>`;
    }
    showToast(`Added ${res.added} key(s) to .env!`);
    await loadGeminiKeysList();
    await refreshAll();
  } else {
    showToast(`Failed to add key(s): ${res.error || "Unknown error"}`);
  }
}

async function removeEnvGeminiKey(keyId, masked) {
  if (!confirm(`Remove Gemini API key (${masked}) from .env?`)) return;
  const res = await apiPost("/api/gemini-keys/remove", { key_id: keyId });
  if (res.ok) {
    delete envGeminiProbeById[keyId];
    showToast(`Removed ${masked} from .env`);
    await loadGeminiKeysList();
    await refreshAll();
  } else {
    showToast(`Failed to remove key: ${res.error || "Unknown error"}`);
  }
}

function selectSceneForThumbnail(sceneId, panelFile, narrationText) {
  document.getElementById("thumb-scene-id").value = sceneId;
  document.getElementById("thumb-panel-file").value = panelFile;
  if (!document.getElementById("thumb-hook-text").value && narrationText) {
    document.getElementById("thumb-hook-text").value = narrationText.slice(0, 60);
  }
  showToast(`Selected ${sceneId} (${panelFile}) for Thumbnail`);
}

async function generateCustomThumbnail() {
  const slug = document.getElementById("studio-series-select").value;
  const ch = parseInt(document.getElementById("studio-chapter-select").value, 10);
  const scene = document.getElementById("thumb-scene-id").value.trim();
  const panel = document.getElementById("thumb-panel-file").value.trim();
  const captions = document.getElementById("thumb-captions").checked;
  const hook = document.getElementById("thumb-hook-text").value.trim();

  const res = await apiPost("/api/jobs/enqueue", {
    action: "pro-thumbnail",
    series_slug: slug,
    series_name: slug,
    chapter: ch,
    scene: scene,
    panel: panel,
    captions: captions,
    hook: hook,
  });
  if (res.ok) {
    showToast("Thumbnail generation job queued!");
    setTimeout(() => loadStudioChapter(), 3000);
  }
}

async function regenerateChapterYoutubeKit() {
  const slug = document.getElementById("studio-series-select").value;
  const ch = parseInt(document.getElementById("studio-chapter-select").value, 10);
  const res = await apiPost("/api/jobs/enqueue", {
    action: "pro-youtube-kit",
    series_slug: slug,
    series_name: slug,
    chapter: ch,
  });
  if (res.ok) {
    showToast("YouTube SEO Kit generation queued!");
    setTimeout(() => loadStudioChapter(), 3000);
  }
}

function openCurrentChapterFolder() {
  const slug = document.getElementById("studio-series-select").value;
  const ch = parseInt(document.getElementById("studio-chapter-select").value, 10);
  if (!slug || isNaN(ch)) return;
  const padded = String(ch).padStart(3, "0");
  openWorkspaceFolder(`data/projects/${slug}/chapter_${padded}`);
}

// Social Media & Reels Studio (YouTube Community Posts + Instagram Reels & 4:5 Carousels)
function populateSocialChapters() {
  const sel = document.getElementById("social-series-select");
  const chSel = document.getElementById("social-chapter-select");
  if (!sel || !chSel) return;
  const slug = sel.value;
  const sObj = (appState.series || []).find((s) => s.series_slug === slug);
  if (!sObj) {
    chSel.innerHTML = "";
    return;
  }
  const projectChs = (sObj.chapters || []).filter((c) => c.project_path);
  chSel.innerHTML = projectChs
    .map((c) => `<option value="${c.chapter}">Ch.${c.chapter} — ${escapeHtml(c.title)}</option>`)
    .join("");
  if (projectChs.length > 0) {
    loadSocialPackForChapter();
  }
}

async function openChapterInSocialStudio(seriesSlug, chapter) {
  switchTab("tab-social");
  const sSel = document.getElementById("social-series-select");
  if (sSel) {
    sSel.value = seriesSlug;
    populateSocialChapters();
  }
  const cSel = document.getElementById("social-chapter-select");
  if (cSel) {
    cSel.value = String(chapter);
  }
  await loadSocialPackForChapter();
}

async function loadSocialPackForChapter() {
  const slug = document.getElementById("social-series-select")?.value;
  const ch = document.getElementById("social-chapter-select")?.value;
  if (!slug || !ch) return;

  try {
    const data = await apiGet(`/api/social-pack?series=${encodeURIComponent(slug)}&chapter=${ch}`);
    const reelBox = document.getElementById("social-reel-box");
    const imgGrid = document.getElementById("social-images-grid");
    const ytBox = document.getElementById("social-yt-post-box");
    const igBox = document.getElementById("social-ig-caption-box");
    const titleBox = document.getElementById("social-reel-title-box");

    if (!data.exists) {
      if (reelBox) {
        reelBox.innerHTML = `<span style="color:var(--text-muted); font-size:13px;">No 9:16 Reel generated yet for Ch.${ch}. Click "🚀 Generate YT Post + IG Carousel + 9:16 Reel" above!</span>`;
      }
      if (imgGrid) {
        imgGrid.innerHTML = `<div class="stat-box" style="color:var(--text-muted); font-size:12.5px; grid-column:1/-1; text-align:center;">No YouTube Community Post or Instagram Carousel images generated yet for Ch.${ch}.</div>`;
      }
      if (ytBox) ytBox.value = "";
      if (igBox) igBox.value = "";
      if (titleBox) titleBox.value = "";
      return;
    }

    // 1. Render 9:16 Reel Video Player
    if (reelBox) {
      if (data.reel_video) {
        reelBox.innerHTML = `
          <div style="width:100%; display:flex; flex-direction:column; align-items:center; gap:8px;">
            <video controls style="max-height:420px; border-radius:8px; background:#000;" src="/api/media?path=${encodeURIComponent(
              data.reel_video
            )}&t=${Date.now()}"></video>
            <div style="font-size:12px; color:var(--accent-emerald);">&#10003; Ready for Instagram Reels &amp; YouTube Shorts (1080x1920 9:16)</div>
          </div>
        `;
      } else {
        reelBox.innerHTML = `<span style="color:var(--accent-amber); font-size:12.5px;">&#9888; Images &amp; Copy generated! (Render the chapter video first to also generate the 9:16 Reel MP4).</span>`;
      }
    }

    // 2. Render 1:1 YouTube Post Image + 4-Slide Instagram 4:5 Carousel Images
    if (imgGrid) {
      const cards = [];
      if (data.yt_post_image) {
        cards.push(`
          <div class="stat-box" style="padding:8px; text-align:center;">
            <div style="font-size:11.5px; font-weight:600; color:var(--accent-amber); margin-bottom:6px;">YouTube Post (1:1)</div>
            <a href="/api/media?path=${encodeURIComponent(data.yt_post_image)}&t=${Date.now()}" target="_blank">
              <img src="/api/media?path=${encodeURIComponent(
                data.yt_post_image
              )}&t=${Date.now()}" style="width:100%; border-radius:6px; object-fit:cover;" />
            </a>
          </div>
        `);
      }
      (data.ig_carousel_images || []).forEach((imgPath, idx) => {
        cards.push(`
          <div class="stat-box" style="padding:8px; text-align:center;">
            <div style="font-size:11.5px; font-weight:600; color:#f472b6; margin-bottom:6px;">IG Slide ${idx + 1}/4 (4:5)</div>
            <a href="/api/media?path=${encodeURIComponent(imgPath)}&t=${Date.now()}" target="_blank">
              <img src="/api/media?path=${encodeURIComponent(
                imgPath
              )}&t=${Date.now()}" style="width:100%; border-radius:6px; object-fit:cover;" />
            </a>
          </div>
        `);
      });
      imgGrid.innerHTML = cards.join("");
    }

    // 3. Populate Copy Boxes
    const copy = data.copy || {};
    if (ytBox) {
      const pollOpts = (copy.yt_poll_options || []).map((o) => `[ ] ${o}`).join("\n");
      ytBox.value = `${copy.yt_community_post || ""}\n\n📊 POLL: ${copy.yt_poll_question || ""}\n${pollOpts}`;
    }
    if (igBox) {
      igBox.value = copy.ig_caption || "";
    }
    if (titleBox) {
      titleBox.value = copy.reel_title || "";
    }
  } catch (err) {
    console.error("Failed to load social pack:", err);
  }
}

async function generateSocialPackNow(btnEl) {
  const slug = document.getElementById("social-series-select")?.value;
  const ch = parseInt(document.getElementById("social-chapter-select")?.value || "1", 10);
  const dur = parseFloat(document.getElementById("social-reel-dur")?.value || "45");
  const startRaw = document.getElementById("social-reel-start")?.value.trim();
  const overlays = document.getElementById("social-overlays")?.checked ?? true;

  if (!slug || isNaN(ch)) return;
  const origHtml = btnEl ? btnEl.innerHTML : "";
  if (btnEl) {
    btnEl.disabled = true;
    btnEl.textContent = "⏳ Generating YT Post + IG Carousel + 9:16 Reel...";
  }
  showToast(`Generating Social Media Pack & 9:16 Reel for ${slug} Ch.${ch}...`);
  try {
    const res = await apiPost("/api/social-pack/generate", {
      series_slug: slug,
      chapter: ch,
      reel_duration: dur,
      reel_start: startRaw !== "" ? parseFloat(startRaw) : null,
      overlays: overlays,
    });
    if (res.ok) {
      showToast("YouTube Post + Instagram Carousel + 9:16 Reel Ready!");
      await loadSocialPackForChapter();
    } else {
      showToast(`Social Pack Error: ${res.error || "Failed"}`);
    }
  } finally {
    if (btnEl) {
      btnEl.disabled = false;
      btnEl.innerHTML = origHtml;
    }
  }
}

async function queueSocialPackJob() {
  const slug = document.getElementById("social-series-select")?.value;
  const ch = parseInt(document.getElementById("social-chapter-select")?.value || "1", 10);
  const dur = parseFloat(document.getElementById("social-reel-dur")?.value || "45");
  const startRaw = document.getElementById("social-reel-start")?.value.trim();
  const overlays = document.getElementById("social-overlays")?.checked ?? true;

  const res = await apiPost("/api/jobs/enqueue", {
    action: "social-pack",
    series_slug: slug,
    series_name: slug,
    chapter: ch,
    reel_duration: dur,
    reel_start: startRaw !== "" ? parseFloat(startRaw) : null,
    overlays: overlays,
  });
  if (res.ok) {
    showToast(`Queued Social Media Pack for ${slug} Ch.${ch}!`);
    await refreshAll();
  }
}

function openSocialPackFolder() {
  const slug = document.getElementById("social-series-select")?.value;
  const ch = parseInt(document.getElementById("social-chapter-select")?.value || "1", 10);
  if (!slug || isNaN(ch)) return;
  const padded = String(ch).padStart(3, "0");
  openWorkspaceFolder(`data/projects/${slug}/chapter_${padded}/social`);
}

// Instagram Full-Episode & Marathon Compatibility Exporter
function loadSocialHandlesLocal() {
  const igInput = document.getElementById("ig-handle-input");
  const ytInput = document.getElementById("ig-yt-input");
  if (igInput && !igInput.value) {
    igInput.value = localStorage.getItem("manhwa_studio_ig_handle") || "";
  }
  if (ytInput && !ytInput.value) {
    ytInput.value = localStorage.getItem("manhwa_studio_yt_handle") || "";
  }
}

function saveSocialHandlesLocal() {
  const igVal = document.getElementById("ig-handle-input")?.value || "";
  const ytVal = document.getElementById("ig-yt-input")?.value || "";
  localStorage.setItem("manhwa_studio_ig_handle", igVal);
  localStorage.setItem("manhwa_studio_yt_handle", ytVal);
}

function toggleIgSourceMode() {
  const mode = document.getElementById("ig-source-mode")?.value || "chapters";
  const isMarathon = mode === "marathon";
  ["ig-series-group", "ig-ch-start-group", "ig-ch-end-group", "ig-speed-group"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.style.display = isMarathon ? "none" : "";
  });
  const mGroup = document.getElementById("ig-marathon-group");
  if (mGroup) mGroup.style.display = isMarathon ? "" : "none";
}

function openMarathonInInstagramExporter(marathonPath) {
  switchTab("tab-social");
  const modeSel = document.getElementById("ig-source-mode");
  if (modeSel) {
    modeSel.value = "marathon";
    toggleIgSourceMode();
  }
  const mSel = document.getElementById("ig-marathon-select");
  if (mSel && marathonPath) {
    mSel.value = marathonPath;
  }
  document.getElementById("ig-exports-container")?.scrollIntoView({ behavior: "smooth", block: "center" });
}

async function queueInstagramExportJob() {
  const mode = document.getElementById("ig-source-mode")?.value || "chapters";
  const maxMinutes = parseFloat(document.getElementById("ig-max-minutes")?.value || "18");
  const aspect = document.getElementById("ig-aspect")?.value || "9x16";
  const ytHandle = (document.getElementById("ig-yt-input")?.value || "").trim();
  const igHandle = (document.getElementById("ig-handle-input")?.value || "").trim();

  const payload = {
    action: "instagram-export",
    max_minutes: maxMinutes,
    aspect: aspect,
    yt_handle: ytHandle,
    ig_handle: igHandle,
  };

  if (mode === "marathon") {
    const marathonFile = document.getElementById("ig-marathon-select")?.value || "";
    if (!marathonFile) {
      showToast("No marathon movie selected");
      return;
    }
    payload.marathon_file = marathonFile;
    payload.series_slug = "";
    payload.series_name = marathonFile;
  } else {
    const slug = document.getElementById("ig-series-select")?.value || "";
    const chStart = parseInt(document.getElementById("ig-ch-start")?.value || "1", 10);
    const chEnd = parseInt(document.getElementById("ig-ch-end")?.value || String(chStart), 10);
    const speed = parseFloat(document.getElementById("ig-speed")?.value || "1.25");
    if (!slug) {
      showToast("Please select a series");
      return;
    }
    payload.series_slug = slug;
    payload.series_name = slug;
    payload.chapter_start = chStart;
    payload.chapter_end = chEnd;
    payload.speed = speed;
  }

  const res = await apiPost("/api/jobs/enqueue", payload);
  if (res.ok) {
    showToast("Queued Instagram 9:16 Export in background render lane!");
    await refreshAll();
  } else {
    showToast(`Instagram Export Error: ${res.error || "Failed"}`);
  }
}

function renderInstagramExports() {
  const container = document.getElementById("ig-exports-container");
  if (!container) return;
  const groups = appState.instagram_exports || [];

  const igPubSel = document.getElementById("ig-publish-folder");
  if (igPubSel) {
    const curVal = igPubSel.value;
    const html = groups.map((g) => `<option value="${escapeHtml(g.folder)}">${escapeHtml(g.folder)} (${g.videos.length} parts)</option>`).join("");
    if (igPubSel.innerHTML !== html) {
      igPubSel.innerHTML = html;
      if (curVal && groups.some((g) => g.folder === curVal)) {
        igPubSel.value = curVal;
      }
    }
  }
  if (groups.length === 0) {
    container.innerHTML = `<div class="stat-box" style="color:var(--text-muted); font-size:12.5px; text-align:center;">No Instagram exports in <code>exports/instagram/</code> yet. Queue an export above!</div>`;
    return;
  }

  container.innerHTML = groups
    .map(
      (g, gIdx) => `
      <div class="stat-box" style="margin-bottom:12px;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:10px;">
          <div>
            <strong style="font-size:14px; color:#f472b6;">&#128247; ${escapeHtml(g.folder)}</strong>
            <span class="badge badge-rendered" style="margin-left:8px;">${g.videos.length} video(s)</span>
          </div>
          <div style="display:flex; gap:8px; flex-wrap:wrap;">
            <button class="btn btn-sm btn-cyan" onclick="regenerateInstagramGuide('${escapeJs(g.folder)}', this)">&#128260; Regenerate AI Guide</button>
            <button class="btn btn-sm" onclick="openWorkspaceFolder('${escapeJs(g.dir_path)}')">&#128193; Open Folder</button>
          </div>
        </div>
        <div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(290px, 1fr)); gap:8px;">
          ${g.videos
            .map(
              (v) => `
            <div style="background:rgba(255,255,255,0.03); border:1px solid var(--border); border-radius:6px; padding:8px 10px; display:flex; justify-content:space-between; align-items:center; gap:8px;">
              <div style="min-width:0;">
                <div style="font-size:12.5px; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="${escapeHtml(v.filename)}">${escapeHtml(v.filename)}</div>
                <div style="font-size:11px; color:var(--text-secondary);">${v.size_mb} MB &bull; 9:16 Ready</div>
              </div>
              <button class="btn btn-sm btn-primary" onclick="openVideoModal('${escapeJs(v.path)}', '${escapeJs(v.filename)}')">&#9654; Watch</button>
            </div>`
            )
            .join("")}
        </div>
        ${
          g.has_guide
            ? `<details style="margin-top:10px;">
                <summary style="cursor:pointer; font-size:12.5px; color:var(--accent-cyan);">&#128203; Instagram Publishing Guide (Titles, Captions, Hashtags &amp; YT/IG CTAs)</summary>
                <div style="margin-top:6px;">
                  <button class="btn btn-sm" style="margin-bottom:6px;" onclick="copyText('ig-guide-${gIdx}')">Copy Full Guide</button>
                  <pre class="cmd-preview" id="ig-guide-${gIdx}" style="white-space:pre-wrap; max-height:360px; overflow-y:auto;">${escapeHtml(g.guide_text)}</pre>
                </div>
              </details>`
            : ""
        }
      </div>`
    )
    .join("");
}

async function regenerateInstagramGuide(folderName, btnEl) {
  const ytHandle = (document.getElementById("ig-yt-input")?.value || "").trim();
  const igHandle = (document.getElementById("ig-handle-input")?.value || "").trim();
  const origHtml = btnEl ? btnEl.innerHTML : "";
  if (btnEl) {
    btnEl.disabled = true;
    btnEl.textContent = "⏳ Generating AI Guide...";
  }
  try {
    const res = await apiPost("/api/instagram-guide/regenerate", {
      folder: folderName,
      yt_handle: ytHandle,
      ig_handle: igHandle,
    });
    if (res.ok) {
      showToast(`Regenerated dynamic Instagram Guide for ${folderName}!`);
      await refreshAll();
    } else {
      showToast(`Guide Error: ${res.error || "Failed"}`);
    }
  } finally {
    if (btnEl) {
      btnEl.disabled = false;
      btnEl.innerHTML = origHtml;
    }
  }
}

// Queue & Console Tab
function renderQueueTab() {
  const q = appState.queue || {};
  const jobs = q.jobs || [];
  const container = document.getElementById("queue-jobs-list");
  document.getElementById("btn-pause-queue").textContent = q.paused ? "Resume Queue" : "Pause Queue";

  if (jobs.length === 0) {
    container.innerHTML = `<p style="color:var(--text-secondary); font-size:13px;">No jobs in the queue yet. Use the Matrix or Workflow Builder to add jobs.</p>`;
    return;
  }

  if (!activeJobLogId && jobs.length > 0) {
    const running = jobs.find((j) => j.status === "running") || jobs[0];
    activeJobLogId = running.job_id;
  }

  container.innerHTML = jobs
    .map((j) => {
      let badgeCls = "";
      if (j.status === "running") badgeCls = "badge-running";
      else if (j.status === "succeeded") badgeCls = "badge-rendered";
      else if (j.status === "queued") badgeCls = "badge-inbox";
      else badgeCls = "badge";

      const isSelected = j.job_id === activeJobLogId;
      const borderStyle = isSelected ? "border-color: var(--accent-cyan);" : "";

      return `
        <div class="stat-box" style="margin-bottom:10px; cursor:pointer; ${borderStyle}" onclick="selectJobLogs('${escapeJs(
        j.job_id
      )}')">
          <div style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
            <strong>${escapeHtml(j.title)}</strong>
            <span class="badge ${badgeCls}">${escapeHtml(j.status.toUpperCase())}</span>
          </div>
          <div style="font-size:11.5px; color:var(--text-secondary); font-family:monospace; margin-top:4px; word-break:break-all;">
            ${escapeHtml(j.display_command)}
          </div>
          <div style="display:flex; justify-content:space-between; align-items:center; margin-top:8px; font-size:11.5px; color:var(--text-muted);">
            <span>Lane: ${escapeHtml(j.lane.toUpperCase())} ${j.pid ? `&bull; PID ${j.pid}` : ""}</span>
            ${
              j.status === "queued" || j.status === "running"
                ? `<button class="btn btn-sm" onclick="event.stopPropagation(); cancelJob('${escapeJs(
                    j.job_id
                  )}')">Cancel</button>`
                : ""
            }
          </div>
        </div>
      `;
    })
    .join("");
}

async function selectJobLogs(jobId) {
  activeJobLogId = jobId;
  renderQueueTab();
  await pollActiveJobLogs(jobId);
}

async function pollActiveJobLogs(jobId) {
  try {
    const info = await apiGet(`/api/job-logs?job_id=${encodeURIComponent(jobId)}`);
    if (info && info.logs) {
      document.getElementById("console-job-title").textContent = `— ${info.title} (${info.status.toUpperCase()})`;
      const box = document.getElementById("job-console-box");
      const wasAtBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
      box.textContent = info.logs.join("\n") || "Waiting for output...";
      if (wasAtBottom) {
        box.scrollTop = box.scrollHeight;
      }
    }
  } catch (err) {
    // ignore
  }
}

function scrollConsoleBottom() {
  const box = document.getElementById("job-console-box");
  box.scrollTop = box.scrollHeight;
}

async function cancelJob(jobId) {
  await apiPost("/api/jobs/cancel", { job_id: jobId });
  showToast("Job cancelled");
  await refreshAll();
}

async function clearFinishedJobs() {
  const res = await apiPost("/api/jobs/clear", {});
  showToast(`Cleared ${res.removed || 0} finished jobs`);
  await refreshAll();
}

async function togglePauseQueue() {
  const nextPaused = !(appState.queue && appState.queue.paused);
  await apiPost("/api/jobs/settings", { paused: nextPaused });
  showToast(nextPaused ? "Job Queue Paused" : "Job Queue Resumed");
  await refreshAll();
}

async function toggleWaitExternal(checked) {
  await apiPost("/api/jobs/settings", { wait_for_external: checked });
  showToast(checked ? "Safe wait for terminal jobs enabled" : "Parallel override enabled");
}

// Modals & Utilities
function openVideoModal(relPath, title) {
  const modal = document.getElementById("video-modal");
  const player = document.getElementById("modal-video-player");
  document.getElementById("modal-video-title").textContent = title || relPath;
  player.src = `/api/media?path=${encodeURIComponent(relPath)}`;
  modal.classList.add("open");
  player.play().catch(() => {});
}

function closeVideoModal() {
  const modal = document.getElementById("video-modal");
  const player = document.getElementById("modal-video-player");
  player.pause();
  player.src = "";
  modal.classList.remove("open");
}

async function openWorkspaceFolder(relPath) {
  await apiPost("/api/open-folder", { path: relPath });
}

function copyText(elementId) {
  const el = document.getElementById(elementId);
  if (!el) return;
  const text = el.value !== undefined ? el.value : el.textContent;
  navigator.clipboard.writeText(text).then(() => showToast("Copied to clipboard!"));
}

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeJs(str) {
  return String(str ?? "").replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

// ==========================================
// YOUTUBE BATCH UPLOAD & STAGGERED SCHEDULER
// ==========================================

async function loadYouTubeAuthStatus() {
  const badge = document.getElementById("yt-auth-badge");
  if (!badge) return;
  try {
    const res = await fetch("/api/youtube/status");
    const data = await res.json();
    if (!data.packages_installed) {
      badge.textContent = "Install google-api-python-client";
      badge.className = "badge badge-warning";
    } else if (data.token_connected) {
      badge.textContent = "OAuth Connected";
      badge.className = "badge badge-rendered";
    } else if (data.client_secrets_found) {
      badge.textContent = "Run: manhwa-studio yt-auth";
      badge.className = "badge badge-warning";
    } else {
      badge.textContent = "Add config/youtube_client_secrets.json";
      badge.className = "badge";
    }
    renderYouTubeHistory(data.history || []);
  } catch (e) {
    badge.textContent = "YouTube Status Unavailable";
  }
}

function renderYouTubeHistory(rows) {
  const container = document.getElementById("yt-history-container");
  if (!container) return;
  if (!rows || rows.length === 0) {
    container.innerHTML = `<div class="stat-box">No YouTube uploads recorded yet in <code>data/youtube_upload_history.json</code>.</div>`;
    return;
  }
  container.innerHTML = `
    <div style="display:grid; gap:6px; max-height:260px; overflow-y:auto;">
      ${rows
        .map((r) => {
          const isShort = r.video_type === "short";
          const typeBadge = isShort
            ? `<span class="badge" style="background:rgba(244,114,182,0.18); color:#f472b6;">Short</span>`
            : `<span class="badge badge-rendered">Full</span>`;
          return `
            <div class="stat-box" style="display:flex; justify-content:space-between; align-items:center; gap:10px; padding:6px 10px;">
              <div style="min-width:0;">
                ${typeBadge}
                <strong style="margin-left:6px;">${escapeHtml(r.series_slug)} Ch.${r.chapter}</strong>
                <span style="color:var(--text-secondary); margin-left:6px;">${escapeHtml(r.title)}</span>
              </div>
              <div style="text-align:right; flex-shrink:0;">
                <span style="color:var(--text-muted);">${escapeHtml(r.publish_at_local)}</span>
                ${r.url ? `<a href="${escapeHtml(r.url)}" target="_blank" style="margin-left:8px; color:var(--accent-cyan);">Open</a>` : ""}
              </div>
            </div>`;
        })
        .join("")}
    </div>
  `;
}

function _getYouTubeBatchPayload() {
  const slug = document.getElementById("yt-batch-series")?.value || "";
  const chapters = document.getElementById("yt-batch-chapters")?.value?.trim() || "";
  const count = parseInt(document.getElementById("yt-batch-count")?.value || "3", 10);
  const speed = parseFloat(document.getElementById("yt-batch-speed")?.value || "1.25");
  const slots = document.getElementById("yt-batch-slots")?.value?.trim() || "10:00,16:00,21:00";
  const intervalRaw = document.getElementById("yt-batch-interval")?.value?.trim() || "";
  const startAt = document.getElementById("yt-batch-start")?.value?.trim() || "";
  const playlistId = document.getElementById("yt-batch-playlist")?.value?.trim() || "";
  return {
    series_slug: slug,
    series_name: slug,
    chapters,
    count,
    speed,
    slots,
    interval_hours: intervalRaw ? parseFloat(intervalRaw) : null,
    start_at: startAt,
    playlist_id: playlistId,
  };
}

async function previewYouTubeBatch() {
  const container = document.getElementById("yt-batch-preview-container");
  const payload = _getYouTubeBatchPayload();
  if (!payload.series_slug) {
    showToast("Please select a series first.");
    return;
  }
  if (container) container.innerHTML = `<div class="stat-box">Generating schedule &amp; SEO metadata preview...</div>`;

  const res = await apiPost("/api/youtube/preview", payload);
  if (!res.ok) {
    if (container) container.innerHTML = `<div class="stat-box" style="color:#f87171;">Preview Error: ${escapeHtml(res.error || "Failed")}</div>`;
    return;
  }
  const items = res.items || [];
  if (items.length === 0) {
    if (container) container.innerHTML = `<div class="stat-box">No pending rendered chapters found for <code>${escapeHtml(payload.series_slug)}</code>.</div>`;
    return;
  }

  container.innerHTML = `
    <div style="display:grid; gap:8px;">
      ${items
        .map(
          (it) => `
        <div class="stat-box" style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px;">
          <div style="min-width:0;">
            <div style="font-weight:600; color:var(--accent-cyan);">Ch.${it.chapter} &bull; ${escapeHtml(it.title)}</div>
            <div style="font-size:11.5px; color:var(--text-secondary); margin-top:3px;">
              Video: <code>${escapeHtml(it.video_path)}</code> ${it.thumbnail_path ? "&bull; Custom Thumbnail Ready" : ""}
            </div>
          </div>
          <div style="text-align:right; flex-shrink:0;">
            <span class="badge badge-rendered">${escapeHtml(it.publish_at_local)}</span>
            <div style="font-size:10.5px; color:var(--text-muted); margin-top:2px;">UTC: ${escapeHtml(it.publish_at_utc)}</div>
          </div>
        </div>`
        )
        .join("")}
    </div>
  `;
}

async function queueYouTubeBatchUpload() {
  const payload = _getYouTubeBatchPayload();
  if (!payload.series_slug) {
    showToast("Please select a series first.");
    return;
  }
  payload.action = "yt-upload-batch";
  payload.dry_run = false;
  const res = await apiPost("/api/jobs/enqueue", payload);
  if (res.ok) {
    showToast("Queued YouTube Batch Upload & Schedule job!");
    await refreshAll();
  } else {
    showToast(`YouTube Batch Error: ${res.error || "Failed"}`);
  }
}

function _getYouTubeShortsPayload() {
  const slug = document.getElementById("yt-shorts-series")?.value || "";
  const chapters = document.getElementById("yt-shorts-chapters")?.value?.trim() || "";
  const count = parseInt(document.getElementById("yt-shorts-count")?.value || "3", 10);
  const duration = parseFloat(document.getElementById("yt-shorts-duration")?.value || "90");
  const slots = document.getElementById("yt-shorts-slots")?.value?.trim() || "12:00,18:00,22:00";
  const intervalRaw = document.getElementById("yt-shorts-interval")?.value?.trim() || "";
  const startAt = document.getElementById("yt-shorts-start")?.value?.trim() || "";
  const playlistId = document.getElementById("yt-shorts-playlist")?.value?.trim() || "";
  return {
    series_slug: slug,
    series_name: slug,
    chapters,
    count,
    duration,
    slots,
    interval_hours: intervalRaw ? parseFloat(intervalRaw) : null,
    start_at: startAt,
    playlist_id: playlistId,
  };
}

async function previewYouTubeShortsBatch() {
  const container = document.getElementById("yt-shorts-preview-container");
  const payload = _getYouTubeShortsPayload();
  if (!payload.series_slug) {
    showToast("Please select a series first.");
    return;
  }
  if (container) container.innerHTML = `<div class="stat-box">Generating YouTube Shorts schedule preview...</div>`;

  const res = await apiPost("/api/youtube/shorts-preview", payload);
  if (!res.ok) {
    if (container) container.innerHTML = `<div class="stat-box" style="color:#f87171;">Preview Error: ${escapeHtml(res.error || "Failed")}</div>`;
    return;
  }
  const items = res.items || [];
  if (items.length === 0) {
    if (container) container.innerHTML = `<div class="stat-box">No pending 9:16 Shorts found for <code>${escapeHtml(payload.series_slug)}</code>.</div>`;
    return;
  }

  container.innerHTML = `
    <div style="display:grid; gap:8px;">
      ${items
        .map(
          (it) => `
        <div class="stat-box" style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px;">
          <div style="min-width:0;">
            <div style="font-weight:600; color:#f472b6;">Short Ch.${it.chapter} &bull; ${escapeHtml(it.title)}</div>
            <div style="font-size:11.5px; color:var(--text-secondary); margin-top:3px;">
              Video: <code>${escapeHtml(it.video_path)}</code>
            </div>
          </div>
          <div style="text-align:right; flex-shrink:0;">
            <span class="badge badge-rendered">${escapeHtml(it.publish_at_local)}</span>
            <div style="font-size:10.5px; color:var(--text-muted); margin-top:2px;">UTC: ${escapeHtml(it.publish_at_utc)}</div>
          </div>
        </div>`
        )
        .join("")}
    </div>
  `;
}

async function queueYouTubeShortsBatchUpload() {
  const payload = _getYouTubeShortsPayload();
  if (!payload.series_slug) {
    showToast("Please select a series first.");
    return;
  }
  payload.action = "yt-upload-shorts";
  payload.dry_run = false;
  const res = await apiPost("/api/jobs/enqueue", payload);
  if (res.ok) {
    showToast("Queued YouTube Shorts Batch Upload & Schedule job!");
    await refreshAll();
  } else {
    showToast(`YouTube Shorts Batch Error: ${res.error || "Failed"}`);
  }
}

function _getYouTubeMarathonPayload() {
  const marathonFile = document.getElementById("yt-marathon-select")?.value || "";
  const publishAt = document.getElementById("yt-marathon-publish-at")?.value?.trim() || "";
  const playlistId = document.getElementById("yt-marathon-playlist")?.value?.trim() || "";
  return {
    marathon_file: marathonFile,
    publish_at: publishAt,
    playlist_id: playlistId,
    series_slug: "",
    series_name: marathonFile,
  };
}

async function previewYouTubeMarathon() {
  const container = document.getElementById("yt-marathon-preview-container");
  const payload = _getYouTubeMarathonPayload();
  if (!payload.marathon_file) {
    showToast("Please select a Marathon Movie first.");
    return;
  }
  if (container) container.innerHTML = `<div class="stat-box">Generating Marathon SEO metadata &amp; schedule preview...</div>`;

  const res = await apiPost("/api/youtube/marathon-preview", payload);
  if (!res.ok) {
    if (container) container.innerHTML = `<div class="stat-box" style="color:#f87171;">Preview Error: ${escapeHtml(res.error || "Failed")}</div>`;
    return;
  }
  const items = res.items || [];
  if (items.length === 0) {
    if (container) container.innerHTML = `<div class="stat-box">This Marathon Movie is already in upload history.</div>`;
    return;
  }
  const it = items[0];
  container.innerHTML = `
    <div class="stat-box" style="display:flex; justify-content:space-between; align-items:flex-start; gap:12px;">
      <div style="min-width:0;">
        <div style="font-weight:600; color:var(--accent-amber);">${escapeHtml(it.title)}</div>
        <div style="font-size:11.5px; color:var(--text-secondary); margin-top:4px;">
          Timeline chapters: <strong>${res.timestamps_count || 0}</strong> &bull;
          Hashtags: <code>${escapeHtml((res.hashtags || []).join(" "))}</code>
          ${it.thumbnail_path ? "&bull; Thumbnail Ready" : ""}
        </div>
      </div>
      <div style="text-align:right; flex-shrink:0;">
        <span class="badge badge-rendered">${escapeHtml(it.publish_at_local)}</span>
        <div style="font-size:10.5px; color:var(--text-muted); margin-top:2px;">UTC: ${escapeHtml(it.publish_at_utc)}</div>
      </div>
    </div>
  `;
}

async function queueYouTubeMarathonUpload() {
  const payload = _getYouTubeMarathonPayload();
  if (!payload.marathon_file) {
    showToast("Please select a Marathon Movie first.");
    return;
  }
  payload.action = "yt-upload-marathon";
  payload.dry_run = false;
  const res = await apiPost("/api/jobs/enqueue", payload);
  if (res.ok) {
    showToast("Queued YouTube Marathon Upload & Schedule job!");
    await refreshAll();
  } else {
    showToast(`YouTube Marathon Error: ${res.error || "Failed"}`);
  }
}

// ==========================================
// INSTAGRAM GRAPH API AUTO-PUBLISHER
// ==========================================

async function loadInstagramAuthStatus() {
  const badge = document.getElementById("ig-auth-badge");
  if (!badge) return;
  try {
    const res = await fetch("/api/instagram/status");
    const data = await res.json();
    if (!data.credentials_configured) {
      badge.textContent = "Run: manhwa-studio ig-auth";
      badge.className = "badge badge-warning";
    } else if (!data.cloudflared_installed) {
      badge.textContent = "IG Connected (Install cloudflared or set IG_VIDEO_BASE_URL)";
      badge.className = "badge badge-warning";
    } else {
      badge.textContent = "IG Graph API + Tunnel Ready";
      badge.className = "badge badge-rendered";
    }
  } catch (e) {
    badge.textContent = "IG Status Unavailable";
  }
}

async function previewInstagramPublish() {
  const container = document.getElementById("ig-publish-preview-container");
  const folder = document.getElementById("ig-publish-folder")?.value || "";
  const count = parseInt(document.getElementById("ig-publish-count")?.value || "2", 10);
  if (!folder) {
    showToast("Please select an Instagram export folder first.");
    return;
  }
  if (container) container.innerHTML = `<div class="stat-box">Loading pending Reels &amp; captions...</div>`;

  const res = await apiPost("/api/instagram/preview", { folder, count });
  if (!res.ok) {
    if (container) container.innerHTML = `<div class="stat-box" style="color:#f87171;">Preview Error: ${escapeHtml(res.error || "Failed")}</div>`;
    return;
  }
  const items = res.items || [];
  if (items.length === 0) {
    if (container) container.innerHTML = `<div class="stat-box">All Reels in <code>${escapeHtml(folder)}</code> are already published.</div>`;
    return;
  }
  container.innerHTML = `
    <div style="display:grid; gap:8px;">
      ${items
        .map(
          (it) => `
        <div class="stat-box">
          <div style="font-weight:600; color:#f472b6;">${escapeHtml(it.filename)}</div>
          <div style="font-size:11.5px; color:var(--text-secondary); margin-top:3px;">${escapeHtml(it.caption_preview)}...</div>
        </div>`
        )
        .join("")}
    </div>
  `;
}

async function queueInstagramPublish() {
  const folder = document.getElementById("ig-publish-folder")?.value || "";
  const count = parseInt(document.getElementById("ig-publish-count")?.value || "2", 10);
  const delayMinutes = parseFloat(document.getElementById("ig-publish-delay")?.value || "0");
  if (!folder) {
    showToast("Please select an Instagram export folder first.");
    return;
  }
  const res = await apiPost("/api/jobs/enqueue", {
    action: "ig-upload-batch",
    folder,
    count,
    delay_minutes: delayMinutes,
    dry_run: false,
  });
  if (res.ok) {
    showToast("Queued Instagram Reels Auto-Publish job!");
    await refreshAll();
  } else {
    showToast(`Instagram Publish Error: ${res.error || "Failed"}`);
  }
}

// Initialize Dashboard
window.addEventListener("DOMContentLoaded", () => {
  updateInboxPreview();
  updateProRenderPreview();
  updateMarathonPreview();
  updateSpeedVideoPreview();
  refreshAll();
  loadAllVoiceProfiles();
  loadStudioEnvConfig();
  loadGeminiKeysList();
  loadYouTubeAuthStatus();
  loadInstagramAuthStatus();
  setInterval(() => refreshAll(false), 4000);
});

