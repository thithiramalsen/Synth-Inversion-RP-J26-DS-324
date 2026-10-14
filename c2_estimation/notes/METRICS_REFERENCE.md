# C2 metrics: definitions, measured results and interpretation

Each local file link is followed by its full path as plain text. A final `:number` identifies the source line; in VS Code, open the file with `Ctrl+P` and jump to that line with `Ctrl+G`.

Snapshot: 15 October 2026. These tables come from saved non-test outputs, not new
training or test evaluation. Display values are rounded to six decimal places;
original CSV/JSON files preserve precision. All recovery errors below use research
coordinates z unless stated otherwise. Read with the
[component guide](D:/VSCode/GitHub/Synth-Inversion-RP/c2_estimation/COMPONENT_STUDY_GUIDE.md) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/c2_estimation/COMPONENT_STUDY_GUIDE.md`).

## Contents

Jump directly to the results or definitions you need.

| Topic | Jump to |
|---|---|
| Definitions | [1. Which kind of number am I looking at?](#1-which-kind-of-number-am-i-looking-at) · [2. Recovery metrics in plain language and equations](#2-recovery-metrics-in-plain-language-and-equations) · [5. Probability, ranking and selective metrics](#5-probability-ranking-and-selective-metrics) |
| Training results | [3. Single CNN and ensemble: the same 4,096 inverse-validation clips](#3-single-cnn-and-ensemble-the-same-4096-inverse-validation-clips) |
| Correctness labels and recovery | [4. What is a correctness label?](#4-what-is-a-correctness-label) |
| Calibration and uncertainty results | [6. All five probability models: macro development results](#6-all-five-probability-models-macro-development-results) · [7. Per-parameter Brier for every probability ablation](#7-per-parameter-brier-for-every-probability-ablation) · [8. Full U+S+R reliability results for all parameters](#8-full-usr-reliability-results-for-all-parameters) · [9. Raw uncertainty ranking before logistic calibration](#9-raw-uncertainty-ranking-before-logistic-calibration) |
| Matched-coverage evaluation | [10. Same 50% coverage: retain 256 settings per parameter](#10-same-50-coverage-retain-256-settings-per-parameter) |
| Tolerance checks and statistical comparisons | [11. Different definitions of correct: secondary tolerance analysis](#11-different-definitions-of-correct-secondary-tolerance-analysis) · [12. Paired uncertainty around Brier differences](#12-paired-uncertainty-around-brier-differences) |
| Audio diagnostics and perturbation validation | [13. Reconstruction residual R and sensitivity S](#13-reconstruction-residual-r-and-sensitivity-s) · [14. Perturbation-step agreement on 256 calibration clips](#14-perturbation-step-agreement-on-256-calibration-clips) |
| Audio QA and result files | [15. Audio QA numbers are different again](#15-audio-qa-numbers-are-different-again) · [16. Where are all remaining numbers?](#16-where-are-all-remaining-numbers) |


## 1. Which kind of number am I looking at?

| Number | Simple meaning | Available for a new unknown clip? |
|---|---|---|
| Predicted z / Vital n | The model's proposed knob setting | Yes |
| Parameter error, MAE, RMSE, R2 | Difference from known original settings | Only if original settings are supplied independently |
| U | Ensemble's predictive variance, in z squared | Yes, from trained models |
| R | Measured difference between input and predicted sound | Yes, after rendering |
| S_j | Audio change when parameter j moves a little | Yes, after perturbation renders |
| q_j | Fitted probability of original-parameter recovery within tolerance | Yes, with calibration limitations |
| Brier, ECE, failure AUROC/AP, AURC | Population evaluation of reliability outputs | Need a labelled evaluation set |
| Peak/RMS/DC/hash | Signal quality or integrity checks | Yes; they do not measure parameter accuracy |

There is no validated universal low/medium/high score scale, perceptual R cutoff
or operational Accept/Approximate/Abstain policy yet.

## 2. Recovery metrics in plain language and equations

Let `e_ij = predicted_z_ij - original_z_ij`, for clip i and parameter j.

| Metric | Formula for one parameter | Explanation |
|---|---|---|
| MAE | mean(abs(e)) | Average distance from the correct knob position |
| MSE | mean(e^2) | Squared-error training/evaluation objective; large misses matter more |
| RMSE | sqrt(mean(e^2)) | Squared-error measure returned to the original coordinate units |
| R2 | 1 - sum(e^2)/sum((true_z-mean(true_z))^2) | Improvement over predicting this evaluation set's mean; 1 is perfect, 0 matches that reference, negative is worse |

R2 is undefined if the target is constant. It is not a probability or a percentage
of correct knobs. The saved training-mean predictor is a separate practical baseline;
its constant comes from training, whereas the R2 denominator uses the evaluated
target mean. R2 is unchanged by an affine coordinate rescaling; MAE/RMSE are not.

An MAE .05 means 5% of a parameter's restricted interval, not 5% of full physical
frequency/time or a perceptual threshold. Macro MAE gives each of 13 parameters
equal weight. Averaging 13 RMSEs is not the same as taking the square root of
the all-parameter MSE; say which aggregation you use.

Code: [baseline.regression_metrics](D:/VSCode/GitHub/Synth-Inversion-RP/c2_estimation/v4/baseline.py:53) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/c2_estimation/v4/baseline.py:53`).

