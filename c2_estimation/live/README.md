# C2 live audio-to-patch app

This local app accepts one isolated synth WAV, runs the frozen three-member C2
ensemble, renders the predicted settings, computes U/S/R and development reliability
q, and exports a real Vital preset. It does not retrain or refine the prediction.

## Start

Open a PowerShell terminal in `D:\VSCode\GitHub\Synth-Inversion-RP`:

```powershell
Set-Location D:\VSCode\GitHub\Synth-Inversion-RP
.\.venv-c2\Scripts\python.exe -B -m c2_estimation.live.server
```

Open **http://127.0.0.1:8770/**. Keep that terminal open. Ctrl+C stops this app.
The existing GPU environment is `.venv-c2`; the separate `venv` has CPU PyTorch.
The default `--device auto` uses CUDA when available. To request CPU explicitly:

```powershell
.\venv\Scripts\python.exe -B -m c2_estimation.live.server --device cpu --port 8770
```

If the port is occupied, use `--port 8771` and the corresponding browser address.
Do not stop an unidentified server. The saved viewer uses 8765 and the C2 study
rehearsal uses 8766; neither is part of this application.

No packages need to be installed in the existing environments. The app uses
PyTorch, Vita, NumPy, SciPy, SoundFile, pandas, Matplotlib, FastAPI and Uvicorn.
It has plain HTML/CSS/JavaScript assets and no frontend build step.

## Use it

1. Click **Run example 1**, or choose a WAV and click **Find the settings**.
   Example buttons perform fresh inference; they do not retrieve saved predictions.
   **Original WAV** downloads an unprocessed example that can also be uploaded.
2. Watch the processing stages. Sensitivity requires up to 26 perturbation renders
   plus the reconstruction. Cancel stops after the current operation.
3. Play **Target** and **Reconstruction**. Their playback copies are PCM16 without
   independent loudness normalization. Numeric diagnostics use canonical float32.
4. Inspect the 13 controls. Research positions are percentages of the restricted
   interval, not full Vital knob percentages. Select a control to see its Vital
   display value, normalized setting, uncertainty U, sensitivity S and perturbation audio.
5. Change the reliability model to inspect the saved ablations on this new prediction.
   This changes the displayed probability only, never the delivered patch.
6. Download the `.vital` patch, canonical FLOAT reconstruction WAV or result JSON.
   Every completed job has passed preset reload, exact control-readback and exact
   conditioned-audio checks through Vita. Opening the preset in the desktop Vital
   UI is a separate manual compatibility check.
7. Reopen a result from the recent list or its `?job=...` URL. Completed results
   survive server restarts. An interrupted job is labelled interrupted; start a
   new run to process it again.

The example rule is fixed: the first three preassigned reliability-validation
diagnostic ranks, IDs `restricted_bend_sustain_v4_63764`, `_68474`, and `_49083`.
They were not selected for good sound or high confidence. Examples are development
data and must not be reported as new held-out test cases.

## Input scope

- Uncompressed WAV, exactly 132,300 frames, mono, 44,100 Hz (three seconds).
- PCM16/24/32 or floating-point samples, maximum file size 2 MiB.
- Finite samples, no full-scale clipping, and non-silent audio.
- Original unprocessed input. C2 applies the canonical 10 Hz DC filter once.
- Training scope: restricted Vital v4 family, MIDI 60, velocity 0.8, a 1.5-second
  held note followed by release, fixed oscillator/filter/modulation setup.

The app rejects incompatible formats instead of silently trimming, resampling,
downmixing or normalizing them. It cannot determine from format alone whether an
arbitrary recording belongs to the trained sound family. q is a development
estimate within that domain, not a validated confidence for arbitrary uploads.

Exact known raw/conditioned test-waveform hashes are blocked using manifest metadata.
No test audio is opened to build this safeguard. This is not an audio fingerprint
system: a transcoded or modified test clip may have a different hash. Do not submit
reserved test material. Known exact conditioned corpus waveforms are also rejected
to prevent filtering those copies twice. For other uploads, the original-input
requirement remains the user's responsibility.

## Meaning of the results

| Output | Meaning |
|---|---|
| Predicted z | Position within each control's fixed research interval, 0 to 1 |
| U | Equal-weight mixture variance: mean member variance plus population variance of member means |
| R | Symmetric multi-resolution STFT discrepancy between target and reconstruction |
| S | Difference between two single-control perturbation renders divided by their actual control-readback separation |
| q | Estimated probability that the generating control is within ±0.05 research units of the prediction |

