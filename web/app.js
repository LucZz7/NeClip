/* NeClip frontend — screen router, auth, jobs, progress, results.
   All API calls use same-origin relative URLs. */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var STAGE_ORDER = ["source", "transcribe", "highlights", "clip"];

  var state = {
    numClips: 3,
    file: null,
    jobId: null,
    jobLabel: "",
    pollTimer: null,
    statusTimer: null,
    logCount: 0,
    channel: null
  };

  /* ---------- helpers ---------- */
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function toast(msg) {
    var t = $("toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(t._h);
    t._h = setTimeout(function () { t.classList.remove("show"); }, 2800);
  }

  function show(name) {
    ["auth", "create", "progress", "results"].forEach(function (s) {
      $("screen-" + s).classList.toggle("active", s === name);
      $("screen-" + s).hidden = s !== name;
    });
    $("topbar").hidden = (name === "auth");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function showError(elId, msg) {
    var el = $(elId);
    el.textContent = msg;
    el.hidden = !msg;
  }

  async function api(path, opts) {
    var res;
    try {
      res = await fetch(path, opts);
    } catch (e) {
      return { ok: false, status: 0, data: null, offline: true };
    }
    var data = null;
    try { data = await res.json(); } catch (e) { /* non-JSON */ }
    return { ok: res.ok, status: res.status, data: data };
  }

  function serverDown() {
    return "Could not reach the NeClip server. Start the backend, then retry.";
  }

  /* ---------- auth ---------- */
  async function refreshStatus() {
    var r = await api("/api/youtube/status");
    if (r.offline) return { offline: true };
    if (!r.ok || !r.data) return null;
    return r.data;
  }

  async function enterApp(status) {
    state.channel = status.channel || null;
    var label = state.channel && state.channel.title
      ? "Connected · " + state.channel.title
      : "Connected";
    $("statusText").textContent = label;
    show("create");
    loadJobs();
  }

  function startStatusPolling() {
    stopStatusPolling();
    state.statusTimer = setInterval(async function () {
      var s = await refreshStatus();
      if (s && s.logged_in) {
        stopStatusPolling();
        $("authCode").hidden = true;
        $("authMain").hidden = false;
        toast("YouTube connected");
        enterApp(s);
      }
    }, 4000);
  }

  function stopStatusPolling() {
    if (state.statusTimer) { clearInterval(state.statusTimer); state.statusTimer = null; }
  }

  async function connectYouTube() {
    showError("authError", "");
    var btn = $("btnConnect");
    btn.disabled = true;

    var res;
    try {
      // Ask for manual redirect handling so we can detect the flow type.
      res = await fetch("/api/youtube/login", { redirect: "manual" });
    } catch (e) {
      btn.disabled = false;
      showError("authError", "Could not reach the server. Check your connection and try again.");
      return;
    }

    // Case 1: backend not configured -> JSON error (HTTP 400).
    if (res.status === 400) {
      btn.disabled = false;
      var err = null;
      try { err = await res.json(); } catch (e) {}
      showError("authError", (err && err.error) || "YouTube is not configured yet.");
      return;
    }

    // Case 2: OAuth redirect flow (what this backend currently serves).
    // fetch(manual) surfaces cross-origin redirects as opaqueredirect.
    if (res.type === "opaqueredirect" || (res.status >= 300 && res.status < 400)) {
      window.location.href = "/api/youtube/login";
      return;
    }

    // Case 3: device-flow JSON payload {user_code, verification_url, ...}
    var data = null;
    try { data = await res.json(); } catch (e) {}
    btn.disabled = false;

    if (data && (data.user_code || data.verification_url)) {
      $("deviceCode").textContent = data.user_code || "";
      $("authMain").hidden = true;
      $("authCode").hidden = false;
      startStatusPolling();
      return;
    }

    // No redirect and no device payload: the server endpoint is missing.
    showError("authError", serverDown());
  }

  /* ---------- create screen ---------- */
  function initPills() {
    $("clipPills").addEventListener("click", function (e) {
      var b = e.target.closest(".pill");
      if (!b) return;
      state.numClips = parseInt(b.dataset.n, 10) || 3;
      Array.prototype.forEach.call(this.querySelectorAll(".pill"), function (p) {
        p.setAttribute("aria-pressed", p === b ? "true" : "false");
      });
    });
  }

  function initDropzone() {
    var dz = $("dropzone"), fi = $("fileInput");
    dz.addEventListener("click", function () { fi.click(); });
    dz.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fi.click(); }
    });
    fi.addEventListener("change", function () { setFile(fi.files[0] || null); });
    ["dragover", "dragenter"].forEach(function (ev) {
      dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.add("dragover"); });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.remove("dragover"); });
    });
    dz.addEventListener("drop", function (e) {
      var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      setFile(f || null);
    });
  }

  function setFile(f) {
    state.file = f || null;
    var lbl = $("dzFile");
    if (state.file) {
      lbl.textContent = state.file.name;
      lbl.hidden = false;
      $("urlInput").value = "";
    } else {
      lbl.hidden = true;
    }
  }

  async function generateClips() {
    showError("formError", "");
    var url = $("urlInput").value.trim();
    var btn = $("btnGenerate");

    if (!state.file && !url) {
      showError("formError", "Paste a YouTube link or upload a video file first.");
      return;
    }

    btn.disabled = true;
    var r;
    try {
      if (state.file) {
        var fd = new FormData();
        fd.append("file", state.file, state.file.name);
        fd.append("num_clips", String(state.numClips));
        r = await api("/api/jobs/upload", { method: "POST", body: fd });
      } else {
        var fd2 = new FormData();
        fd2.append("source", url);
        fd2.append("num_clips", String(state.numClips));
        r = await api("/api/jobs", { method: "POST", body: fd2 });
      }
    } catch (e) {
      btn.disabled = false;
      showError("formError", "Could not reach the server. Try again.");
      return;
    }
    btn.disabled = false;

    if (!r.ok || !r.data || !r.data.job_id) {
      showError("formError", (r.data && r.data.error) || "Could not start the job.");
      return;
    }
    state.jobLabel = state.file ? state.file.name : url;
    openProgress(r.data.job_id, state.jobLabel);
  }

  /* ---------- jobs history ---------- */
  function badgeClass(status) {
    return "job-badge " + (status || "queued");
  }

  async function loadJobs() {
    var list = $("jobsList");
    var r = await api("/api/jobs");
    if (!r.ok || !r.data || !Array.isArray(r.data.jobs)) {
      list.innerHTML = '<p class="empty-note">Could not load jobs.</p>';
      return;
    }
    var jobs = r.data.jobs;
    if (!jobs.length) {
      list.innerHTML = '<p class="empty-note">No jobs yet. Your clipping jobs will appear here.</p>';
      return;
    }
    list.innerHTML = "";
    jobs.slice(0, 12).forEach(function (j) {
      var b = document.createElement("button");
      b.className = "job-row";
      b.innerHTML =
        '<span class="job-label">' + esc(j.label || j.id) + "</span>" +
        '<span class="' + badgeClass(j.status) + '">' + esc(j.status || "queued") + "</span>";
      b.addEventListener("click", function () { openJob(j.id); });
      list.appendChild(b);
    });
  }

  async function openJob(jobId) {
    var r = await api("/api/jobs/" + encodeURIComponent(jobId));
    if (!r.ok || !r.data) { toast("Job not found"); return; }
    var j = r.data;
    if (j.status === "done" && j.result) {
      renderResults(j.id, j.result);
    } else if (j.status === "failed") {
      toast("Job failed: " + (j.error || "unknown error"));
    } else {
      openProgress(j.id, j.label || jobId);
    }
  }

  /* ---------- progress ---------- */
  function resetStages() {
    Array.prototype.forEach.call(document.querySelectorAll(".stage"), function (el) {
      el.classList.remove("active", "done");
      el.querySelector(".stage-state").innerHTML = '<span class="spinner"></span>';
    });
  }

  function updateStages(stage, status) {
    var idx = STAGE_ORDER.indexOf(stage);
    Array.prototype.forEach.call(document.querySelectorAll(".stage"), function (el) {
      var s = el.dataset.stage;
      var si = STAGE_ORDER.indexOf(s);
      var st = el.querySelector(".stage-state");
      el.classList.remove("active", "done");
      if (status === "done" || si < idx || (status === "done")) {
        el.classList.add("done");
        st.innerHTML = '<svg class="ic check"><use href="#icon-check"/></svg>';
      } else if (s === stage && (status === "running" || status === "queued")) {
        el.classList.add("active");
        st.innerHTML = '<span class="spinner"></span>';
      } else {
        st.innerHTML = '<span class="spinner" style="opacity:.25"></span>';
      }
    });
  }

  function appendLogs(logs) {
    var box = $("logBox");
    (logs || []).slice(state.logCount).forEach(function (line) {
      var d = document.createElement("div");
      d.textContent = line;
      box.appendChild(d);
    });
    state.logCount = (logs || []).length;
    box.scrollTop = box.scrollHeight;
  }

  function openProgress(jobId, label) {
    stopPolling();
    state.jobId = jobId;
    state.logCount = 0;
    $("logBox").innerHTML = "";
    $("progressTitle").textContent = label ? ("Creating Shorts — " + label).slice(0, 60) : "Creating your Shorts";
    showError("progressError", "");
    resetStages();
    show("progress");
    pollJob();
    state.pollTimer = setInterval(pollJob, 2000);
  }

  function stopPolling() {
    if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
  }

  async function pollJob() {
    if (!state.jobId) return;
    var r = await api("/api/jobs/" + encodeURIComponent(state.jobId));
    if (!r.ok || !r.data) return;
    var j = r.data;

    $("progressFill").style.width = Math.min(100, j.progress || 0) + "%";
    $("progressPct").textContent = Math.min(100, j.progress || 0) + "%";
    $("progressLabel").textContent = j.stage_label || "Working…";
    updateStages(j.stage, j.status);
    appendLogs(j.log);

    if (j.status === "done") {
      stopPolling();
      updateStages(null, "done");
      $("progressFill").style.width = "100%";
      $("progressPct").textContent = "100%";
      setTimeout(function () { renderResults(j.id, j.result || { shorts: [] }); }, 600);
    } else if (j.status === "failed") {
      stopPolling();
      showError("progressError", j.error || "The job failed. Try again with a different video.");
    }
  }

  /* ---------- results ---------- */
  function renderResults(jobId, result) {
    stopPolling();
    var grid = $("clipsGrid");
    grid.innerHTML = "";
    var shorts = (result && result.shorts ? result.shorts : []).filter(function (s) { return s.file; });

    if (!shorts.length) {
      grid.innerHTML = '<div class="glass-panel"><p class="empty-note">No clips were rendered for this job.</p></div>';
    }

    shorts.forEach(function (s, i) {
      var card = document.createElement("div");
      card.className = "clip-card";

      var vwrap = document.createElement("div");
      vwrap.className = "clip-video";
      var v = document.createElement("video");
      v.src = "/api/clips/" + encodeURIComponent(jobId) + "/" + encodeURIComponent(s.file);
      v.setAttribute("playsinline", "");
      v.setAttribute("preload", "metadata");
      v.setAttribute("controls", "");
      vwrap.appendChild(v);

      var badge = document.createElement("span");
      badge.className = "score-badge";
      badge.textContent = "Viral Score: " + (s.score != null ? s.score : "—");
      vwrap.appendChild(badge);

      var body = document.createElement("div");
      body.className = "clip-body";

      var title = document.createElement("p");
      title.className = "clip-title";
      title.textContent = s.title || ("Short " + (i + 1));
      body.appendChild(title);

      if (s.hook) {
        var hook = document.createElement("p");
        hook.className = "clip-hook";
        hook.textContent = s.hook;
        body.appendChild(hook);
      }

      var titleInput = document.createElement("input");
      titleInput.className = "clip-title-input";
      titleInput.value = s.title || ("NeClip Short " + (i + 1));
      titleInput.setAttribute("aria-label", "Video title");
      body.appendChild(titleInput);

      var upBtn = document.createElement("button");
      upBtn.className = "btn btn-primary btn-block";
      upBtn.style.marginTop = "0";
      upBtn.innerHTML = '<svg class="ic"><use href="#icon-cloud"/></svg> Upload to YouTube';
      upBtn.addEventListener("click", function () { uploadClip(jobId, i, titleInput.value, upBtn, body); });
      body.appendChild(upBtn);

      card.appendChild(vwrap);
      card.appendChild(body);
      grid.appendChild(card);
    });

    show("results");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function uploadClip(jobId, idx, title, btn, body) {
    btn.disabled = true;
    var original = btn.innerHTML;
    btn.innerHTML = '<span class="spinner"></span> Uploading…';
    var fd = new FormData();
    fd.append("title", title || "");
    fd.append("description", "");
    fd.append("privacy", "public");

    var r;
    try {
      r = await api("/api/upload/" + encodeURIComponent(jobId) + "/" + idx,
                    { method: "POST", body: fd });
    } catch (e) {
      r = { ok: false, data: { error: "Could not reach the server." } };
    }

    if (r.ok && r.data && r.data.url) {
      btn.outerHTML =
        '<div class="upload-ok"><svg class="ic"><use href="#icon-check"/></svg>' +
        '<span>Uploaded — <a href="' + esc(r.data.url) + '" target="_blank" rel="noopener">Watch Short</a></span></div>';
      toast("Uploaded to YouTube");
    } else {
      btn.disabled = false;
      btn.innerHTML = original;
      toast((r.data && r.data.error) || "Upload failed");
    }
  }

  /* ---------- init ---------- */
  function handleLoginQuery() {
    var q = new URLSearchParams(window.location.search).get("login");
    if (!q) return;
    // Clean the query string without leaving the current path.
    window.history.replaceState({}, "", window.location.pathname);
    if (q === "ok") toast("YouTube connected");
    else if (q === "failed") toast("Sign-in was cancelled");
    else toast("Sign-in error — please try again");
  }

  function init() {
    handleLoginQuery();
    initPills();
    initDropzone();

    $("btnConnect").addEventListener("click", connectYouTube);
    $("btnCancelAuth").addEventListener("click", function () {
      stopStatusPolling();
      $("authCode").hidden = true;
      $("authMain").hidden = false;
      $("btnConnect").disabled = false;
    });
    $("btnGenerate").addEventListener("click", generateClips);
    $("btnRefreshJobs").addEventListener("click", loadJobs);
    $("btnBackCreate").addEventListener("click", function () { stopPolling(); show("create"); loadJobs(); });
    $("btnCreateMore").addEventListener("click", function () { show("create"); loadJobs(); });

    show("auth");
    refreshStatus().then(function (s) {
      if (s && s.offline) {
        showError("authError", serverDown());
      } else if (s && s.logged_in) {
        enterApp(s);
      }
    });

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("sw.js").catch(function () {});
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
