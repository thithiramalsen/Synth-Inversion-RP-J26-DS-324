# C2 saved-results viewer

This local browser viewer replays **real, saved development results**. It does not
accept uploaded audio, run inference in the browser, or edit a synthesizer patch.
No full synthesizer interface needs to be recreated: the existing Vita adapter
already renders the fixed Vital preset with the predicted controls. The viewer
plays those verified renders and displays their measured diagnostics.

## Intended application output

The intended C2 application takes an isolated synth clip and returns the 13
predicted settings, a downloadable Vital patch, reconstructed audio and
per-parameter uncertainty U, sensitivity S and calibrated correctness q, together
with reconstruction error R. The trained models and forward diagnostics exist;
the upload/inference service and patch-download interface are still pending.

An uploaded clip generally has no known generating settings, so MAE, RMSE, R2 and
true parameter errors cannot be calculated for it. Those belong in the research
evaluation. Live scores must also explain the model's restricted preset and note
conditions; calibration has not been established for arbitrary synth recordings.

## Launch the existing viewer

In a PowerShell terminal at the repository root:

```powershell
.\venv\Scripts\python.exe -B -m http.server 8765 --bind 127.0.0.1 --directory data/processed/c2_v4/viewer_v1
```

Open **http://127.0.0.1:8765/** in a browser. Leave that terminal running while
using the viewer; `Ctrl+C` stops only the web server. No training or calibration
job is required. The server exposes only this generated viewer directory on this
computer's loopback address, not the whole repository. If port 8765 is already
occupied, use a different port in both command and URL; do not stop an unknown job.

The entry file is `data/processed/c2_v4/viewer_v1/index.html`. Open this generated
copy, not the source template in `c2_estimation/viewer/`. Everything is local;
there are no external scripts, uploads, accounts or services. The static files
avoid data-fetch requests, but direct file opening was not browser-tested; the
loopback HTTP launch above is the verified method. No package installation is needed.

## Walk through the output

1. Choose an example and play **target**, then **reconstruction**. Starting one
   player pauses the other players. Expand the paired log-mel spectrograms.
2. Inspect the 13 predicted controls and their correctness probabilities. Values
   use research-range coordinates `z`, not raw knob positions or physical units.
3. Select a control. The inspector shows ensemble variance U, local sensitivity S,
   estimated correctness q and the actual perturbation interval. Listen to its
   minus/plus renders. The delivered prediction stays unchanged.
4. Turn on **Show original settings** to compare with the generating labels and
   inspect absolute errors. Optionally play the known-parameter roundtrip. These
   labels are available because the examples are synthetic research data; they
   are not inputs to the deployed estimator or calibrator.
5. Switch the displayed calibrator to compare U-only, U+S, U+R and U+S+R estimates
   for exactly the same patch. This changes only the displayed probabilities.
6. Open **Validation results** for the aggregate Brier comparison, per-control
   intervals, matched-coverage comparisons and reliability/risk curves. Open
   **Method** for the processing sequence and limitations.

All six examples are the **first six preassigned reliability-validation diagnostic
ranks**, not the best-sounding or highest-confidence results. Their IDs and selection
rule are saved in `manifest.json` and `data.json`. The six examples illustrate the
pipeline; they do not replace the complete 512-case validation analysis.

## Interpret the numbers accurately

- **Predicted z**: location within that control's research interval,
  `(Vital normalized value - lower bound) / interval width`.
- **U**: total three-member mixture variance in z squared, not a probability.
- **R**: target-versus-prediction multi-resolution STFT distance; lower means closer
  under this metric. It is not a percentage of similarity or a perceptual guarantee.
- **S**: acoustic distance between single-control perturbations divided by their
  actual engine-readback separation. High local influence is not proof of unique
  parameter recovery; low influence does not mean that the model predicted correctly.
- **q**: a fitted estimate of whether the generating parameter is within **±.05 of
  the research interval**. It is not the probability that the audio sounds identical.
  No universal Accept/Abstain threshold has been validated.

The inverse model uses 64-band log-mel features. Forward diagnostics use the fixed
multi-resolution STFT distance at FFT sizes 512/1024/2048; CLAP and MFCC are not
used by this C2 implementation. Displayed spectrograms use the same fixed decibel
reference. The original protocol applies the canonical conditioning once and does
not independently normalize target/reconstruction loudness.

Playback copies are PCM16 for browser compatibility, without loudness normalization.
All numeric diagnostics and exact roundtrip checks use canonical float32 samples
before that playback quantization. The build checks for clipping rather than silently
rescaling files. Each example has 29 WAVs: target, prediction, known-true roundtrip,
and two perturbations for each of 13 controls.

## Rebuild or refresh

The completed build was produced with:

```powershell
.\venv\Scripts\python.exe -B -m c2_estimation.v4.build_viewer --output data/processed/c2_v4/viewer_v1 --examples 6
```

A fresh build needs a **new** output directory and the existing protocol, completed
development-calibration and `results_audit_v1` artifacts. It verifies source outputs,
rerenders the selected patches, checks canonical target/roundtrip hashes and
matches saved R/S before exporting. It does not retrain or refit anything.

After changing only the three frontend source files, refresh the existing display:

```powershell
.\venv\Scripts\python.exe -B -m c2_estimation.v4.build_viewer --output data/processed/c2_v4/viewer_v1 --refresh-ui
node --check c2_estimation/viewer/app.js
```

Refresh verifies the existing artifact hashes first, replaces only HTML/CSS/JS and
updates their checksums. It does not regenerate measured data or audio. Use a browser
reload after refreshing. Do not edit generated results to change the displayed scores.

## Verification and limits

All six builds passed exact true-parameter roundtrip, frozen-prediction, readback
isolation and saved R/S checks. Browser checks verified playback, player exclusion,
example/control/calibrator switching, reference reveal and all four research figures;
no JavaScript errors were observed. Desktop screenshots are saved beside `index.html`.
The recorded CPU suite discovered 43 tests: 41 passed, two CUDA-only tests skipped.
The wording was simplified on 15 October, then checked in the browser across all
three tabs. `viewer-wording.jpg` shows the revised page.

The evidence is development-only: validation selected calibrator regularization.
The restricted preset family, MIDI 60, velocity .8, 1.5-second note and 3-second
44.1 kHz mono render are fixed. Arbitrary audio, other notes and other synthesizers
are not validated. Final method locking, untouched-test evaluation and a small human
study remain pending. See [VALIDATION_RESULTS.md](VALIDATION_RESULTS.md).

The viewer and model artifacts live in Git-ignored `data/processed/c2_v4/`. Back up
the **whole viewer folder** to retain relative audio/image/data links. Git alone
does not preserve the generated demonstration or trained models.