## 3. Single CNN and ensemble: the same 4,096 inverse-validation clips

| Parameter | Single MAE | Single RMSE | Single R2 | Ensemble MAE | Ensemble RMSE | Ensemble R2 |
| --- | --- | --- | --- | --- | --- | --- |
| wave_frame | 0.078432 | 0.106992 | 0.861098 | 0.066230 | 0.091645 | 0.898087 |
| bend_amount | 0.216818 | 0.262532 | 0.165682 | 0.241761 | 0.280462 | 0.047828 |
| filter_cutoff | 0.056082 | 0.081588 | 0.919057 | 0.044266 | 0.067620 | 0.944400 |
| filter_resonance | 0.149575 | 0.191556 | 0.552953 | 0.156537 | 0.198985 | 0.517608 |
| filter_drive | 0.180036 | 0.221752 | 0.404213 | 0.215541 | 0.254445 | 0.215587 |
| amp_attack | 0.040772 | 0.053499 | 0.965886 | 0.015749 | 0.026980 | 0.991324 |
| amp_decay | 0.090675 | 0.131770 | 0.790556 | 0.076709 | 0.126803 | 0.806047 |
| amp_sustain | 0.049487 | 0.066501 | 0.947826 | 0.031470 | 0.048848 | 0.971849 |
| amp_release | 0.025746 | 0.035617 | 0.984816 | 0.003329 | 0.005081 | 0.999691 |
| filter_env_amount | 0.168136 | 0.210775 | 0.464376 | 0.186703 | 0.230561 | 0.359095 |
| filter_env_attack | 0.171434 | 0.213378 | 0.457955 | 0.196728 | 0.238382 | 0.323473 |
| filter_env_decay | 0.223305 | 0.266838 | 0.158404 | 0.240880 | 0.281031 | 0.066491 |
| filter_env_sustain | 0.188961 | 0.233032 | 0.346583 | 0.187984 | 0.233534 | 0.343768 |

Single CNN macro MAE: **.126112**; ensemble macro MAE: **.127991**. The ensemble
improves some parameters but has slightly worse average MAE. Single CNN MSE is
.031867 versus .083213 for the training-mean baseline; ensemble MSE is .035284.
The two models use different training objectives, so differences do not isolate
ensemble averaging alone.

