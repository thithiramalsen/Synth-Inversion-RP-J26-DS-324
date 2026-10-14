"use strict";
(() => {
  const data = window.C2_DATA;
  const get = id => document.getElementById(id);
  if (!data || !Array.isArray(data.examples) || !data.examples.length) {
    get("load-error").hidden = false;
    get("load-error").textContent = "The example data could not be loaded. Open the generated viewer folder; DEMO.md has the build and launch commands.";
    return;
  }
  let exampleIndex = 0, selectedControl = "filter_cutoff", variant = "g(U,S,R)";
  const label = name => name.replaceAll("_", " ");
  const fmt = value => Number(value).toFixed(4);
  const percent = value => value > .999 && value < 1 ? ">99.9%" : value > 0 && value < .001 ? "<0.1%" : `${(100 * value).toFixed(1)}%`;
  const stopAudio = () => document.querySelectorAll("audio").forEach(a => a.pause());
  const setAudio = (id, file) => { const a = get(id); a.pause(); a.src = file; a.load(); };
  document.querySelectorAll("audio").forEach(audio => audio.addEventListener("play", () => {
    document.querySelectorAll("audio").forEach(other => { if (other !== audio) other.pause(); });
  }));
  data.examples.forEach((example, index) => {
    const option = document.createElement("option");
    option.value = String(index); option.textContent = `Example ${index + 1}`;
    get("example-select").append(option);
  });
  function drawControls() {
    const example = data.examples[exampleIndex], showTruth = get("show-truth").checked;
    get("parameter-rows").replaceChildren();
    document.querySelectorAll(".truth-column").forEach(el => { el.hidden = !showTruth; });
    for (const p of example.parameters) {
      const row = document.createElement("tr");
      row.classList.toggle("selected", p.name === selectedControl);
      const nameCell = document.createElement("td"), button = document.createElement("button");
      button.type = "button"; button.className = "parameter-button";
      button.textContent = label(p.name); button.setAttribute("aria-pressed", String(p.name === selectedControl));
      button.addEventListener("click", () => {
        selectedControl = p.name; drawControls(); drawInspector();
        get("parameter-rows").querySelector(".selected button").focus({preventScroll:true});
      });
      nameCell.append(button);
      const valueCell = document.createElement("td"); valueCell.textContent = fmt(p.predicted_z);
      const track = document.createElement("div"), fill = document.createElement("span");
      track.className = "value-track"; track.setAttribute("aria-hidden", "true"); fill.style.width = `${100 * p.predicted_z}%`; track.append(fill); valueCell.append(track);
      const probabilityCell = document.createElement("td"); probabilityCell.className = "probability-cell";
      const inline = document.createElement("div"), qText = document.createElement("strong"), qTrack = document.createElement("span"), qFill = document.createElement("span");
      inline.className = "probability-inline"; qText.textContent = percent(p.q[variant]);
      qTrack.className = "q-track"; qTrack.setAttribute("aria-hidden", "true"); qFill.style.width = `${100 * p.q[variant]}%`; qTrack.append(qFill); inline.append(qText, qTrack); probabilityCell.append(inline);
      const reference = document.createElement("td"); reference.className = "reference-values"; reference.hidden = !showTruth;
      reference.textContent = `${fmt(p.actual_z)} / |error| ${fmt(p.error_z)}`;
      const outcome = document.createElement("span"); outcome.textContent = p.correct ? "Within ±0.05" : "Outside ±0.05"; reference.append(outcome);
      row.append(nameCell, valueCell, probabilityCell, reference); get("parameter-rows").append(row);
    }
    get("reference-audio-section").hidden = !showTruth;
  }
  function drawInspector() {
    const example = data.examples[exampleIndex], p = example.parameters.find(item => item.name === selectedControl);
    get("selected-parameter").textContent = label(p.name);
    get("selected-u").textContent = p.U.toExponential(3) + " z²";
    get("selected-s").textContent = fmt(p.S); get("selected-q").textContent = percent(p.q[variant]);
    get("step-explanation").textContent = `Settings used: z ${fmt(p.minus_z)} and ${fmt(p.plus_z)} (a difference of ${fmt(p.actual_step_z)}).${p.mode === "central" ? "" : " The step is one-sided because the prediction is near a range limit."}`;
    setAudio("minus-audio", example.base_path + p.name + "_minus.wav");
    setAudio("plus-audio", example.base_path + p.name + "_plus.wav");
    get("minus-audio").setAttribute("aria-label", `Play ${label(p.name)} at the lower setting`);
    get("plus-audio").setAttribute("aria-label", `Play ${label(p.name)} at the higher setting`);
  }
  function drawExample() {
    stopAudio();
    const example = data.examples[exampleIndex];
    get("sample-id").textContent = example.sample_id; get("example-rank").textContent = `Selection order: ${example.diagnostic_rank + 1}`;
    get("residual-value").textContent = fmt(example.R);
    setAudio("target-audio", example.base_path + "target.wav"); setAudio("predicted-audio", example.base_path + "predicted.wav");
    setAudio("truth-audio", example.base_path + "true_roundtrip.wav");
    get("spectrogram").src = example.base_path + "spectrograms.png";
    drawControls(); drawInspector();
  }
  get("example-select").addEventListener("change", event => { exampleIndex = Number(event.target.value); drawExample(); });
  get("variant-select").addEventListener("change", event => { variant = event.target.value; drawControls(); drawInspector(); });
  get("show-truth").addEventListener("change", drawControls);
  document.querySelectorAll(".nav-button").forEach(button => button.addEventListener("click", () => {
    stopAudio();
    document.querySelectorAll(".nav-button").forEach(item => { const active = item === button; item.classList.toggle("active", active); item.setAttribute("aria-pressed", String(active)); });
    document.querySelectorAll(".panel").forEach(panel => { panel.hidden = panel.id !== button.dataset.panel; });
  }));
  const max = Math.max(...Object.values(data.macro_brier));
  for (const name of ["g0", "g(U)", "g(U,S)", "g(U,R)", "g(U,S,R)"]) {
    const row = document.createElement("div"), text = document.createElement("span"), background = document.createElement("div"), bar = document.createElement("div"), number = document.createElement("span");
    row.className = "bar-row" + (name === "g(U,S,R)" ? " full" : ""); text.textContent = name;
    background.className = "bar-background"; background.setAttribute("aria-hidden", "true"); bar.className = "bar-fill"; bar.style.width = `${100 * data.macro_brier[name] / max}%`;
    number.className = "bar-value"; number.textContent = data.macro_brier[name].toFixed(6); background.append(bar); row.append(text, background, number); get("brier-bars").append(row);
  }
  const conditional = data.comparisons.find(item => item.reference === "g(U,R)" && item.group === "all_13");
  get("sensitivity-finding").textContent = `Adding S to U+R changed the Brier score by ${conditional.point_difference.toFixed(6)}. The paired 95% interval runs from ${conditional.ci95_low.toFixed(6)} to ${conditional.ci95_high.toFixed(6)}, so it includes zero.`;
  get("probability-note").textContent = `q estimates the chance that a parameter is within ±${data.tau_z.toFixed(2)} of its original value, using the research range. U measures ensemble variance, S measures sensitivity to small changes, and R measures reconstruction error. The probabilities come from development calibration.`;
  get("selection-note").textContent = `These are the first ${data.examples.length} examples in the validation subset's predefined order. They were not chosen for how good they sound. Use the full validation results to judge overall performance.`;
  get("audio-note").textContent = "Audio is played as 16-bit WAV without loudness normalization. The measurements use the original float32 samples.";
  get("scope-note").textContent = "All examples use MIDI note 60, velocity 0.8 and a 1.5-second note, rendered as 3 seconds of mono audio at 44.1 kHz.";
  drawExample();
})();
