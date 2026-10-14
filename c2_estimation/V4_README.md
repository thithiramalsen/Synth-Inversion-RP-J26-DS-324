# C2 v4 implementation and runbook

Status: 14 October 2026. The development milestone, **full deterministic baseline
and three-member ensemble training are complete**. The reliability-calibration
study is still in progress.
Nothing here regenerates the corpus. See [FULL_BASELINE_RESULTS.md](FULL_BASELINE_RESULTS.md).
Saved EDA/audit evidence is indexed in [RESEARCH_EVIDENCE.md](RESEARCH_EVIDENCE.md).

## Implemented and verified

- Exact agreement between the canonical 131,072-row manifest and the full parameter
  reference; 13 recorded normalized controls; no duplicate complete control vectors.
- Actual readback labels in Vital coordinates and research-range coordinates
  `z=(v-low)/(high-low)`. Sampled Sobol coordinates are not substituted for readbacks.
- Immutable, checksummed train/calibration/validation/test assignments, seed 20261013.
- Fixed diagnostic subsets selected before model/error/uncertainty inspection.
- Canonical DC-on-read loader, with raw and conditioned sample-hash verification
  during extraction. No source WAVs, generator, recipe, or preset are changed.
- Resumable, checksummed float32 log-mel shards and training-only normalization.
- A 13-output deterministic CNN with checkpoints, validation MAE/RMSE/R2 in both
  coordinate systems, mean-predictor baseline, curves and training spectrogram images.
- Symmetric multi-resolution STFT diagnostic; range-aware perturbations; actual
  engine readbacks checked for isolation and used for the step denominator.
- One real, predetermined inverse-validation worked example with 13 sensitivities,
  target/reconstruction/perturbation audio, exact roundtrip and inactivity checks.
- Full training on 98,304 clips with 4,096 inverse-validation clips, 60 GPU epochs,
  best checkpoint at epoch 53, exact checkpoint reload, and per-control metrics.
- Same-ID comparison on the original 512 validation clips: lower MAE for all 13
  controls; macro z MAE .184187 -> .126339. Updated audio example for the same clip.
- A 10-figure EDA pack with plotted tables, parameter distributions, split balance,
  training correlation, training audio QA and all-control validation error analysis.
- Three independent Gaussian-head CNNs, each trained for 60 epochs; selected
  epochs 57/59/58, exact checkpoint reload, and saved mixture-moment decomposition.
- Ensemble evidence pack (11 figures), frozen 128-clip training-smoke and
  2,048-clip calibration predictions; completed smoke diagnostics with four audits.
- Frozen non-test subset prediction, resumable forward-diagnostic cases and
  calibration/ablation implementation. Batch-core checks reproduce the saved real
  example's R and all 13 sensitivities exactly within the declared numeric tolerance.
- Saved synthetic implementation checks: 34 CPU-suite checks (two CUDA-only skips),
  plus those two CUDA checks passed separately; logs/counts/source hashes are saved.

## Not yet completed

- Remaining 2,048-clip calibration diagnostics and 512-clip reliability-validation
  predictions/diagnostics. Resumed from 994 completed calibration cases on 14 October.
- Measured real-data calibrators, ablations, bootstrap intervals and final threshold policy.
- Final untouched-test evaluation and the later exploratory human usefulness study.

Do not describe the first deterministic checkpoint as calibrated or assign it q values.

## Fixed partition contract

| Partition | Count | Use |
|---|---:|---|
| Train | 98,304 | Inverse-model fitting; original development prefix is here only |
| Calibration | 16,384 | Pool; first 2,048 selected for planned reliability fitting |
| Validation/inverse | 4,096 | Inverse-model selection and development checks |
| Validation/reliability | 4,096 | Independent reliability/diagnostic tuning; 512 selected |
| Test | 8,192 | Reserved; 1,024 selected for the eventual diagnostic test |