Sources:
[single CNN metrics](D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/baseline_full_v1/validation_metrics.csv) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/baseline_full_v1/validation_metrics.csv`),
[ensemble metrics](D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/ensemble_full_v1/parameter_metrics.csv) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/ensemble_full_v1/parameter_metrics.csv`),
[training-mean baseline](D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/baseline_full_v1/mean_baseline_metrics.csv) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/baseline_full_v1/mean_baseline_metrics.csv`).
Each recovery CSV also includes Vital-normalized coordinate metrics.

## 4. What is a correctness label?

`y_ij = 1[abs(predicted_z_ij - original_z_ij) <= tau]`.
Primary tau=.05; secondary tau=.025/.10. The boundary is inclusive.
The model estimates q=P(y=1 | measured features), not P(perceptually identical audio).

The following is a **different** set: the 512 reliability-validation clips. It
must not be substituted for the 4,096-clip inverse-validation result.

| Parameter | MAE z | RMSE z | R2 | Successes / 512 | Failures |
| --- | --- | --- | --- | --- | --- |
| wave_frame | 0.066408 | 0.093852 | 0.887424 | 257 | 255 |
| bend_amount | 0.237756 | 0.278356 | 0.025322 | 59 | 453 |
| filter_cutoff | 0.043168 | 0.066148 | 0.947494 | 369 | 143 |
| filter_resonance | 0.161219 | 0.205101 | 0.496555 | 112 | 400 |
| filter_drive | 0.220873 | 0.261189 | 0.199929 | 64 | 448 |
| amp_attack | 0.014941 | 0.026328 | 0.991552 | 474 | 38 |
| amp_decay | 0.073794 | 0.119388 | 0.838172 | 306 | 206 |
| amp_sustain | 0.031281 | 0.046633 | 0.973734 | 422 | 90 |
| amp_release | 0.003575 | 0.007047 | 0.999396 | 510 | 2 |
| filter_env_amount | 0.187707 | 0.230744 | 0.382301 | 81 | 431 |
| filter_env_attack | 0.181858 | 0.223940 | 0.338150 | 86 | 426 |
| filter_env_decay | 0.236488 | 0.277070 | 0.062193 | 50 | 462 |
| filter_env_sustain | 0.202163 | 0.250733 | 0.303487 | 88 | 424 |

Failure counts matter. Amplitude release has only two failures, so its ranking
metrics can change greatly if just one example changes. Bend and filter-envelope
decay have many failures despite some patches reconstructing reasonably well.

## 5. Probability, ranking and selective metrics

| Metric | Simple explanation | Exact policy here |
|---|---|---|
| Brier | Squared error of a probability against a 0/1 outcome | mean((q-y)^2); lower is better; primary probability score |
| Reliability diagram | Compare what q says with how often predictions succeed | Plot bin mean q against observed success; diagonal is agreement |
| ECE | Average gap between stated probability and observed frequency | 10 equal-frequency bins, weighted absolute gap; lower is better |
| Failure AUROC | Does a failing estimate usually get a higher failure score than a successful one? | Failure=1-y; score=1-q, or raw U; average-rank ties; higher is better |
| Failure AP | Precision of detected failures as more are included | Noninterpolated average precision; score ties grouped; higher is better |
| Coverage | Fraction of parameter predictions kept | k/n after sorting by q descending, or U ascending |
| Risk at coverage | Fraction of kept estimates outside tolerance | Cumulative failures/k; lower is better |
| AURC | Average retained failure risk along the coverage curve | Arithmetic mean over prefixes k=1..n; lower is better |
| MAE at coverage | Parameter error among estimates kept at the same rate | Cumulative absolute z error/k; lower is better |

Brier evaluates probability quality, not calibration in isolation. A constant can
score well on an imbalanced outcome; this is why g0, class counts and ranking are
reported too. ECE depends on binning and is not proof of perfect calibration.
AUROC is .5 for a constant score with both classes present. Random-score AP is
related to failure prevalence, so compare AP within the same parameter/outcome,
not against .5 universally. The implementation reports **AP**, not trapezoidal
PR-AUC; do not silently rename the statistic.

Single-class AUROC/AP are undefined. q sorting is stable in preassigned diagnostic
order. Equal-q ties may be split between ECE bins. A constant predictor's risk
curve follows that fixed tie order, not learned discrimination. At nominal 10%
coverage, ceil(512*.1)=52 predictions are kept; actual coverage is 52/512.
At 50%, exactly 256 predictions per parameter are kept.

These are parameter-level selections. Different parameters can retain different
audio IDs; this does not define a whole-patch acceptance rule.

The exact calculation:

[c2_estimation/v4/calibration.py:111](D:/VSCode/GitHub/Synth-Inversion-RP/c2_estimation/v4/calibration.py:111) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/c2_estimation/v4/calibration.py:111`)

