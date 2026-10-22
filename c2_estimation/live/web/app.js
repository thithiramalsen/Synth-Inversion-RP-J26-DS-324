"use strict";
const $ = (id) => document.getElementById(id);
let active = null, result = null, resultJob = null, selectedControl = 0, chosenFile = null;
let busy = false, pollTimer = null;
const requestHeaders = {"X-C2-Request": "1"};
const fmt = (n, digits = 4) => Number(n).toFixed(digits);
const pct = (n) => `${fmt(n * 100, 1)}%`;

function message(text) {
  $("message").textContent = text || "";
  $("message").hidden = !text;
}
async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Request failed. Try again.");
  return data;
}
function setBusy(value) {
  busy = value;
  $("analyse").disabled = value || !chosenFile;
  $("audio-file").disabled = value;
  document.querySelectorAll("[data-example]").forEach(b => { b.disabled = value; });
}
function fileChosen(file) {
  if (busy || !file) return;
  chosenFile = file;
  $("file-label").textContent = file.name;
  $("analyse").disabled = false;
  message("");
}
function filesUrl(name, attachment = false) {
  return `/api/jobs/${resultJob}/files/${encodeURIComponent(name)}${attachment ? "?attachment=true" : ""}`;
}
function stopAudio() {
  document.querySelectorAll("audio").forEach(a => a.pause());
}
document.addEventListener("play", event => {
  if (event.target.tagName === "AUDIO") {
    document.querySelectorAll("audio").forEach(a => { if (a !== event.target) a.pause(); });
  }
}, true);