The two validation roles total 8,192. The previously studied v4 prefix (indexes
0-1023) is forced into training; a seeded permutation assigns all remaining IDs.
Selections are unrelated to observed errors or model outputs. A separate 128-clip
training-only diagnostic smoke selection is reserved. Derived renders inherit their
source's partition; they never become new inverse-training examples.

Metadata inspection for integrity is not model evaluation. **No test feature
extraction or test evaluation is performed by these commands.** These are C2
assignments; coordinate shared evaluation IDs before later cross-component comparisons.

The protocol and splits are under `data/processed/c2_v4/protocol_v1/` (ignored by Git).
Rerunning preparation checks identity and refuses changes. Save/version these files
alongside experiment backups; never delete and silently reshuffle a reported study.

## Environment

Use the existing pinned environment for these verified CPU commands. It contains
Python 3.13.14, PyTorch 2.13.0+cpu, NumPy 2.5.1, pandas 3.0.5, PyArrow 25.0.0,
SciPy 1.18.0, SoundFile 0.14.0, Matplotlib 3.11.1 and Vita 0.0.5.
The original environment remains CPU-only. GPU training now uses `.venv-c2`, a
CUDA overlay with PyTorch **2.13.0+cu130**, CUDA 13.0 and cuDNN 9.20 on the RTX
4060 Laptop GPU. It reuses the original pinned scientific dependencies read-only;
the CUDA PyTorch wheel is installed locally in the overlay. The setup does not
upgrade or uninstall anything in the original synthesis environment.

Create/recreate the overlay and record its runtime:

```powershell
.\venv\Scripts\python.exe -B -m c2_estimation.v4.setup_cuda --install
.\.venv-c2\Scripts\python.exe -B -m unittest discover -s c2_estimation/tests -v
```

The runtime record is `data/processed/c2_v4/cuda_environment.json`. Twenty focused
tests pass in this environment, including strict GPU training reproducibility.
For the fixed 64x259 input, the final 2x4 adaptive pool uses the same 4x8 averaging
windows as the fixed GPU pool. The fixed form avoids CUDA adaptive-pool backward
nondeterminism; values and gradients were checked for equivalence. TF32 is disabled.
GPU and CPU training are not promised bit-identical. A short real-feature GPU run
also passed checkpoint reload and completed two development epochs in about 2.7 seconds.

Only needed dependency additions are listed in `c2_estimation/requirements.txt`.
No package installation was required for this milestone.

## Reproduce the first milestone

Run in the repository root. New output names preserve previous runs.

```powershell
.\venv\Scripts\python.exe -B -m c2_estimation.v4.data

.\venv\Scripts\python.exe -B -m c2_estimation.v4.features --cache data/processed/c2_v4/features_development_v1 --scope development --workers 4

.\venv\Scripts\python.exe -B -m c2_estimation.v4.baseline --cache data/processed/c2_v4/features_development_v1 --output data/processed/c2_v4/baseline_development_v3 --epochs 8 --patience 4 --batch-size 64 --threads 4 --device cpu

.\venv\Scripts\python.exe -B -m c2_estimation.v4.diagnostics --run data/processed/c2_v4/baseline_development_v3 --output data/processed/c2_v4/worked_example_v3

.\venv\Scripts\python.exe -B -m unittest discover -s c2_estimation/tests -v
```

The development scope uses a fixed 4,096 training and 512 inverse-validation clips.
They are subsets of the locked assignments, not another reshuffled train/test split.
Feature extraction was about 87 seconds; eight CPU epochs about 70 seconds in the
initial run. These are observed development timings, not full-run guarantees.

Feature extraction resumes verified completed shards with the same command. A
different signature is rejected, not overwritten. Model training saves `last_model.pt`
after each epoch; rerun the **identical** training command with `--resume` to finish
an interrupted run. Epoch-addressable shuffle preserves ordering on resume. Changed
hyperparameters, source hashes, or environments require a new run directory. A
worked-example directory must be new. Do not run concurrent writers to one output.