```python
def probability_metrics(y,q,error):
    if not np.isfinite(q).all() or np.any((q<0)|(q>1)):
        raise ValueError("Invalid correctness probabilities")
    ordered = np.argsort(q,kind="stable")
    bins = []
    for k,ids in enumerate(np.array_split(ordered,min(10,len(y)))):
        bins.append({"bin":k,"count":len(ids),"mean_q":float(q[ids].mean()),"observed_success":float(y[ids].mean()),
                     "min_q":float(q[ids].min()),"max_q":float(q[ids].max())})
    ece = sum(b["count"]*abs(b["mean_q"]-b["observed_success"]) for b in bins)/len(y)
    coverage,risk,mae = risk_curve(y,q,error)
    result = {"brier":float(np.square(q-y).mean()),"ece_10_equal_frequency":float(ece),
              "aurc_discrete":float(risk.mean()),"success_count":int(y.sum()),"failure_count":int((1-y).sum()),
              **ranking_metrics(1-y,1-q)}
    for c in COVERAGES:
        i = max(1,int(np.ceil(len(y)*c)))-1
        result[f"risk_at_coverage_{c:g}"] = float(risk[i])
        result[f"mae_z_at_coverage_{c:g}"] = float(mae[i])
    return result,bins,(coverage,risk,mae)
```

Related code:
[ranking_metrics](D:/VSCode/GitHub/Synth-Inversion-RP/c2_estimation/v4/calibration.py:85) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/c2_estimation/v4/calibration.py:85`),
[risk_curve](D:/VSCode/GitHub/Synth-Inversion-RP/c2_estimation/v4/calibration.py:102) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/c2_estimation/v4/calibration.py:102`).

## 6. All five probability models: macro development results

| Model | Macro Brier | Macro ECE | Macro AURC |
| --- | --- | --- | --- |
| g0 | 0.138242 | 0.040681 | 0.568125 |
| g(U) | 0.116267 | 0.037460 | 0.462585 |
| g(U,S) | 0.115908 | 0.036614 | 0.459520 |
| g(U,R) | 0.115572 | 0.035921 | 0.462154 |
| g(U,S,R) | 0.115385 | 0.035282 | 0.459777 |

These are equal-weight macro averages over 13 per-control metrics. g(U,S) has
slightly lower AURC than the full model, while the full model has slightly lower
Brier/ECE. Raw U has no probability Brier/ECE because variance is not q.
Reliability-validation selected C, so these are development results.

## 7. Per-parameter Brier for every probability ablation

| Parameter | g0 | g(U) | g(U,S) | g(U,R) | g(U,S,R) |
| --- | --- | --- | --- | --- | --- |
| wave_frame | 0.250798 | 0.195597 | 0.189182 | 0.187582 | 0.183839 |
| bend_amount | 0.102051 | 0.075224 | 0.074995 | 0.074836 | 0.074752 |
| filter_cutoff | 0.201672 | 0.166640 | 0.166705 | 0.166238 | 0.166348 |
| filter_resonance | 0.170927 | 0.139412 | 0.139774 | 0.139140 | 0.139402 |
| filter_drive | 0.109394 | 0.107745 | 0.107746 | 0.107286 | 0.107240 |
| amp_attack | 0.068719 | 0.048988 | 0.049959 | 0.049244 | 0.049713 |
| amp_decay | 0.240589 | 0.170184 | 0.169817 | 0.169991 | 0.169662 |
| amp_sustain | 0.145126 | 0.118832 | 0.119663 | 0.118487 | 0.119251 |
| amp_release | 0.003900 | 0.002918 | 0.003061 | 0.002903 | 0.003020 |
| filter_env_amount | 0.133177 | 0.128986 | 0.128839 | 0.129663 | 0.129552 |
| filter_env_attack | 0.140100 | 0.135815 | 0.136123 | 0.135901 | 0.136226 |
| filter_env_decay | 0.088188 | 0.088122 | 0.088013 | 0.088181 | 0.088088 |
| filter_env_sustain | 0.142508 | 0.133004 | 0.132925 | 0.132983 | 0.132908 |