function readHistory() {
  try { return JSON.parse(localStorage.getItem("c2-live-history") || "[]"); }
  catch { return []; }
}
function remember(job, name) {
  try {
    localStorage.setItem("c2-live-history", JSON.stringify(
      [{id:job, name}, ...readHistory().filter(x => x.id !== job)].slice(0, 6)));
  } catch { /* The result URL still works when storage is unavailable. */ }
  renderHistory();
}
function renderHistory() {
  const entries = readHistory();
  $("recent").hidden = entries.length === 0;
  $("recent-links").replaceChildren();
  for (const item of entries) {
    const button = document.createElement("button");
    button.className = "secondary"; button.textContent = item.name;
    button.addEventListener("click", () => openResult(item.id).catch(e => message(e.message)));
    $("recent-links").append(button);
  }
}
function cell(text, tag = "td") {
  const element = document.createElement(tag); element.textContent = text; return element;
}
function renderEvidence(evidence) {
  const tbody = $("brier-table").querySelector("tbody"); tbody.replaceChildren();
  for (const [name, score] of Object.entries(evidence.macro_brier)) {
    const row = document.createElement("tr");
    row.append(cell(name === "g0" ? "Constant baseline" : name), cell(fmt(score, 6)));
    tbody.append(row);
  }
  const recovery = $("regression-table").querySelector("tbody"); recovery.replaceChildren();
  for (const metric of evidence.regression) {
    const row = document.createElement("tr");
    row.append(cell(metric.parameter.replaceAll("_", " ")), cell(fmt(metric.mae)),
      cell(fmt(metric.rmse)), cell(fmt(metric.r_squared)));
    recovery.append(row);
  }
}
function renderControls() {
  const tbody = $("controls").querySelector("tbody"); tbody.replaceChildren();
  const variant = $("variant").value;
  result.parameters.forEach((parameter, index) => {
    const row = document.createElement("tr");
    if (index === selectedControl) row.className = "selected";
    const name = document.createElement("td");
    const button = document.createElement("button");
    button.textContent = parameter.label;
    button.setAttribute("aria-pressed", String(index === selectedControl));
    button.addEventListener("click", () => { selectedControl = index; renderControls(); inspectControl(); });
    name.append(button);
    row.append(name, cell(pct(parameter.predicted_z)), cell(pct(parameter.q[variant])));
    tbody.append(row);
  });
}
function inspectControl() {
  const p = result.parameters[selectedControl];
  $("control-name").textContent = p.label;
  const details = $("control-details"); details.replaceChildren();
  for (const [name, value] of [
    ["Vital value", p.vital_display], ["Vital normalized setting", fmt(p.vital_normalized, 6)],
    ["Reliability q", pct(p.q[$("variant").value])],
    ["Uncertainty U (research range²)", Number(p.U).toPrecision(5)],
    ["Local sensitivity S", Number(p.S).toPrecision(5)],
  ]) { details.append(cell(name, "dt"), cell(value, "dd")); }
  $("minus-player").src = filesUrl(`${p.name}_minus.wav`);
  $("plus-player").src = filesUrl(`${p.name}_plus.wav`);
  $("step-note").textContent = `Research positions: ${pct(p.minus_z)} and ${pct(p.plus_z)}. ${p.perturbation_mode === "central" ? "Both sides measured." : "One-sided check near the range limit."} Other controls unchanged.`;
}
async function openResult(job) {
  message("");
  const loaded = await api(`/api/jobs/${job}/result`);
  stopAudio(); result = loaded; resultJob = job; selectedControl = 0;
  $("result").hidden = false;
  $("result-file").textContent = loaded.filename;
  $("elapsed").textContent = `Processed in ${fmt(loaded.elapsed_seconds, 1)} s · ${loaded.provenance.device}`;
  $("target-player").src = filesUrl("target.wav");
  $("reconstruction-player").src = filesUrl("reconstruction.wav");
  $("spectrograms").src = filesUrl("spectrograms.png");
  $("patch-download").href = filesUrl("predicted.vital", true);
  $("wav-download").href = filesUrl("reconstruction_float.wav", true);
  $("report-download").href = filesUrl("result.json", true);
  $("patch-check").textContent = "Patch verified: reloading it through Vita reproduced the controls and audio exactly.";
  $("residual").textContent = `Reconstruction distance R: ${fmt(loaded.R, 5)} (multi-resolution STFT).`;
  renderControls(); inspectControl(); remember(job, loaded.filename);
  window.history.replaceState(null, "", `/?job=${job}#result`);
  $("result").scrollIntoView({behavior: "smooth", block: "start"});
}
function track(job) {
  active = job; setBusy(true); message("");
  $("result").hidden = true; stopAudio();
  $("progress-panel").hidden = false; $("cancel").disabled = false;
  window.history.replaceState(null, "", `/?job=${job}#workspace`);
  clearTimeout(pollTimer); poll();
}
async function poll() {
  if (!active) return;
  try {
    const status = await api(`/api/jobs/${active}`);
    $("progress-title").textContent = status.filename;
    $("progress-detail").textContent = status.detail;
    $("progress").value = status.completed;
    if (status.state === "complete") {
      const job = active; active = null; setBusy(false);
      $("progress-panel").hidden = true;
      await openResult(job); return;
    }
    if (["failed", "cancelled", "interrupted"].includes(status.state)) {
      message(status.detail); active = null; setBusy(false);
      $("progress-panel").hidden = true; return;
    }
    pollTimer = setTimeout(poll, 800);
  } catch (error) {
    message(`Connection lost. Retrying… ${error.message}`);
    pollTimer = setTimeout(poll, 3000);
  }
}
async function startExample(id) {
  setBusy(true); message("");
  try {
    const job = await api("/api/examples", {method:"POST",
      headers:{...requestHeaders, "Content-Type":"application/json"}, body:JSON.stringify({example_id:id})});
    track(job.id);
  } catch (error) { setBusy(false); message(error.message); }
}
$("audio-file").addEventListener("change", e => fileChosen(e.target.files[0]));
for (const name of ["dragenter", "dragover"]) $("drop").addEventListener(name, e => {
  e.preventDefault(); if (!busy) $("drop").classList.add("dragging");
});
for (const name of ["dragleave", "drop"]) $("drop").addEventListener(name, e => {
  e.preventDefault(); $("drop").classList.remove("dragging");
});
$("drop").addEventListener("drop", e => fileChosen(e.dataTransfer.files[0]));
$("upload-form").addEventListener("submit", async event => {
  event.preventDefault(); if (!chosenFile || busy) return;
  if (chosenFile.size > 2 * 1024 * 1024) { message("Choose a WAV smaller than 2 MB."); return; }
  setBusy(true); message("");
  try {
    const job = await api("/api/jobs", {method:"POST", headers:{
      ...requestHeaders, "Content-Type":"audio/wav", "X-C2-Filename":encodeURIComponent(chosenFile.name),
    }, body:chosenFile});
    track(job.id);
  } catch (error) { setBusy(false); message(error.message); }
});
$("cancel").addEventListener("click", async () => {
  if (!active) return;
  $("cancel").disabled = true;
  try { await api(`/api/jobs/${active}/cancel`, {method:"POST", headers:requestHeaders}); }
  catch (error) { $("cancel").disabled = false; message(error.message); }
});
$("variant").addEventListener("change", () => { if (result) { renderControls(); inspectControl(); } });
async function boot() {
  const info = await api("/api/info");
  $("runtime").textContent = `Local · ${info.device.toUpperCase()}`;
  for (const example of info.examples) {
    const row = document.createElement("div"); row.className = "example-row";
    const button = document.createElement("button"); button.className = "secondary";
    button.textContent = `Run ${example.label.toLowerCase()}`; button.dataset.example = example.id;
    button.addEventListener("click", () => startExample(example.id));
    const download = document.createElement("a"); download.textContent = "Original WAV";
    download.href = `/api/examples/${example.id}/raw`; download.download = "";
    row.append(button, download); $("example-buttons").append(row);
  }
  renderEvidence(info.evidence); renderHistory();
  const requested = new URLSearchParams(window.location.search).get("job");
  const job = requested || info.active_job;
  if (job) {
    const status = await api(`/api/jobs/${job}`);
    if (status.state === "complete") await openResult(job);
    else if (["queued", "running", "cancelling"].includes(status.state)) track(job);
    else message(status.detail);
  }
}
boot().catch(error => message(`C2 is unavailable. Check that the local server is running. ${error.message}`));