Verification: 18 focused tests pass, including an injected interruption immediately
after an epoch checkpoint; resuming produced identical model tensors, history and
prediction CSV to uninterrupted training. The completed development run also passes
the real `--resume` path without changing its predictions.

## Full deterministic baseline

```powershell
.\venv\Scripts\python.exe -B -m c2_estimation.v4.features --cache data/processed/c2_v4/features_full_v1 --scope full --workers 8

.\.venv-c2\Scripts\python.exe -B -m c2_estimation.v4.baseline --cache data/processed/c2_v4/features_full_v1 --output data/processed/c2_v4/baseline_full_v1 --epochs 60 --patience 12 --batch-size 128 --threads 4 --device cuda

.\venv\Scripts\python.exe -B -m c2_estimation.v4.compare_baselines --development data/processed/c2_v4/baseline_development_v3 --full data/processed/c2_v4/baseline_full_v1
```

Full scope is 98,304 train + 4,096 inverse-validation clips, requiring about 6.3 GiB
of float32 feature storage. Check disk/compute budget before launch. Calibration,
reliability-validation and test feature extraction will be added with the later
frozen ensemble workflow, not pulled into baseline fitting.

The comparison aligns the same 512 inverse-validation IDs and checks identical
ground-truth readbacks. This avoids comparing the development model's 512-clip
metrics directly with the full model's 4,096-clip metrics. It is a descriptive
comparison of training regimes; model selection is still based on inverse validation.
Results are not final untouched-test evidence.

Measured full-run inverse-validation MSE is **.031867**, versus **.083213** for the
training-mean predictor. Macro z MAE is **.126112** on all 4,096 inverse-validation
clips. Cutoff and amplitude-envelope controls are strong; bend and filter-envelope
decay remain weaker. Full per-control tables and interpretation are in the results report.

To rerender the same earlier worked example with the full model:

```powershell
.\venv\Scripts\python.exe -B -m c2_estimation.v4.diagnostics --run data/processed/c2_v4/baseline_full_v1 --output data/processed/c2_v4/worked_example_full_v1 --sample-id restricted_bend_sustain_v4_01394
```

Twenty GPU checks plus the additional matched-ID comparison check have passed.
The full-model worked example passed roundtrip, isolation, determinism and frozen
prediction checks. The reconstruction distance changed from .363118 to .314926
for this one clip; that is numerical evidence for this example, not a perceptual
similarity percentage or a population-wide reconstruction conclusion.

Source hashes are part of run signatures. Historical development results remain
saved; reruns using the GPU-compatible code need a new output directory. Resume
the full run only with the identical command plus `--resume`.

## EDA, uncertainty ensemble and non-test calibration workflow

```powershell
.\venv\Scripts\python.exe -B -m c2_estimation.v4.evidence --run data/processed/c2_v4/baseline_full_v1 --output data/processed/c2_v4/evidence_baseline_full_v1

.\.venv-c2\Scripts\python.exe -B -m c2_estimation.v4.ensemble --cache data/processed/c2_v4/features_full_v1 --output data/processed/c2_v4/ensemble_full_v1 --members 3 --epochs 60 --patience 12 --batch-size 128 --threads 4 --device cuda

.\venv\Scripts\python.exe -B -m c2_estimation.v4.run_development --ensemble data/processed/c2_v4/ensemble_full_v1 --output data/processed/c2_v4/development_uncertainty_v1 --workers 4 --wait-minutes 120
```

The evidence directory and completed ensemble already exist; these commands record
how they were produced. Do not launch another writer into `ensemble_full_v1`.
All three models are saved, so this workflow resume does not retrain them. For an
interrupted training run, first confirm no old writer remains, then repeat its
identical ensemble command with `--resume`. The workflow reuses verified completed
stages (or waits up to 120 minutes if ensemble training is still in progress), then
performs these stages in order:

1. Save ensemble EDA, including raw variance vs squared-error plots.
2. Freeze predictions for the preassigned 128 training smoke clips and measure S/R.
3. After smoke/audit checks pass, freeze and measure 2,048 calibration and 512
   reliability-validation clips. Actual engine readbacks are the step denominator.
4. Fit g0, g(U), g(U,S), g(U,R), g(U,S,R), with raw-U ranking separately. Select C
   only on reliability-validation and save Brier/ECE/AUROC/AP/risk-coverage, matched
   coverage MAE, diagrams, and 2,000 paired whole-audio Brier bootstrap intervals.
5. Repeat correctness-tolerance analyses at .025/.10, reusing the same diagnostic
   renders. Save a measured `RESULTS.md` only after stages actually complete.

The workflow saves `status.json`, per-stage logs and source signatures. Completed
outputs are verified before reuse. Long diagnostics resume individual checksummed
cases. Interrupted short-stage outputs are preserved under `__partial_<timestamp>`
before rerunning that stage; no existing corpus/model data is deleted. Never run
two workflow writers into the same directory. Sources/environment must remain
unchanged while this run is active. Keep the laptop awake and on power; sleeping
or closing the app may interrupt execution, but saved checkpoints/cases remain.

A full epoch was initially about 26 seconds on this laptop; three 60-epoch members
can take roughly 80 minutes before diagnostics, unless early stopping reduces it.
Forward-render timing is measured in stage logs, not assumed from CNN speed.
Four CPU workers bound parallel rendering. No second multi-gigabyte feature cache
is created, and perturbation waveforms are streamed rather than saved in bulk.

### Live progress and saved models

The workflow was resumed from **994/2,048 saved calibration cases** on 14 October
2026. New case counts were observed after restart; saved models and completed
smoke diagnostics were reused. This is a dated restart record, not a live count.

From the repository root in VS Code's PowerShell terminal, follow the active
calibration diagnostic log:

```powershell
Get-Content data/processed/c2_v4/development_uncertainty_v1/logs/diagnose_calibration.log -Tail 10 -Wait
```

`Ctrl+C` stops this viewer only. It does not stop the workflow running in another
terminal/session. Once calibration diagnostics finish, follow
`logs/diagnose_reliability-validation.log` instead. Inspect the current stage with:

```powershell
Get-Content data/processed/c2_v4/development_uncertainty_v1/status.json
```

`status.json` is updated at stage boundaries, not per clip. Its `running` value can
remain stale after an interruption; advancing log counts/new case files demonstrate
progress. Only the terminal exit result or final completion status confirms that
the workflow has finished. To resume after confirming the previous writer stopped,
rerun the identical `run_development` command above. Do not delete partial cases.

Saved checkpoints, relative to `data/processed/c2_v4/`:

| Model | Best checkpoint |
|---|---|
| Deterministic baseline | `baseline_full_v1/best_model.pt` |
| Ensemble member 0 | `ensemble_full_v1/member_00/best_model.pt` |
| Ensemble member 1 | `ensemble_full_v1/member_01/best_model.pt` |
| Ensemble member 2 | `ensemble_full_v1/member_02/best_model.pt` |

Each model directory also has `last_model.pt` for training resume. The ensemble
uses all three best checkpoints together, not just the last-trained member.
Keep run configs, preprocessing/protocol metadata and checksums with the weights.
These generated artifacts are ignored by Git and need a separate backup.

Measured ensemble inverse-validation macro z MAE is **.127991**, compared with
**.126112** for the deterministic baseline on the same 4,096 clips. Point accuracy
therefore did not improve in this run. Whether U/S/R improves correctness reliability
is a separate question, still awaiting the real-data calibration/ablation results.
No held-out test has been evaluated.

For an individual stage after ensemble completion:

```powershell
.\.venv-c2\Scripts\python.exe -B -m c2_estimation.v4.predict_subsets --ensemble data/processed/c2_v4/ensemble_full_v1 --partition smoke --output data/processed/c2_v4/smoke_predictions_manual_v1 --device cuda
.\venv\Scripts\python.exe -B -m c2_estimation.v4.diagnostic_batch --predictions data/processed/c2_v4/smoke_predictions_manual_v1 --output data/processed/c2_v4/smoke_diagnostics_manual_v1 --workers 4
```

`--partition` also accepts `calibration` and `reliability-validation`; **not test**.
Do not use training smoke labels to fit reported calibrators. Calibration commands:

```powershell
.\venv\Scripts\python.exe -B -m c2_estimation.v4.calibration --calibration data/processed/c2_v4/development_uncertainty_v1/diagnostics_calibration --validation data/processed/c2_v4/development_uncertainty_v1/diagnostics_reliability-validation --output data/processed/c2_v4/calibration_manual_v1 --tau .05 --bootstrap 2000
```

Training uses a Gaussian NLL working objective with bounded mean and positive
variance. It is not a calibrated posterior. Total mixture variance is in z², not
a success probability. Logistic fitting uses the pinned SciPy implementation,
calibration-only standardization, no class weighting and an unpenalized intercept;
regularization is `||w||²/(2*C*n)` added to mean binomial NLL. Single-class controls
use the observed constant probability and have undefined ranking metrics.

These are **development** scores: reliability-validation selects C, so its reported
scores and bootstrap intervals are not final unbiased test evidence. Delta remains
.02; perturbation-step alternatives, method locking and final test come later.
The workflow will not invent q before fitting, label R as percent similarity,
modify theta-hat during diagnostics or infer a universal sound-similarity threshold.

To save reproducibility checks again, use fresh output names:

```powershell
.\venv\Scripts\python.exe -B -m c2_estimation.v4.verification --output data/processed/c2_v4/verification_cpu_new
.\.venv-c2\Scripts\python.exe -B -m c2_estimation.v4.verification --gpu-only --output data/processed/c2_v4/verification_gpu_new
.\venv\Scripts\python.exe -B -m c2_estimation.v4.verify_forward_batch --run data/processed/c2_v4/baseline_full_v1 --example data/processed/c2_v4/worked_example_full_v1 --output data/processed/c2_v4/forward_batch_check_new --workers 2
```

## Measured development result

Eight epochs on the development subset gave inverse-validation research-range MSE
**0.054479**, versus **0.083877** for the training-mean predictor, and macro z MAE
**0.184187**. This is a sanity result, not a final held-out-test or uncertainty result.
Checkpoint reload reproduced the predictions exactly. Initial repeat training also
reproduced the prediction CSV exactly; the final export preserves float64 readback
labels and full precision of the float32 predictions.

The model learns cutoff and amplitude-envelope controls much better than several
other controls. Bend, drive and multiple filter-envelope controls remain near the
mean baseline at this stage. Inspect per-control metrics before training the ensemble;
do not hide these weaknesses behind a macro average or a confidence display.

## Output inventory

| Location within run directory | Meaning |
|---|---|
| `run_config.json` | Scope, source hashes, preprocessing statistics, model/runtime settings |
| `best_model.pt`, `last_model.pt` | Best validation model and resumable optimizer checkpoint |
| `training_history.csv`, `learning_curves.png` | Training/inverse-validation learning evidence |
| `validation_predictions.csv` | IDs and actual/predicted z and Vital coordinates |
| `validation_metrics.csv` | MAE/RMSE/R2 per control in both coordinate systems |
| `mean_baseline_metrics.csv` | Constant training-mean regression baseline |
| `spectrogram_examples/` | Four training-only log-mel figures |
| `summary.json` | Measured status, checkpoint/prediction hashes, no-test flag |

The worked example adds `example.json`, `parameter_diagnostics.csv`, target,
predicted, true-roundtrip, midpoint, cutoff-minus and cutoff-plus FLOAT WAVs. It
does not normalize them independently or modify the source corpus. Large generated
artifacts stay in ignored `data/processed/c2_v4/`; source and documentation stay in Git.