Lower is better. Wave frame contributes much of the improvement over U alone.
This table exposes small regressions as well as improvements; the full model
does not improve every parameter.

## 8. Full U+S+R reliability results for all parameters

| Parameter | Brier | ECE | Failure AUROC | Failure AP | AURC |
| --- | --- | --- | --- | --- | --- |
| wave_frame | 0.183839 | 0.063845 | 0.796582 | 0.756097 | 0.266263 |
| bend_amount | 0.074752 | 0.025909 | 0.818274 | 0.968973 | 0.731550 |
| filter_cutoff | 0.166348 | 0.039445 | 0.761669 | 0.555094 | 0.132704 |
| filter_resonance | 0.139402 | 0.042601 | 0.768326 | 0.909925 | 0.603304 |
| filter_drive | 0.107240 | 0.036229 | 0.607910 | 0.905919 | 0.822321 |
| amp_attack | 0.049713 | 0.016051 | 0.938763 | 0.452329 | 0.007588 |
| amp_decay | 0.169662 | 0.034534 | 0.816597 | 0.755776 | 0.188760 |
| amp_sustain | 0.119251 | 0.044865 | 0.819510 | 0.449437 | 0.055260 |
| amp_release | 0.003020 | 0.003348 | 0.790196 | 0.504630 | 0.001073 |
| filter_env_amount | 0.129552 | 0.042942 | 0.629315 | 0.901057 | 0.784369 |
| filter_env_attack | 0.136226 | 0.043839 | 0.617234 | 0.885317 | 0.769311 |
| filter_env_decay | 0.088088 | 0.019180 | 0.542121 | 0.914386 | 0.888395 |
| filter_env_sustain | 0.132908 | 0.045873 | 0.693075 | 0.899882 | 0.726209 |

ECE uses the declared ten-bin policy. AUROC/AP target failures. An impressive
amplitude-release ranking number is fragile with only two failures; a high AP
for bend partly reflects that failures are common. Check the counts in section 4.

## 9. Raw uncertainty ranking before logistic calibration

| Parameter | Failure AUROC | Failure AP | AURC |
| --- | --- | --- | --- |
| wave_frame | 0.775738 | 0.762988 | 0.303827 |
| bend_amount | 0.815991 | 0.969646 | 0.733393 |
| filter_cutoff | 0.760475 | 0.551599 | 0.132233 |
| filter_resonance | 0.764241 | 0.906549 | 0.603546 |
| filter_drive | 0.575718 | 0.898192 | 0.831529 |
| amp_attack | 0.940207 | 0.464895 | 0.007457 |
| amp_decay | 0.814868 | 0.753220 | 0.188112 |
| amp_sustain | 0.823091 | 0.449212 | 0.054224 |
| amp_release | 0.927451 | 0.513158 | 0.000317 |
| filter_env_amount | 0.644267 | 0.903533 | 0.777903 |
| filter_env_attack | 0.624986 | 0.887161 | 0.766565 |
| filter_env_decay | 0.534589 | 0.915550 | 0.887312 |
| filter_env_sustain | 0.688974 | 0.895382 | 0.727180 |

Raw U ranks likely failures directly. g(U) is a learned monotonic logistic
transformation of log U, whose fitted sign can differ by parameter; therefore do
not assume their rankings must always be identical. Neither is guaranteed to
identify recordings outside the training domain.

