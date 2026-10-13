# C2 research evidence register

This register separates **saved measured evidence**, implementation checks, and
experiments that are still running. It is not a claim that C2 is finished.

## Saved EDA and baseline evidence

The reproducible pack is `data/processed/c2_v4/evidence_baseline_full_v1/`.
It contains **10 PNG figures, their CSV tables, and `evidence.json`** recording
input/output hashes, source fingerprint, partition policy and measured checks.
Key figures were visually inspected for readable axes/labels. The complete corpus
verification is inherited from C1 and clearly labelled as such; this script also
freshly hash-verifies a fixed 128-clip training-only audio subset.

| Figure | Saved table(s) | Research purpose and limit |
|---|---|---|
| `target_distributions_and_split_balance.png` | `target_histogram_bins.csv`, `target_descriptive_statistics.csv`, `split_distribution_balance.csv` | Actual engine-readback coverage and non-test split balance; not a significance test |
| `training_parameter_correlation.png` | `training_parameter_correlation.csv` | Training-only sampling correlations; does not measure acoustic identifiability |
| `experimental_partition_counts.png` | `split_counts.csv` | Disjoint train/calibration/inverse-validation/reliability-validation/test assignments; test count only |
| `training_audio_quality.png` | `training_audio_qa_128.csv` | Conditioned audio peak/RMS/DC, duration/rate and hashes; no independent loudness normalization |
| `validation_actual_vs_predicted.png` | Frozen run `validation_predictions.csv` | All 13 controls' recovery patterns, rather than just a macro score |
| `validation_error_distributions.png` | `validation_error_histogram_bins.csv` | Signed errors, bias and ±.05 parameter tolerance; not perceptual similarity |
| `validation_per_parameter_errors.png` | `validation_metrics_and_mean_baseline.csv` | MAE/RMSE/R² and training-mean comparator |
| `validation_error_by_actual_value.png` | `validation_error_by_actual_value.csv` | Range-dependent weaknesses; true values are descriptive EDA, never deployed calibrator inputs |
| `filter_envelope_error_context.png` | `filter_envelope_error_by_true_depth.csv` | Error vs generating envelope depth; descriptive pattern, not proof of causality |
| `learning_curves.png` | Run `training_history.csv` | Training/validation evolution and model-selection evidence |

Current measured non-test metadata: **zero missing parameter values, zero duplicate
complete parameter vectors**. The largest absolute off-diagonal training correlation
is **.004659**, consistent with broad low-correlated control sampling, not evidence
that the controls are independently recoverable from audio.

On inverse validation, filter-envelope attack MAE is **.235356** in the lowest
true-depth bin `[0,.1)` and **.130205** in `[.9,1)`. This is consistent with the
weak-depth concern and motivates the forward-sensitivity experiment. It does not
establish that S will improve calibrated reliability: the ablations must test that.

Other already saved evidence:

- `protocol_v1/`: immutable source hashes, seed, split identities, diagnostic ranks,
  tolerances, actual-readback coordinate definition and test exclusion.
- `baseline_full_v1/`: checkpoints, train-only normalization, learning history,
  four spectrogram examples, all-control metrics, delivered predictions, exact
  checkpoint reload and matched development comparison.
- `worked_example_full_v1/`: target/prediction/known-true/midpoint/perturbation audio,
  MR-STFT components, engine readbacks, known inactive-control check and frozen patch.
- `forward_batch_check_v1/verification.json`: the new batch core agrees with that
  saved example's reconstruction residual and all 13 sensitivities; repeat,
  exact true-parameter roundtrip, inactivity and prediction-preservation checks pass.
- `forward_parallel_check_v3/verification.json`: two spawned Windows workers
  reproduce the serial diagnostic exactly under the production one-thread BLAS
  policy. Audio sample hashes also agree. The earlier strict-dictionary comparison
  exposed only a 1.67e-16 R / 1.55e-15 maximum S reduction-order difference with
  mismatched parent/worker thread settings; the saved comparison in
  `forward_parallel_check_v2/` is retained rather than hidden or overwritten.
- `verification_cpu_v2/`, `verification_gpu_v1/`: saved test logs, counts,
  skip reasons and source fingerprints. Synthetic test scores are **not** research
  results; temporary test fixtures are removed after testing.

## Data-science safeguards applied

Labels are actual recorded synth readbacks, transformed by each research interval;
Sobol proposal coordinates are not silently substituted. Splits and diagnostic
subsets are chosen before errors are observed. The previously studied v4 pilot
prefix is training-only. All feature normalization is fitted on training rows.
Inverse-validation selects CNN checkpoints; separate calibration rows fit logistic
coefficients/scalers; reliability-validation selects regularization. No source
audio, labels or generator settings are overwritten.

Point-estimation metrics remain separate from acoustic reconstruction distance and
correctness probabilities. Per-control weaknesses and mean baselines are exposed.
Raw ensemble variance is **not** displayed as probability. The calibrator has no
true-error/true-parameter feature, no class rebalancing, explicit single-class
fallback, and declared ranking/binning/tie policies. Bootstrap samples whole audio
examples so their 13 controls are kept together.

## Next experiment: implemented, not yet a completed research result

`ensemble_full_v1/` trains three independent Gaussian-head CNNs with different
initialization/shuffle seeds, strict CUDA determinism and epoch checkpoint resume.
It saves member NLL/point-error histories, mean predictions, within-member variance,
between-member disagreement and total mixture variance. Means are sigmoid-bounded;
variances use softplus plus `1e-4` in z². The Gaussian objective is a practical
working model on bounded labels, **not a calibrated or truncated posterior**.
Within/between components are operational summaries, not proven pure aleatoric/
epistemic decompositions. See [deep ensembles](https://arxiv.org/abs/1612.01474).

`development_uncertainty_v1/status.json` records actual workflow progress. After all
members finish, the workflow saves ensemble EDA and freezes predictions for 128
training smoke clips. Only after smoke/audit checks pass does it render the fixed
2,048 calibration and 512 reliability-validation subsets, not the whole corpus.
Perturbation audio is streamed/discarded; readbacks, steps, case checksums and S/R
are saved. The same delivered patch is used for every ablation.

The five probability baselines are g0, g(U), g(U,S), g(U,R), g(U,S,R), with a separate
raw-U ranking baseline. Per-control L2 logistic models are fitted with SciPy's
[L-BFGS-B](https://docs.scipy.org/doc/scipy/reference/optimize.minimize-lbfgsb.html),
using calibration-only transforms/scalers and C=.01/.1/1/10. No new scikit-learn
installation or frozen synthesis-environment changes are required. Brier is the
primary probabilistic score; reliability diagrams/ECE examine calibration, while
failure AUROC/AP, risk/coverage and matched-coverage MAE examine ranking/abstention.
Two thousand paired whole-audio bootstrap replicates summarize Brier differences.
Tolerance .025/.05/.10 analyses reuse the same predictions and diagnostic distances.

Reliability-validation also chooses C, so its scores/intervals are **development
evidence, not unbiased final test conclusions**. Stronger models, five-member final
runs, perturbation-step checks, frozen final method, held-out test and the small
human validation study remain later stages. C3 is not changed.

## Rebuild and inspect

Commands are recorded in [V4_README.md](V4_README.md). Rebuild into a new output
directory to preserve measured artifacts. Large generated artifacts live in ignored
`data/processed/c2_v4/`; back them up separately from Git before relocating the repo.
Keep sources/environment unchanged while a run is active; signatures detect drift.
