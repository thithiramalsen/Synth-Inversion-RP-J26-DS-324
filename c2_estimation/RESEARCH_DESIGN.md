# C2: technology choices, justification and evaluation

## Scientific target

For a fixed in-domain Vital estimate, predict the probability that each delivered
control is within a predeclared tolerance of the known generating control.
The main question is whether actual forward-synthesizer measurements add useful
reliability information beyond inverse-model uncertainty alone. C2 never uses the
diagnostic renders to optimize or replace the delivered patch.

This is generating-parameter recovery, not proof that a patch is the only valid
perceptual match. Similar sounds can have different generating controls. This
non-uniqueness is established, for example, by
[Hayes et al. (2025)](https://arxiv.org/abs/2506.07199).

## Three distinct representations and roles

| Stage | Technology | Why it is used | What it does not establish |
|---|---|---|---|
| Inverse prediction | 64-band fixed-reference log-mel + small PyTorch CNN | Compact time/frequency input; existing pilot code; affordable repeat training | Best possible architecture or perceptually optimal embedding |
| Acoustic diagnostics | Three linear-frequency STFT magnitudes (512/1024/2048 FFT; quarter-window hops) | Inspect spectral structure at complementary time/frequency resolutions | A validated perceptual similarity probability |
| Reliability prediction (planned) | Per-control regularized logistic models of U, S, R | Small, inspectable models; controlled feature ablations | Causality, global identifiability, or automatic out-of-domain validity |

STFT and mel are deterministic signal representations, not pretrained semantic
embeddings. The inverse CNN learns its own representation during supervised training.
The three diagnostic resolutions form **one predefined diagnostic distance**, not
three independently cherry-picked scores.

The deterministic CNN currently minimizes parameter-space MSE in z, using known
generating controls. It does not minimize the diagnostic distance during training.
Consequently, audio reconstruction must be measured separately after prediction;
low parameter loss alone is not a guarantee of a perceptually close sound.

MR-STFT objectives have sound-generation precedent in
[Parallel WaveGAN](https://arxiv.org/abs/1910.11480), but that speech-generation
result does not validate our exact symmetric distance or our Vital reliability claim.
Local auditory-feature geometry has precedent in
[Han et al.](https://arxiv.org/abs/2311.14213); C2 tests a different post-hoc use.

## Why not CLAP initially?

[CLAP](https://arxiv.org/abs/2206.04769) learns a joint audio-language space from
paired audio/text. That makes it a plausible later comparison, including audio-only
embedding comparisons; using its audio encoder would not require text input.
However, the original objective does not establish sensitivity to small changes of
these 13 Vital knobs. Whether it preserves those differences needs measurement.

The initial choice of STFT is therefore a practical hypothesis, not evidence that
STFT is universally better than CLAP. Adding a large embedding now would add model,
resampling and invariance choices to an experiment already testing U/S/R.

If a learned embedding is added later: choose its frozen checkpoint and preprocessing
on development data, use the same clips/perturbations, inspect inactive-control and
known-change behavior, compare incremental calibration benefit on validation, and
freeze the representation before final test. Do not combine arbitrary distances
without fixing their scaling and weights. C4's learned human-aligned metric remains
a separate component and is not a dependency for the initial C2 hypothesis test.

## What is compared before and after perturbation?

1. `x` is the target. The CNN outputs one 13-control vector `z_hat`.
2. Map z through each allowed Vital interval and render the complete patch `x_hat`.
3. `R = D(x, x_hat)` measures target/reconstruction discrepancy.
4. Freeze the estimate. For control j, render `z_hat +/- .02 e_j` while holding
   every other control and synthesis condition fixed.
5. `S_j = D(x_minus, x_plus)/(actual_z_plus-actual_z_minus)` measures local activity.
6. On calibration/evaluation data only, known truth gives
   `y_j = 1[abs(z_hat_j-z_true_j) <= .05]`.
7. The future calibrator estimates `q_j = g_j(U_j, S_j, R)`.

Near boundaries use a forward/backward .02 step and the actual engine-readback
denominator, not clipping with a fictitious .04 denominator. At an interior point
the denominator is approximately .04. The tiny readback differences are recorded.

The example also reports `D(x,x_minus)` and `D(x,x_plus)` to help explain behavior.
These are **not substituted for S and not used to choose a better patch**. A plus
step can sound closer while the official output stays exactly the original estimate.

## Exact initial acoustic distance

All audio is 44.1 kHz mono, three seconds, fixed note/velocity, and passed once through
the canonical 10 Hz DC policy. There is no independent peak or loudness normalization.
At each resolution, normalize FFT magnitude by half the Hann-window sum. Then use:

```text
SC(A,B) = ||A-B||F / (0.5*(||A||F+||B||F) + 1e-12)
LM(A,B) = mean(abs(ln(max(A,1e-4)) - ln(max(B,1e-4))))
D(a,b)  = mean_over_3_resolutions(SC + LM)
```

The fixed magnitude floor is -80 dB relative to the amplitude reference. The floor
is deliberately separate from the denominator's numerical epsilon. This avoids
letting inaudible numerical tails dominate log differences. It is a development
choice requiring sensitivity checks, not a universally correct perceptual floor.
See the repository's PCM precision characterization for the motivating numerical issue.

## How we justify each choice

Use a four-part record: requirement -> reason/prior work -> alternatives -> measured
validation evidence. A citation motivates a choice; it does not replace experiment.

| Question | Evidence/check | Allowed conclusion |
|---|---|---|
| Do our labels map to the actual synth? | Recorded readbacks, range audit, known-patch re-render | Mapping/reconstruction implementation works for tested cases |
| Is the diagnostic contaminated by randomness? | Repeated identical renders; fixed preset/note/phase | Deterministic under the recorded runtime |
| Does an inactive control get small S? | Zero filter-envelope-depth fixture | Diagnostic passes a known inactivity check |
| Does the model learn controls? | Per-control MAE/RMSE/R2 against training-mean baseline | Better/worse parameter recovery on the evaluated partition |
| Does the patch reconstruct the target? | R and its component distances; baselines; examples | Relative numerical reconstruction quality under D |
| Do listeners perceive a good match? | A specifically designed listening evaluation | Only the perceptual claim that study actually tests |
| Does forward evidence help reliability? | Same frozen predictions; g0, raw-U ranking, g(U), g(U,S), g(U,R), g(U,S,R) | Incremental benefit, if supported by held-out comparisons |

There is currently **no validated universal R cutoff for 'close enough'**. R is
neither percent similarity nor confidence. A good R also does not imply every knob
is correct. High S does not prove unique identifiability; low S does not prove error.

## Remaining statistical experiment

Train probabilistic CNN members after reviewing the full deterministic baseline.
Use three during development, aiming for five if resources permit. Retain mean
within-member variance, between-member disagreement, and their sum. Use that sum
as the primary U. Deep ensembles are established methodology, not the novelty here:
[Lakshminarayanan et al.](https://arxiv.org/abs/1612.01474).

Fit per-control regularized logistic calibrators on the calibration subset. Any
transform/scaler is fitted there only. Do not silently class-balance fitting data
and then present the resulting scores as ordinary population probabilities. Include
a constant per-control calibration success-rate baseline and handle one-class
controls explicitly. Raw U is a ranking score, not a probability.

Use Brier score for probabilistic quality, reliability diagrams and declared-bin
calibration error for calibration behavior, AUROC/AUPRC for failure ranking, and
risk-coverage/AURC plus MAE at matched coverage for abstention. Declare failure as
`1-y` and score as `1-q`. Report class counts and undefined metrics honestly.
Bootstrap whole audio examples, keeping their 13 controls together. Primary
tolerance is .05 of the research interval, with .025/.10 sensitivity analysis.
Statistical comparisons use paired predictions and predeclared primary metrics.
All choices and display thresholds are frozen before diagnostic test evaluation.

## Small human study later

A small formative study can complement technical evaluation without becoming a
C1-style perceptual-label collection project. Run it after the inverse model **and
reliability calibration/interface** are fixed, not merely after CNN training.

Suggested scope, subject to supervisor/ethics approval and informed consent:

- Recruit relevant producers/synth users; record their experience and actual number.
- Compare the same predicted patches with and without reliability information.
- Counterbalance condition order or use matched tasks to reduce practice effects.
- Check whether participants understand q and Accept/Approximate/Abstain, identify
  controls they would retain/check, and explain why. Collect usefulness/confusion
  ratings and short qualitative comments; optionally log editing behavior.
- Avoid leading questions and presenting confidence as proof. Separate judging
  interface usefulness from judging target/reconstruction sound similarity.
- Treat a handful of participants as exploratory case-study evidence. Do not claim
  population-wide effectiveness, statistical power, or validated calibration from it.

Technical correctness probabilities are evaluated against known generating labels.
Human preference does not replace those labels. If the report claims that D itself
tracks perceived similarity, that requires a specifically designed perceptual study;
the small reliability-interface study cannot establish that automatically.