## 10. Same 50% coverage: retain 256 settings per parameter

| Parameter | Raw-U risk | U risk | U+S+R risk | Raw-U MAE | U MAE | U+S+R MAE |
| --- | --- | --- | --- | --- | --- | --- |
| wave_frame | 0.289062 | 0.289062 | 0.257812 | 0.037209 | 0.037209 | 0.037498 |
| bend_amount | 0.796875 | 0.796875 | 0.804688 | 0.132718 | 0.132718 | 0.137616 |
| filter_cutoff | 0.144531 | 0.144531 | 0.136719 | 0.025886 | 0.025886 | 0.025240 |
| filter_resonance | 0.656250 | 0.656250 | 0.656250 | 0.108292 | 0.108292 | 0.111858 |
| filter_drive | 0.855469 | 0.855469 | 0.847656 | 0.197020 | 0.197020 | 0.194547 |
| amp_attack | 0.000000 | 0.000000 | 0.000000 | 0.005521 | 0.005521 | 0.006015 |
| amp_decay | 0.164062 | 0.164062 | 0.160156 | 0.028808 | 0.028808 | 0.028426 |
| amp_sustain | 0.039062 | 0.039062 | 0.046875 | 0.017603 | 0.017603 | 0.017931 |
| amp_release | 0.000000 | 0.000000 | 0.000000 | 0.002521 | 0.002521 | 0.002528 |
| filter_env_amount | 0.792969 | 0.792969 | 0.804688 | 0.142528 | 0.142528 | 0.155169 |
| filter_env_attack | 0.800781 | 0.800781 | 0.792969 | 0.150692 | 0.150692 | 0.149225 |
| filter_env_decay | 0.898438 | 0.898438 | 0.890625 | 0.228176 | 0.228176 | 0.238795 |
| filter_env_sustain | 0.761719 | 0.761719 | 0.761719 | 0.153296 | 0.153296 | 0.157632 |

Compare methods at equal retained count; a method cannot gain credit merely by
keeping fewer predictions. All variants and nominal coverages .1/.25/.5/.75/1 are
preserved in
[parameter_metrics.csv](D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/development_uncertainty_v1/calibration_tau_0.05/parameter_metrics.csv) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/development_uncertainty_v1/calibration_tau_0.05/parameter_metrics.csv`),
[raw_uncertainty_ranking.csv](D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/development_uncertainty_v1/calibration_tau_0.05/raw_uncertainty_ranking.csv) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/development_uncertainty_v1/calibration_tau_0.05/raw_uncertainty_ranking.csv`)
and [matched_coverage_audit.csv](D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/results_audit_v1/matched_coverage_audit.csv) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/results_audit_v1/matched_coverage_audit.csv`).
The full prefix curves are in
[risk_coverage.csv](D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/development_uncertainty_v1/calibration_tau_0.05/risk_coverage.csv) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/development_uncertainty_v1/calibration_tau_0.05/risk_coverage.csv`).

## 11. Different definitions of correct: secondary tolerance analysis

| Tolerance z | g0 | g(U) | g(U,S) | g(U,R) | g(U,S,R) |
| --- | --- | --- | --- | --- | --- |
| 0.025000 | 0.122540 | 0.103842 | 0.103434 | 0.103254 | 0.102946 |
| 0.050000 | 0.138242 | 0.116267 | 0.115908 | 0.115572 | 0.115385 |
| 0.100000 | 0.146619 | 0.122370 | 0.122377 | 0.122240 | 0.122300 |

Each row fits its own calibrators for that correctness event, using the same
predictions and .02 diagnostic renders. Do not treat a smaller Brier at one tau
as proof that that tau is better: event prevalence changes with tolerance.
Primary tau remains .05. Sources are the `summary.json` files in
`D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/development_uncertainty_v1/calibration_tau_0.025`,
`calibration_tau_0.05` and `calibration_tau_0.1`.

## 12. Paired uncertainty around Brier differences