Perturbation step is .02, with one-sided measurements near boundaries. The primary
display uses the existing `g(U,S,R)` development calibrator; U-only, U+S and U+R
are available for comparison. The app adds no fitted models or thresholds.

q is not a sound-similarity percentage, and high sensitivity does not prove
unique recovery. No universal accept/abstain or perceptual-match threshold has
been validated. The existing development comparison does not establish extra
benefit from S over U+R.

The **Research results** section reads existing ensemble MAE/RMSE/R² on 4,096
inverse-validation clips and Brier scores on 512 reliability-validation clips.
These are separate populations. The latter selected calibrator regularization,
so they are development findings. An uploaded clip without known original
parameters cannot have a meaningful parameter MAE, RMSE or R² computed for it.

## Implementation and saved files

| File | Responsibility |
|---|---|
| `c2_estimation/live/engine.py` | Source/artifact verification, input conditioning, inference, diagnostics, calibration, patch export and roundtrip checks |
| `c2_estimation/live/server.py` | Loopback API, one worker, bounded uploads, progress, cancellation, persistence and checked downloads |
| `c2_estimation/live/web/index.html` | Page content and accessible controls |
| `c2_estimation/live/web/app.js` | Uploads, progress polling, audio, control inspector and result reopening |
| `c2_estimation/live/web/style.css` | Responsive layout |
| `c2_estimation/live/test_live.py` | Input, job, HTTP, integrity and restart tests |
| `c2_estimation/live/verify.py` | Real development examples compared with the frozen research implementations |

Default outputs:

`D:\VSCode\GitHub\Synth-Inversion-RP\data\processed\c2_v4\live_app_v1\`

Each `jobs/<random-id>/` contains the original upload, conditioned playback,
FLOAT reconstruction, 26 perturbation WAVs, comparison figure, predicted `.vital`,
result JSON and output checksums. The JSON includes U components, all four q
variants, R by resolution, readbacks, timing, input/model/source hashes and export
verification. Status and error logs are separate in `status/`.

The app serves only whitelisted web assets, the three predetermined original
examples and checksum-verified files from complete jobs. It does not mount the
repository, dataset or study directories. Requests are loopback-only with Host,
Origin and request-header checks; this is not a public authenticated deployment.
One worker serializes inference, rendering and plotting. A second simultaneous
submission receives a busy response instead of starting overlapping jobs.

Files remain local until manually removed. This folder is Git-ignored, so back up
needed results separately. Cancelling preserves partial files for diagnosis but
does not expose them as completed results. There is no participant-data collection.

## Frozen-source and preset checks

The runtime verifies the protocol, training source, checkpoint signatures,
calibrators, diagnostic configuration and synthesis recipe. Git's CRLF conversion
is accepted only when text otherwise matches the recorded source exactly.
The historical generator has mixed line endings; its original bytes are verified
against the existing checksummed `team_v4_131072_SHARE.zip` before comparing
normalized newlines. Checkpoint/preset hashes are never normalized.

The ignored base preset was missing in this checkout on 20 October 2026. It was
restored from the existing local clone-QA copy after matching the protocol's SHA256:

`ee3c0d4df877a0715c3660bfdff730f80eb93287c10a45697f56bc0f9e03c49b`

The restored file is:

`D:\VSCode\GitHub\Synth-Inversion-RP\generation\presets\base_restricted_bend_sustain_v4.vital`

No tracked research source or source hash was rewritten. The app's renderer
subclass changes setup verification only and inherits the existing `Renderer.render`
unchanged. Known true-patch roundtrips and independent diagnostics are checked in
the real verification run. Use the supplied exact preset and private bundle on
another checkout; do not regenerate a replacement silently.

## Verification commands

```powershell
.\venv\Scripts\python.exe -B -m unittest c2_estimation.live.test_live -v
.\.venv-c2\Scripts\python.exe -B -m c2_estimation.live.verify --output data/processed/c2_v4/live_verification_v2 --device cuda
```

Use a **new** verification output name each time. The existing completed check is
`D:\VSCode\GitHub\Synth-Inversion-RP\data\processed\c2_v4\live_verification_v1\verification.json`.
It checks three predetermined development clips, repeat inference, comparison
with historical predictions, R/S agreement with the unchanged research diagnostic
code, the calibrator formula, known true-patch and inactive-control audits, and
exported-preset roundtrips. See `VERIFICATION.md` for measured results and limits.

## Still separate from application completion

Final method locking, independent test evaluation and the human study remain
pending. This app does not implement automatic whole-patch acceptance, broaden the
model domain, optimize a patch after prediction, or provide a full synthesizer
editor. The existing saved viewer, human-study software and all other components
remain separate.
