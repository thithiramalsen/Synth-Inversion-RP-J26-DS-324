# C2 v4 implementation and runbook

Status: 13 October 2026. This is the **first implemented research milestone**, not
the completed reliability-calibration study. Nothing here regenerates the corpus.

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

## Not yet completed

- Full-training-pool deterministic run and architecture/learning-curve review.
- Probabilistic 3/5-member ensemble, uncertainty decomposition and frozen ensemble predictions.
- Full 128-clip diagnostic smoke batch and bounded 2,048/512/1,024 reliability study.
- Per-control calibrators, ablations, bootstrap intervals, risk/coverage threshold policy.
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
The machine has an RTX 4060 Laptop GPU, but this PyTorch installation cannot use it.
Do not replace the frozen synthesis environment to add CUDA. Prepare a separate
training environment if GPU acceleration is chosen, then record its dependencies
and repeat reproducibility checks. GPU and CPU results are not promised bit-identical.

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

## Next full baseline (commands available; not run for this milestone)

```powershell
.\venv\Scripts\python.exe -B -m c2_estimation.v4.features --cache data/processed/c2_v4/features_full_v1 --scope full --workers 4

.\venv\Scripts\python.exe -B -m c2_estimation.v4.baseline --cache data/processed/c2_v4/features_full_v1 --output data/processed/c2_v4/baseline_full_v1 --epochs 60 --patience 12 --batch-size 64 --threads 4 --device cpu
```

Full scope is 98,304 train + 4,096 inverse-validation clips, requiring about 6.3 GiB
of float32 feature storage. Check disk/compute budget before launch. Calibration,
reliability-validation and test feature extraction will be added with the later
frozen ensemble workflow, not pulled into baseline fitting.

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