| Comparison: full minus reference | Point difference | Paired 95% percentile interval |
|---|---|---|
| g(U), all 13 | -.000882 | [-.001684, -.000089] |
| g(U,R), all 13 | -.000187 | [-.000757, .000400] |
| g(U), exclude wave frame, exploratory | +.000024 | [-.000422, .000486] |
| g(U,R), exclude wave frame, exploratory | +.000109 | [-.000291, .000517] |

2,000 paired whole-audio resamples keep each clip's 13 controls together. The
conditional interval versus U+R includes zero. Thus additional benefit from S is
not established in this development analysis. The exploratory exclusion is not
the primary endpoint; no per-control multiple-comparison correction was applied.
Intervals condition on the fitted models and development selection and do not
include uncertainty from retraining.

Exact source:
[macro_paired_comparisons.csv](D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/results_audit_v1/macro_paired_comparisons.csv) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/results_audit_v1/macro_paired_comparisons.csv`),
[per_parameter_paired_comparisons.csv](D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/results_audit_v1/per_parameter_paired_comparisons.csv) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/results_audit_v1/per_parameter_paired_comparisons.csv`).

## 13. Reconstruction residual R and sensitivity S

At each FFT resolution:

```text
SC = ||A-B||F / (0.5*(||A||F + ||B||F) + 1e-12)
LM = mean(abs(ln(max(A,1e-4)) - ln(max(B,1e-4))))
D = mean_over_512_1024_2048(SC + LM)
R = D(target, predicted_audio)
S_j = D(minus_audio_j, plus_audio_j) / actual_readback_span_z_j
```

R and S are nonnegative numerical distances/activity scores. They do not have a
validated good/bad cutoff and cannot be converted to percentages of similarity.
The per-resolution components are retained in case JSON records.

Descriptive R distribution from already-saved non-test diagnostic files:

| Partition | Clips | Mean R | Median R | 90th percentile R | Min R | Max R |
| --- | --- | --- | --- | --- | --- | --- |
| calibration | 2048 | 0.313639 | 0.289749 | 0.523543 | 0.037167 | 0.996517 |
| reliability-validation | 512 | 0.319013 | 0.301779 | 0.524795 | 0.043359 | 0.872882 |

These are absolute residual summaries, not an audio-reconstruction comparison
against a population-wide midpoint baseline or a listening study. The known-true
roundtrip and midpoint comparisons elsewhere concern selected worked examples.

## 14. Perturbation-step agreement on 256 calibration clips

| Parameter | rho .01/.02 | rho .02/.05 | p95 abs log1p difference .02/.05 |
| --- | --- | --- | --- |
| wave_frame | 0.976079 | 0.924167 | 0.689971 |
| bend_amount | 0.980507 | 0.938325 | 0.693299 |
| filter_cutoff | 0.999386 | 0.995610 | 0.215802 |
| filter_resonance | 0.999999 | 0.999958 | 0.004595 |
| filter_drive | 0.999999 | 0.999972 | 0.001051 |
| amp_attack | 0.998069 | 0.992270 | 0.404696 |
| amp_decay | 0.999987 | 0.999964 | 0.008606 |
| amp_sustain | 0.999992 | 0.999824 | 0.007125 |
| amp_release | 0.999971 | 0.999812 | 0.008518 |
| filter_env_amount | 0.999999 | 0.999929 | 0.007522 |
| filter_env_attack | 0.999621 | 0.998441 | 0.078085 |
| filter_env_decay | 0.999914 | 0.999752 | 0.006365 |
| filter_env_sustain | 0.999996 | 0.999917 | 0.003133 |

Spearman compares rank ordering, not magnitude. The p95 column measures the 95th
percentile of abs(log(1+S_first)-log(1+S_second)), not a percentage or dB value.
Near-perfect ranks can coexist with changing magnitudes, especially amp attack.
Wave frame/bend are more scale-dependent. Keep .02; no calibrator was refitted.

