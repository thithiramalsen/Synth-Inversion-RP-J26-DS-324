# C2 development audit and perturbation robustness

Measured on 14 October 2026, using the existing frozen three-member ensemble and
13-control v4 protocol. These are **development findings, not final-test results**.
No models, predictions, synthesizer source, calibrators or default .02 step were
changed by these analyses. No human study or test-set evaluation was performed.

## Completed development calibration

The workflow completed 128 training smoke, 2,048 calibration and 512
reliability-validation diagnostic cases, with four renderer audits per partition.
The calibration partition fits the transforms and logistic coefficients; reliability
validation selects regularization C. Therefore its reported scores and bootstrap
intervals are descriptive development evidence, not unbiased test estimates.

The three-member ensemble's macro inverse-validation z MAE is **.127991**, versus
**.126112** for the deterministic baseline on the same 4,096 examples. Point
accuracy did not improve. Probability quality is a separate question.

At the primary correctness tolerance `abs(predicted_z - actual_z) <= .05`:

| Probability model | Macro Brier on 512 validation clips |
|---|---:|
| Constant g0 | .138242 |
| g(U) | .116267 |
| g(U,S) | .115908 |
| g(U,R) | .115572 |
| g(U,S,R) | .115385 |

Lower Brier is better. U is ensemble variance, S is local forward sensitivity and
R is reconstruction residual. These are measured on the same delivered prediction
for every ablation. Secondary correctness tolerances .025/.10 reuse the same renders.

## Per-control and paired-comparison audit

The audit uses 2,000 paired whole-audio bootstrap replicates, seed 20261013: all
13 controls from an audio example are resampled together. Differences are full
g(U,S,R) minus the named comparator; negative favours the full model.

| Comparator / controls | Brier difference | Paired 95% interval |
|---|---:|---:|
| g(U), all 13 | -.000882 | [-.001684, -.000089] |
| g(U,R), all 13 | -.000187 | [-.000757, .000400] |
| g(U), excluding wave frame (exploratory) | +.000024 | [-.000422, .000486] |
| g(U,R), excluding wave frame (exploratory) | +.000109 | [-.000291, .000517] |

There is a small development improvement over U alone, concentrated in wave frame.
The conditional comparison against U+R does **not establish an extra benefit from
S**. Removing wave frame is a post-hoc explanatory analysis, not a new primary
endpoint. Per-control intervals are exploratory, without multiplicity adjustment.
These intervals condition on the fitted models; they do not capture retraining-seed
uncertainty or remove the effects of validation-based model selection.

The saved `per_parameter_audit.csv` exposes MAE, RMSE, R2, correctness counts and
probability/ranking metrics for all 13 controls on these 512 clips. For example,
amplitude release has z MAE .00358 and 510/512 successes, whereas bend has MAE
.23776 and 59/512 successes. Amplitude release has only two failures, making its
failure-ranking estimates particularly fragile. Do not substitute these subset
metrics for the separate 4,096-clip inverse-validation metrics.

The matched-coverage table/figure compares failure risk and MAE at the same retained
fraction. These are per-control selections, not a validated whole-patch acceptance
policy. The audit saves both aggregate and per-control evidence rather than only
the favourable macro comparison.

Artifacts: `data/processed/c2_v4/results_audit_v1/` contains five CSV tables,
`per_parameter_brier_differences.png`, `matched_coverage_audit.png`, `RESULTS.md`
and `summary.json` with source/output hashes.

## Fixed 256-clip step-size study

The first 256 **preassigned calibration diagnostic ranks** were selected independently
of errors or sensitivity values. The saved .02 results were hash-verified and reused;
.01 and .05 were rendered around exactly the same predictions: 512 new diagnostic
cases, not perturbation of the entire 131,072-clip corpus. Each case measures all
13 controls separately. Four repeat-render, true-roundtrip and inactive-control
audits passed at each additional step. Actual engine readbacks determine denominators.

| Control | Spearman .01/.02 | Spearman .02/.05 | p95 absolute log1p(S) difference, .02/.05 |
|---|---:|---:|---:|
| wave_frame | .9761 | .9242 | .6900 |
| bend_amount | .9805 | .9383 | .6933 |
| filter_cutoff | .9994 | .9956 | .2158 |
| filter_resonance | 1.0000 | 1.0000 | .0046 |
| filter_drive | 1.0000 | 1.0000 | .0011 |
| amp_attack | .9981 | .9923 | .4047 |
| amp_decay | 1.0000 | 1.0000 | .0086 |
| amp_sustain | 1.0000 | .9998 | .0071 |
| amp_release | 1.0000 | .9998 | .0085 |
| filter_env_amount | 1.0000 | .9999 | .0075 |
| filter_env_attack | .9996 | .9984 | .0781 |
| filter_env_decay | .9999 | .9998 | .0064 |
| filter_env_sustain | 1.0000 | .9999 | .0031 |

Most controls retain highly similar sensitivity rankings. Wave frame and bend are
more step-dependent. Amplitude attack retains a high rank correlation but changes
in magnitude: rank agreement alone is not sufficient evidence of stability. These
patterns also appear in common-interior cases; they are not explained solely by
boundary handling. A displayed 1.0000 is rounded, not necessarily exact equality.

The CSV retains all three step pairs, common-interior and boundary-affected groups,
group sizes, zero counts and mode switches. Empty/constant rank comparisons are
undefined, not converted to zero. Some boundary groups contain only two cases;
their correlations must not be treated as robust population evidence. The log1p
differences are not percentage changes or perceptual units.

This is a local robustness study, not a formal derivative-convergence test, global
identifiability proof or perceptual-equivalence study. No post-hoc pass threshold
was invented. **Retain .02 and the existing calibrators**; the study does not select
a replacement step or refit probabilities.

Artifacts: `data/processed/c2_v4/step_stability_v1/` contains 9,984 measurement rows,
117 pair/group summaries, `step_size_rank_agreement.png`,
`step_size_magnitude_agreement.png`, checksummed per-case JSONs, run configuration,
status, summary and `RESULTS.md`. A completed-run rerun verified the hashes and
returned without additional rendering.

## Commands and verification

Run from the repository root. These exact paths already hold completed artifacts:

```powershell
.\venv\Scripts\python.exe -B -m c2_estimation.v4.audit_results --output data/processed/c2_v4/results_audit_v1 --bootstrap 2000
.\venv\Scripts\python.exe -B -m c2_estimation.v4.stability --output data/processed/c2_v4/step_stability_v1 --workers 4
.\venv\Scripts\python.exe -B -m c2_estimation.v4.verification --output data/processed/c2_v4/verification_validation_viewer_v1
```

Use a fresh output name to reproduce the audit or test report. The step study
supports verified resume with the identical command, source files and settings;
never run two writers to one directory. Do not delete partial cases to resume.

The saved CPU test report records 43 discovered tests, 41 passed and two CUDA-only
skips. The new tests cover fixed subset selection, step agreement, boundary/constant
cases, paired comparisons, row alignment and viewer export safeguards. Synthetic
tests establish implementation checks, not the scientific hypothesis. Figures
were visually inspected, and the separate [saved-results viewer](DEMO.md) was
browser-tested with real outputs.

## Remaining research decisions

The immediate evidence supports a functioning pipeline and modest development
probability improvements, not a claim that sensitivity universally improves
reliability. Before the one-time untouched-test evaluation, freeze the final method,
primary comparisons and any operational decision policy. Additional hypotheses or
model changes require separate documented development experiments. A small later
human study can explore perceived reconstruction quality and usefulness of the
reliability display; it cannot replace objective held-out calibration evaluation.
