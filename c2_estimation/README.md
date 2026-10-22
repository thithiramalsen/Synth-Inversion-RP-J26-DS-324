# C2 - Deterministic synthesizer parameter estimation

## Open a C2-focused workspace

In VS Code use **File > Open Workspace from File** and select
[`C2.code-workspace`](../C2.code-workspace). This hides other components only in
that workspace. Current models, protocol and study runtimes stay at their original
paths; verification records are grouped in `data/processed/c2_v4/checks/`, and old
development/test-fixture outputs in `data/processed/c2_v4/archive/`. Legacy paths
remain compatibility junctions, not duplicate data. See the
[layout and safety notes](tools/README.md). The detailed learning guide remains
outside the repository.

## Current research implementation: 13-control v4

For a plain-language explanation with exact code excerpts, start with
[COMPONENT_STUDY_GUIDE.md](notes/COMPONENT_STUDY_GUIDE.md). Use
[DEMONSTRATION_WALKTHROUGH.md](notes/DEMONSTRATION_WALKTHROUGH.md) for VS Code/browser
walkthroughs, and [METRICS_REFERENCE.md](notes/METRICS_REFERENCE.md) for formulas and
complete measured tables.

The current C2 research dataset is the completed **131,072-sound, 13-control v4
corpus**. Start with [V4_README.md](V4_README.md) for commands, verified status,
split protections, and remaining work. [RESEARCH_DESIGN.md](RESEARCH_DESIGN.md)
explains the technology choices and evaluation justification;
[WORKED_EXAMPLE.md](WORKED_EXAMPLE.md) walks through actual development renders.
The full deterministic model is now trained; measured results are in
[FULL_BASELINE_RESULTS.md](FULL_BASELINE_RESULTS.md).
[RESEARCH_EVIDENCE.md](RESEARCH_EVIDENCE.md) indexes the saved EDA figures, tables,
audits and statistical safeguards, and distinguishes running experiments from results.

The deterministic baseline, three-member ensemble, EDA and development calibration
are complete. Diagnostics cover 128 smoke, 2,048 calibration and 512
reliability-validation clips. The per-control results audit and a fixed 256-clip
calibration-only perturbation-step study are also complete; see
[VALIDATION_RESULTS.md](VALIDATION_RESULTS.md) for measured findings and limits.

Use [DEMO.md](DEMO.md) to launch the local saved-results viewer: six predetermined
examples with target/reconstruction audio, 13 predicted controls, correctness
probabilities, perturbations and research figures. This is not live inference.
The final test set remains untouched, the final method is not locked, and no human
study has been run. No C3 code or frozen generation code was changed. Checkpoint
locations are in the [runbook](V4_README.md#live-progress-and-saved-models).

## Historical eight-control pilot

The original `pipeline.py` uses only the canonical 1,024-sample `pilot_v1`
dataset, computes fixed-reference log-mel spectrograms, and trains one small CNN
to estimate eight normalized Vital parameters. Its defaults, checkpoints and
results below are preserved as historical engineering evidence, not v4 results.
That historical pipeline has no ensembles or reliability calibration.

## Environment

From the repository root, activate the project virtual environment and install the C2 dependencies:

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install -r c2_estimation/requirements.txt
```

## Run the canonical baseline

```powershell
python c2_estimation/pipeline.py
```

The defaults are the canonical manifest at `data/manifests/pilot_v1.csv`, dataset configuration at `data/manifests/pilot_v1_config.json`, fixed split/training seed `20260826`, 60 maximum epochs, early-stopping patience 12, and CPU execution. The script validates that all 1,024 mono, 44.1 kHz, three-second WAV files exist and match the dataset configuration before training.

The deterministic split uses a NumPy seeded permutation. For 1,024 rows it assigns 819 training samples, 102 validation samples, and 103 test samples. The exact assignments and an assignment hash are saved with the run outputs.

To rebuild the feature cache explicitly:

```powershell
python c2_estimation/pipeline.py --force-preprocess
```

To run the focused implementation tests:

```powershell
python -m unittest discover -s c2_estimation/tests -v
```

## Preprocessing and model

Each full three-second waveform is converted to a 64-band log-mel power spectrogram with a 2,048-sample Hann window, 512-sample hop, 20 Hz lower frequency, 20 kHz upper frequency, reflect padding, and an 80 dB floor relative to fixed 0 dBFS. Inputs are standardized with the training split's scalar mean and standard deviation only, so validation and test data do not influence preprocessing statistics.

The CNN has three convolution/ReLU/max-pooling blocks, adaptive average pooling, and a two-layer regressor. Its eight sigmoid outputs are mapped to the normalized parameter ranges frozen in `pilot_v1_config.json`. Training minimizes squared error after dividing each parameter error by its configured range, which gives the eight targets equal weighting despite their different pilot ranges.

## Outputs

The pipeline writes these artifacts under `c2_estimation/outputs/`:

- `split_manifest.csv` - every sample's deterministic train, validation, or test assignment and eight targets.
- `spectrogram_examples/*.png` - four fixed, directly comparable example log-mel images.
- `best_model.pt` - best-validation PyTorch checkpoint plus preprocessing and target metadata.
- `training_history.csv` and `learning_curves.png` - train/validation loss history.
- `test_predictions.csv` - held-out actual values, predictions, and signed errors.
- `test_metrics.csv` and `test_metrics.json` - per-parameter MAE, RMSE, and R² in normalized synthesizer units.
- `run_config.json` - dataset/manifest hash, split hash, preprocessing, training configuration, package versions, and macro test summary.

The cached feature tensor is stored at `data/processed/c2_pilot_v1_logmel.npz`; that directory is already excluded from version control because it is reproducible from the WAV files.

## Verified pilot result

The checked-in output files report the exact test-set result for the command above. Metrics are measured only on the 103 held-out test samples and are reported in normalized synthesizer parameter units.

| Parameter | MAE | RMSE | R² |
| --- | ---: | ---: | ---: |
| `wave_frame` | 0.12371 | 0.16114 | 0.71015 |
| `filter_cutoff` | 0.06061 | 0.09006 | 0.73098 |
| `filter_resonance` | 0.19920 | 0.23003 | -0.03846 |
| `filter_drive` | 0.18359 | 0.21071 | 0.17279 |
| `amp_attack` | 0.01878 | 0.02382 | 0.95722 |
| `amp_decay` | 0.07430 | 0.08942 | 0.25699 |
| `amp_sustain` | 0.09174 | 0.12705 | 0.63209 |
| `amp_release` | 0.01759 | 0.02459 | 0.94355 |

The macro averages are MAE `0.09619`, RMSE `0.11960`, and R² `0.54566`. Resonance and drive are clear weaknesses of this first small-data baseline; no ensemble or calibration work has been added to compensate for them.

Verification completed with the dependency versions pinned above:

- Three focused tests pass for split reproducibility/completeness and metric calculation.
- The checkpoint reloads successfully and contains the expected eight-target metadata.
- A second complete 60-epoch CPU run from the feature cache reproduced the split manifest, all 103 test predictions, and the metric CSV byte-for-byte (identical SHA-256 hashes).