All pairs, zero counts, group counts and modes are in
[step_size_agreement.csv](D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/step_stability_v1/step_size_agreement.csv) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/step_stability_v1/step_size_agreement.csv`).
The complete 9,984 measurements are in
[step_size_measurements.csv](D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/step_stability_v1/step_size_measurements.csv) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/step_stability_v1/step_size_measurements.csv`).
Tiny boundary groups and undefined constant/empty correlations must be interpreted cautiously.

## 15. Audio QA numbers are different again

Peak=max(abs(audio)); RMS=sqrt(mean(audio^2)); RMS dBFS=20*log10(RMS); DC=mean(audio).
Full generation flags silence at RMS below -60 dBFS, clipping at peak>=1 and a DC
warning at abs(mean)>=.005 or abs(mean)/RMS>=.20. The completed conditioned corpus
has zero flags under those rules. This does not say all raw audio had zero DC.

Exact hash equality, repeat rendering and known-parameter roundtrip are implementation
checks. They do not measure perceptual quality, correctness probability or proof
of unique parameter recovery.

## 16. Where are all remaining numbers?

| Evidence | Exact file |
|---|---|
| Member seeds/epochs/checkpoint hashes/variance summaries | [ensemble summary](D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/ensemble_full_v1/summary.json) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/ensemble_full_v1/summary.json`) |
| Epoch-by-epoch losses and errors | [member 0 history](D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/ensemble_full_v1/member_00/training_history.csv) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/ensemble_full_v1/member_00/training_history.csv`), equivalent files under member_01/member_02 |
| Selected C, fitted weights, transforms and calibration class counts | [calibrators.json](D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/development_uncertainty_v1/calibration_tau_0.05/calibrators.json) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/development_uncertainty_v1/calibration_tau_0.05/calibrators.json`) |
| Every candidate C validation score | [candidate_C_scores.csv](D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/development_uncertainty_v1/calibration_tau_0.05/candidate_C_scores.csv) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/development_uncertainty_v1/calibration_tau_0.05/candidate_C_scores.csv`) |
| Reliability bin counts and observed frequencies | [reliability_bins.csv](D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/development_uncertainty_v1/calibration_tau_0.05/reliability_bins.csv) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/development_uncertainty_v1/calibration_tau_0.05/reliability_bins.csv`) |
| Each clip's frozen prediction/U/S/R | [diagnostics.csv](D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/development_uncertainty_v1/diagnostics_reliability-validation/diagnostics.csv) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/development_uncertainty_v1/diagnostics_reliability-validation/diagnostics.csv`) |
| Actual perturbation endpoints and denominators | [perturbation_readbacks.csv](D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/development_uncertainty_v1/diagnostics_reliability-validation/perturbation_readbacks.csv) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/development_uncertainty_v1/diagnostics_reliability-validation/perturbation_readbacks.csv`) |
| Delivered q values for every model and clip | [validation_probabilities.parquet](D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/development_uncertainty_v1/calibration_tau_0.05/validation_probabilities.parquet) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/development_uncertainty_v1/calibration_tau_0.05/validation_probabilities.parquet`) |
| Implementation checks and skip reasons | [verification.json](D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/verification_validation_viewer_v1/verification.json) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/verification_validation_viewer_v1/verification.json`) |
| Snapshot source fingerprints | [STUDY_GUIDE_EVIDENCE.json](D:/VSCode/GitHub/Synth-Inversion-RP/c2_estimation/docs/STUDY_GUIDE_EVIDENCE.json) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/c2_estimation/docs/STUDY_GUIDE_EVIDENCE.json`) |

The read-only collector is
[collect_study_evidence.py](D:/VSCode/GitHub/Synth-Inversion-RP/c2_estimation/docs/collect_study_evidence.py) (path: `D:/VSCode/GitHub/Synth-Inversion-RP/c2_estimation/docs/collect_study_evidence.py`).
It reads saved tables and source excerpts, checks expected dimensions/non-test flags,
and prints documentation evidence. It does not rerender, retrain, refit or evaluate
test audio. These documents describe this snapshot, not automatic future results.
