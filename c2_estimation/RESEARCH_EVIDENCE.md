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

## Ensemble and development calibration complete

`ensemble_full_v1/` contains three completed independent Gaussian-head CNNs with
different initialization/shuffle seeds, strict CUDA determinism and epoch checkpoint
resume. Each ran 60 epochs; selected epochs are 57/59/58 and checkpoint reloads
reproduce predictions exactly. It saves member NLL/point-error histories, mean predictions, within-member variance,
between-member disagreement and total mixture variance. Means are sigmoid-bounded;
variances use softplus plus `1e-4` in z². The Gaussian objective is a practical
working model on bounded labels, **not a calibrated or truncated posterior**.
Within/between components are operational summaries, not proven pure aleatoric/
epistemic decompositions. See [deep ensembles](https://arxiv.org/abs/1612.01474).

Ensemble inverse-validation macro z MAE is **.127991**, versus **.126112** for the
deterministic model on the same 4,096 IDs; this is not a point-accuracy improvement.
The saved ensemble EDA pack has 11 figures, including raw uncertainty versus error.
The 128-clip training diagnostic smoke batch passed, including four renderer audits.

`development_uncertainty_v1/status.json` records completion at 2026-10-14 06:49:57 UTC.
The interrupted workflow resumed from 994 saved calibration cases and finished all
2,048 calibration and 512 reliability-validation cases, with four renderer audits
per partition. All three correctness-tolerance calibrations completed. These fixed
subsets, not the whole corpus, were measured.
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
evidence, not unbiased final test conclusions**. A frozen final method, held-out
test and the small human validation study remain later stages. Stronger or larger
ensembles remain optional research decisions, not prerequisites silently launched
by these commands. C3 is not changed.

## Per-control audit and perturbation robustness

See [VALIDATION_RESULTS.md](VALIDATION_RESULTS.md) for interpretation. The new packs
preserve the original models, predictions, calibrators and .02 default step:

| Artifact directory | Saved evidence | Purpose and limit |
|---|---|---|
| `results_audit_v1/` | Per-control MAE/RMSE/R2, success counts, probability/ranking scores, matched-coverage CSVs; two figures; paired whole-audio Brier intervals | 512 reliability-validation cases; descriptive because this partition selected regularization |
| `step_stability_v1/` | 9,984 control/step measurements; 117 pair/group summaries; rank heatmaps and magnitude scatterplots; checksummed cases and eight new renderer audits | 256 fixed calibration clips, .01/.02/.05; no refitting or formal derivative-convergence claim |
| `viewer_v1/` | Six examples, 174 PCM16 playback WAVs, six spectrogram figures, four copied research figures, data and checksums | First six validation diagnostic ranks, not quality-selected; saved-results demonstration only |
| `verification_validation_viewer_v1/` | Test log, counts and source hashes | 43 discovered, 41 passed, two CUDA-only skips; synthetic checks are not research results |

Full g(U,S,R) macro Brier is .115385 versus .116267 for g(U) and .115572 for g(U,R).
The paired full-minus-g(U,R) interval includes zero: the extra contribution of S
is not established. Excluding wave frame removes the aggregate improvement over
g(U); that is an exploratory explanation, not a replacement endpoint.

Step-size ranks are highly consistent for most controls. Wave frame and bend have
lower agreement; amplitude attack also shows magnitude changes despite high rank
agreement. Common-interior and boundary-affected results, sample sizes and undefined
rank scores are retained. Small boundary groups must not be overinterpreted.

Browser checks covered example/control/calibrator switching, reference reveal,
target/reconstruction playback, exclusive playback and all four evidence figures.
No JavaScript errors were observed. Screenshots are saved as `viewer-preview.jpg`
and `viewer-controls.jpg`. Loopback HTTP was tested; direct `file://` opening was
not tested because the browser automation surface does not permit that protocol.

## Rebuild and inspect

Commands are recorded in [V4_README.md](V4_README.md). Rebuild into a new output
directory to preserve measured artifacts. Large generated artifacts live in ignored
`data/processed/c2_v4/`; back them up separately from Git before relocating the repo.
Keep sources/environment unchanged while a run is active; signatures detect drift.
