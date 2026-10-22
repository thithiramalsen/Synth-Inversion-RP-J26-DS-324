"""Build an additive, self-contained edition of the existing C2 walkthrough.

Reads documentation only. Never imports model, renderer or dataset modules.
Original heading order, prose and executable command blocks are preserved.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "c2_estimation/DEMONSTRATION_WALKTHROUGH.md"
METRICS = ROOT / "c2_estimation/METRICS_REFERENCE.md"
OUTPUT = ROOT / "c2_estimation/DEMONSTRATION_WALKTHROUGH_EXPLAINED.md"


def metric_table(number):
    """Copy a measured/definition table verbatim, rather than retyping values."""
    text = METRICS.read_text(encoding="utf-8")
    section = re.search(rf"^## {number}\. [^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if section is None:
        raise ValueError(f"Missing metrics section {number}")
    table = re.search(r"^\|.*(?:\n\|.*)*", section[1], re.M)
    if table is None:
        raise ValueError(f"Missing table in metrics section {number}")
    return table[0]


NOTES = {
    "Showing and explaining the C2 results": """
## About this expanded edition

This is the same walkthrough with explanations inserted at each stop. All original
instructions, commands, tables and headings remain in their original order. The
added explanation headings are reading notes, not extra experiments to run. You
can follow either route without opening the study guide for the basic explanation.

The original opening above still points to the companion guides; those are now
optional references. File paths remain visible in plain text, including source
line numbers where supplied. Commands are copied unchanged; run them from the
repository root. The explanations describe the saved 15 October 2026 snapshot,
not a new training run or a newly evaluated test set.

Added measured tables are copied from
`D:/VSCode/GitHub/Synth-Inversion-RP/c2_estimation/METRICS_REFERENCE.md`.
The unchanged short walkthrough is
`D:/VSCode/GitHub/Synth-Inversion-RP/c2_estimation/DEMONSTRATION_WALKTHROUGH.md`.
""",
    "Before starting": """
#### Explanation: what the whole component is trying to do

Imagine hearing a machine with 13 knobs behind a curtain. First, the model guesses
the knob positions. Then C2 asks how much trust to place in each guess. A knob
that barely changes the sound may be difficult to recover even if the resulting
patch sounds close. Conversely, a poor guess may matter a great deal acoustically.

The research question is whether two measurements made with the synthesizer add
useful reliability information beyond the network's uncertainty. The main claim
is not that CNNs, ensembles or finite differences are new. It is the controlled
comparison of these reliability inputs for the same frozen parameter predictions.

Keep these questions separate:

| Question | What answers it? |
|---|---|
| Did I recover the original knob position? | Parameter MAE/RMSE/R2, or the within-tolerance label y |
| Does the predicted patch resemble the target under my audio distance? | Whole-clip residual R, plus listening for illustration |
| How likely is one knob prediction to be within tolerance? | Per-parameter calibrated probability q |

Different patches can make similar sounds. For example, with zero filter-envelope
depth, changing that envelope's timing has no effect through that route. Therefore
a small R does not prove all 13 original values were recovered. This experiment
measures recovery of the actual generating settings, not all possible equivalent patches.

The current data is the 131,072-clip, 13-control v4 corpus. The older eight-control
`pilot_v1` is historical; its 80/10/10 split and test results are not current results.
""",
    "Route A: use VS Code and its terminal": """
#### Explanation: what to do in VS Code

Keep this expanded Markdown preview on one side, a source file or saved figure
on the other, and PowerShell below. When a path ends in `:72`, open the file
without that suffix using `Ctrl+P`, then press `Ctrl+G` and enter `72`.

`Get-Content` reads text; `ConvertFrom-Json` turns JSON into inspectable objects;
`Import-Csv` reads a saved table; `Select-Object` chooses columns; `Format-Table`
and `Format-List` only change their display. None fits a model. Opening a `.png`
shows an existing plot. The `.pt` inspection below loads weights but does not train.
""",
    "1A. Configuration, sampling and rendering": """
##### Explanation: the synth is the sound maker, not the CNN

Vital is the synthesizer. Vita is the Python wrapper that controls its engine.
We do not recreate the synth in the browser. Shared generation code uses the
engine to make supervised pairs: an audio recording and the settings that made it.
Later, the same rendering recipe turns predicted settings back into audio.

The domain uses one oscillator with an embedded Basic Shapes wavetable, Bend
shaping, an Analog 12 dB filter, amplitude ADSR and ENV2 routed to cutoff. Other
oscillators, noise and effects stay off. Fixed conditions reduce unrelated causes
of sound changes; they also limit what the trained model is demonstrated to handle.

| Fixed condition | Value | Why hold it fixed? |
|---|---|---|
| Note and velocity | MIDI 60; velocity .8 | Avoid learning varying pitch and playing strength at the same time |
| Timing | Note held 1.5 s; full render 3 s | Include the attack, held segment and release |
| Audio | 44,100 Hz; canonical mono; 132,300 samples | Give every example the same shape and analysis rules |
| Storage | Raw FLOAT WAV masters | Preserve original samples; derive conditioning when loaded |

Here is what each of the five source stops above contributes:

1. `bend_sustain_config.py` selects the current 13 controls, inheriting the earlier
   configuration and making filter-envelope sustain variable again.
2. `restricted_config.py` supplies fixed note/timing/rate and the restricted ranges.
3. `create_sobol_samples` draws the reproducible parameter combinations. Think of
   spreading dots over a 13-dimensional box. The generation seed is 20260803, and
   131,072 is 2^17. Scrambled Sobol improves coverage in these chosen coordinates;
   it does not guarantee equal perceived timbre coverage or audible independence.
4. `apply_sampled_parameters` maps a unit sample into its allowed interval, sets
   the control, then reads it back. The readback, not the requested value or a
   rounded display string, is the canonical label.
5. `render_one` makes a fresh synth, loads the frozen preset, applies the fixed
   and sampled controls, renders and records the result. Fresh state and fixed
   phase reduce carry-over between samples. Parallel workers still commit in index order.

The 13 values and allowed engine-normalized ranges are:

| Parameter | Allowed n | What it changes |
|---|---|---|
| wave_frame | 0-1 | Position in the fixed wavetable |
| bend_amount | .25-.75 | Waveform bending; .5 is neutral |
| filter_cutoff | .30-.85 | Main filter frequency control |
| filter_resonance | 0-.80 | Emphasis near cutoff |
| filter_drive | 0-.75 | Nonlinear filter drive |
| amp_attack | .05-.35 | How quickly volume rises |
| amp_decay | .15-.40 | Movement toward held volume |
| amp_sustain | .20-1 | Held volume level |
| amp_release | .10-.45 | Volume fall after note-off |
| filter_env_amount | .50-.5625 | ENV2 cutoff depth; n=.5 means zero depth |
| filter_env_attack | .05-.35 | Filter-envelope rise |
| filter_env_decay | .15-.40 | Filter-envelope fall toward sustain |
| filter_env_sustain | 0-1 | Held filter-envelope fraction |

These are normalized control positions, not directly seconds, Hz or percentages
of audible change. Thirteen is the selected manageable research domain, not a
proved optimal count. Ranges reflect engineering characterization and researcher
review, not a completed human perceptual validation study.

Frozen preset path:
`D:/VSCode/GitHub/Synth-Inversion-RP/generation/presets/base_restricted_bend_sustain_v4.vital`.
Unit mapping explanation:
`D:/VSCode/GitHub/Synth-Inversion-RP/generation/PARAMETER_UNITS.md`.
""",
    "1B. Dataset integrity checks": """
##### Explanation: checking the ingredients before judging the model

The audit checks that the corpus was saved consistently. Unique paths guard
against accidentally reusing a file; hashes act like fingerprints of exact
waveform samples; agreement between CSV, Parquet and checkpoints guards against
incomplete or inconsistent bookkeeping. The recipe records synthesis settings
and source/runtime identities so a later render can be checked against them.

Audio QA checks finite samples, duration/rate and levels. Silence is flagged below
-60 RMS dBFS, clipping at peak >=1, and DC warnings at abs(mean)>=.005 or
abs(mean)/RMS>=.20. Zero conditioned flags means these rules passed after the fixed
conditioning. It does not mean all raw audio was DC-free or all sounds were perceptually good.

Reading `verification.json` shows a completed check. It does not run that check
again. Whole-corpus storage/format checks may include files later reserved for
test; measuring a trained model's performance on those files is a different action.
""",
    "1C. Inspect one generated record": """
##### Explanation: how audio and labels stay connected

`sample_id` is the joining key. `raw_audio_path` identifies the actual source WAV;
an imported prefix can remain in its original directory, so do not assume every
clip is physically in one folder. The manifest is the authoritative map.

| Field ending | Meaning | Use |
|---|---|---|
| sample_01 | Proposed Sobol coordinate inside the chosen interval | Reproduce the sampling design |
| normalized | Actual engine-normalized readback | Canonical target label |
| raw | Native engine control value | Inspect units and engine behavior |
| display | Rounded human-readable control text | Explain, not train |

For interval [lower, upper], the requested engine setting is
`lower + sample_01*(upper-lower)`. Floating-point readback can differ slightly.
Saving both proposal and readback avoids pretending a rounded requested value
was exactly what the engine used. No human has to guess these labels from sound.
""",
    "Stop 2A: Audio conditioning with the shared utility": """
#### Explanation: centering the waveform without erasing level information

DC offset is a waveform shifted away from zero. The shared loader reads the raw
master and applies the same causal second-order Butterworth 10 Hz high-pass once.
It returns canonical float32 samples at 44.1 kHz. With verification enabled it
checks raw and processed sample hashes. Tiny float32 subnormal tails are made
consistent for reproducible hashes; this is not a denoising algorithm.

There is no per-clip peak or loudness normalization in this C2 path. Making every
clip equally loud could remove information about amplitude-envelope or drive
settings. Feature standardization at Stop 3 is a separate operation.

The key code sequence in `load_audio` is `read_raw` -> `dc_filter` ->
`canonical_float32` -> optional hash checks. It does not assign splits, make new
training examples or call the neural network. A shared utility can live under
`generation/` without making its caller's training/splitting a generation task.

Policy path:
`D:/VSCode/GitHub/Synth-Inversion-RP/generation/audio_policies/dc_highpass_10hz_v1.json`.
""",
    "Stop 2B: C2 dataset splitting": """
#### Explanation: separate books for learning and the final exam

Training teaches the CNN the knob positions. Calibration teaches a different,
small model how to judge its errors. Inverse-validation chooses CNN checkpoints;
reliability-validation chooses calibrator regularization and supports development
comparisons. The final test is the sealed exam, not a tuning set.

The C2 seed is 20261013, different from generation's 20260803. In `assignments`,
the already-inspected 1,024 v4-prefix IDs stay in training; a seeded permutation
assigns the rest. Validation is split into two disjoint roles. A separate seed+1
ordering chooses diagnostic ranks before looking at prediction quality. Reusing
that saved ordering prevents picking only convenient sounds later.

`protocol.json` records the choices. Displaying it does not perform the split.
`prepare` saves the assignments and transformed labels; later stages check hashes
before reusing them. It belongs to C2 at
`D:/VSCode/GitHub/Synth-Inversion-RP/c2_estimation/v4/data.py:132`.
""",
    "Recap of audio conditioning and C2 splitting": """
##### Explanation: remember the pool sizes versus the measured subsets

| Role | Available clips | Actual development use |
|---|---|---|
| Train | 98,304 | CNN fitting and train-only normalization; 128 smoke diagnostics |
| Calibration | 16,384 | First 2,048 predetermined diagnostic ranks fit q |
| Inverse-validation | 4,096 | Select CNN checkpoints and report parameter errors |
| Reliability-validation | 4,096 | First 512 predetermined ranks select C and compare reliability methods |
| Reserved test | 8,192 | No model/reliability evaluation; 1,024 diagnostic IDs assigned for later |

The smaller subsets bound expensive synth rendering; they are not the whole pools.
The old pilot's 80/10/10 split is not this protocol. Disjoint IDs protect roles,
but do not prove every sound is acoustically distinct or that this tests a new
synthesizer family. Perturbations stay with their source partition and never
become extra inverse-model training data in this experiment.
""",
    "Stop 3: C2 feature preprocessing and normalization": """
#### Explanation: turning sound into a small time-frequency map

A waveform is one long list of values. A spectrogram shows which frequencies are
present as time moves forward. The mel filterbank groups them into 64 bands; the
logarithm compresses the range of power values. The image makes this visible,
but the model receives the numeric array, not the PNG, title or color palette.

Read `extract_log_mel` in this order: reflect-pad the waveform; take overlapping
2,048-sample frames every 512 samples; multiply by the Hann window; apply real FFT;
scale magnitudes; square them into power; multiply by the triangular mel filterbank;
take 10*log10; clip to the fixed -80 to 0 dB range; transpose to mel-by-time float32.
The fixed reference is not each clip's own maximum.

| Feature setting | Value |
|---|---|
| Window / hop | 2,048 / 512 samples, about 46.44 / 11.61 ms |
| Frequency range | 20-20,000 Hz |
| Per-clip array | 64 bands x 259 time frames |
| CNN input | 1 x 64 x 259; a batch adds its first dimension |
| Cache shard | Up to 512 clips; memory-mapped to bound RAM use |

`training_statistics` calculates one mean and standard deviation over training
spectrogram values only. The saved values are -73.5395297540483 and
12.9035521819895. Later inputs use `(log_mel-training_mean)/training_std`, without
fitting new statistics on validation or test. This keeps unseen data out of fitting.

The input is log-mel. The forward audio checks at Stop 7A use multi-resolution
linear-frequency STFT magnitudes instead. Neither path currently uses CLAP or
MFCC embeddings. A compact, inspectable representation is justified as a controlled
baseline, not as proof of the best embedding; a stronger representation would need
a matched experiment rather than an assumption that it must improve this task.

Feature configuration path:
`D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/features_full_v1/cache.json`.
The full cache has 98,304 train and 4,096 inverse-validation clips; it is not a
cache of evaluated test examples.
""",
    "4A. Training code and learning curves": """
##### Explanation: the CNN learns patterns, then adjusts its own weights

A convolution is a small pattern detector sliding across time and frequency.
ReLU lets the network represent nonlinear relations. Max pooling reduces the
map size; average pooling and dense layers combine the learned patterns into
13 continuous outputs. This is regression, not 13-class classification.

The reused `ParameterCNN` receives 13 output bounds for v4. Importing its class
from `pipeline.py` does not make this an eight-control pilot run.

```text
1 x 64 x 259
 -> Conv/ReLU/MaxPool: 8 x 32 x 129
 -> Conv/ReLU/MaxPool: 16 x 16 x 64
 -> Conv/ReLU/MaxPool: 32 x 8 x 32
 -> average pool: 32 x 2 x 4
 -> flatten 256 -> dense 64 -> dense 13 -> sigmoid
```

The sigmoid constrains predictions to the research coordinate z. Actual engine
positions n are converted using `z=(n-lower)/(upper-lower)` so each restricted
interval spans 0-1 in the learning problem. On reconstruction,
`n=lower+z*(upper-lower)`. For cutoff, z=.4 maps to n=.30+.4*.55=.52;
this does not mean .52 Hz or 52% perceived brightness.

These are the central operations in the existing `baseline.train` loop:

```python
optimizer.zero_grad(set_to_none=True)
prediction = model(x.to(device))
loss = torch.mean(torch.square(prediction - y.to(device)))
loss.backward()
optimizer.step()
```

`zero_grad` clears earlier gradients; `model` predicts; MSE measures disagreement
with true z; `backward` calculates how weights affect that error; Adam's `step`
updates the weights. Vital is not in this gradient path. The training objective
is parameter error, not R and not a perceptual similarity loss.

The single CNN has 23,181 trainable weights/biases. Full training used batch 128,
Adam learning rate .001, weight decay .0001, up to 60 epochs and patience 12.
An epoch is one pass through the training set; patience counts consecutive epochs
without validation improvement. All 60 epochs ran; the best checkpoint is epoch 53.
Training and validation curves show that selection history, not a new test result.

CUDA uses a mathematically equivalent fixed 4x8 average pool to support deterministic
backward execution for this input size. Fixed seeds, deterministic operations,
epoch-addressable shuffle, hashes and reload checks support reproducibility in
the recorded environment, not a promise of identical training on every machine.

Learning curve path:
`D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/baseline_full_v1/learning_curves.png`.
""",
    "4B. Parameter-recovery results on inverse validation": """
##### Explanation: reading the recovery numbers

For each parameter, let error=predicted_z-actual_z. MAE is mean(abs(error)); RMSE
is sqrt(mean(error^2)), so it penalizes large mistakes more. R2 is
`1-sum(error^2)/sum((actual_z-mean(actual_z))^2)`: 1 is perfect, 0 matches the
constant mean fitted to those evaluated targets, and negative is possible.
That R2 reference is distinct from the separately reported training-mean predictor.

A z MAE of .05 means 5% of that parameter's restricted interval on average, not
5% Hz or a guaranteed perceptual difference. Macro MAE gives each of the 13 controls
equal weight. Macro RMSE is not the square root of an overall MSE; name the aggregation.

The saved single-model z MSE is .031867 versus .083213 for the training-mean
baseline. The table below reports the same 4,096 inverse-validation clips for the
single CNN and ensemble. The ensemble is explained at the next stop; this is not
a comparison on the 512 reliability-validation examples.

{recovery_table}

Amplitude envelope and cutoff are relatively strong; bend and several filter
envelope controls are harder. Possible causes include weak/conditional audio
effects and model error; these scores alone do not prove a particular cause.
The ensemble's macro MAE .127991 is slightly worse than the single model's .126112.
Because their losses differ, this is not a causal test of averaging alone.
""",
    "4C. Saved checkpoint metadata": """
##### Explanation: a trained model is its learned weights plus its recipe

The Python class defines the shape of the machine; `best_model.pt` contains its
learned numbers. Loading it without the matching parameter order, feature settings
and training normalization would not reproduce the same predictor. The metadata
check shows the selected epoch and 13 outputs without starting inference on test.

`best_model.pt` is the selected predictor. `last_model.pt` also preserves the last
training state needed for an exact configured resume. Neither is a Vital patch.
A `.vital` patch stores synth settings; a `.wav` stores sound; a `.npy` stores
numeric features; CSV/Parquet store tables; JSON stores configuration or results.

Model path:
`D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/baseline_full_v1/best_model.pt`.
Run recipe path:
`D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/baseline_full_v1/run_config.json`.
""",
    "Stop 5: Ensemble training and uncertainty U": """
#### Explanation: three guesses, each with a predicted spread

Each Gaussian CNN predicts a mean setting and positive variance for every knob.
The mean head uses sigmoid; the variance head uses softplus plus a 1e-4 floor.
The Gaussian model has 24,026 trainable parameters and is trained with Gaussian
negative log-likelihood, not the single model's MSE alone:

```text
NLL = .5 * mean(log(variance) + (mean-target)^2/variance)
```

Large errors with tiny variance cost a lot, but arbitrarily huge variance also
has a cost. The omitted constant does not affect gradients. NLL can be negative
for small continuous variances; that is not automatically a bug. The Gaussian
objective is a modelling assumption, not proof of a correct posterior.

Independent seeds are 20261013, 20262022 and 20263031; each best checkpoint is
chosen using its own inverse-validation NLL. Best epochs are 57, 59 and 58.
The combining code computes:

```text
predicted_z = average(member_mean)
within = average(member_variance)
between = average((member_mean-predicted_z)^2)
U = within + between
```

Imagine three people estimating a knob. Each gives a range, and their central
guesses may disagree. Both pieces contribute to U. The between term uses population
averaging, not division by members-1. These are operational uncertainty components,
not proved pure aleatoric and epistemic decompositions. Agreement can still be wrong.

U is measured in z squared. U=.02 does not mean 98% confidence. The later calibration
model learns how these measurements relate to the declared correctness event.
Three members are a practical bounded choice, not a demonstrated optimum. Use all
three best checkpoints and the saved preprocessing settings for this ensemble.
""",
    "6A. Predicted settings and diagnostics": """
##### Explanation: what is already frozen in this example

Before forward diagnostics, `predict_subsets.predict` runs the trained ensemble
with fixed feature normalization, checks identities and repeated inference, then
saves its means, variances and IDs. Its development selector permits smoke,
calibration and reliability-validation, not test.

Prediction source path:
`D:/VSCode/GitHub/Synth-Inversion-RP/c2_estimation/v4/predict_subsets.py:42`.
Viewer data path:
`D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/viewer_v1/data.json`.

The displayed example is first in the predefined reliability-validation diagnostic
ordering. It was not picked for being accurate or sounding good. `actual_z` is
known only because this is synthetic research data. `predicted_z` is the frozen
model output; `error_z` and correctness labels judge it; U/S/R are measurements;
q estimates within-tolerance recovery. Error/actual_z never become calibrator inputs.

`predictions_unchanged` verifies that diagnostics did not replace the original
guess. `roundtrip_exact` says rendering the true generating settings reproduced
the canonical target samples before playback encoding. It does not say the
predicted settings were correct. One selected example cannot establish population performance.
""",
    "6B. Listen to target and reconstruction": """
##### Explanation: why two sounds can be close while some settings are wrong

The target is the known generated clip. The reconstruction is Vital rendered at
the ensemble's predicted settings, using the fixed preset/note/phase recipe.
The CNN predicts controls; it does not directly generate waveform samples.

The players replay stored WAVs; they do not perform a new prediction or call a
live synth. Playback copies use PCM16 for compatibility. Numerical diagnostics
were computed on canonical float32 audio before quantization, without independent
gain matching. Listen at a comfortable level; one person's impression is an
illustration, not the later human-validation study.
""",
    "6C. Inspect one parameter in detail": """
##### Explanation: the cutoff arithmetic, one quantity at a time

| Quantity | This saved example | Meaning |
|---|---|---|
| Actual / predicted z | .369066 / .371036 | True setting and model guess in the restricted coordinate |
| Absolute error | .001970 | Inside the primary tolerance .05, so y=1 |
| Engine-normalized prediction | .504070 | .30 + .371036*(.85-.30) |
| Lower / higher z | About .351036 / .391036 | One changed knob; all other predictions fixed |
| Actual endpoint span | About .04 | Read back from the engine, not assumed |
| Lower-versus-higher distance | About .070776 | Difference between two diagnostic renders |
| S | 1.769388 | About .070776/.04; local acoustic activity |
| U | .001301 | Predicted ensemble variance, in z squared |
| Full q | .893669 | Estimated probability of recovery within .05 |
| Whole-patch R | .098242 | Target-versus-predicted render mismatch |

q is not `1-error`, and it is not `1-R`. For a new unknown clip the true error is
unavailable. The learned calibrator uses U/S/R to estimate the event probability.
This example's drive error is .230290 with full q about .131774: several wrong
knobs coexist with a fairly small global R. Filter-envelope amount succeeds with
low q; one low-q success is not by itself evidence that calibration is wrong.
""",
    "Stop 7A: Forward diagnostics with R and S": """
#### Explanation: ask the synth two different questions

First, render the frozen predicted patch and compare it with the target: that is
R. Next, change one predicted knob slightly lower and higher, render both, and
compare those two sounds: that gives S after dividing by actual knob separation.
The target is used for R, not for deciding which perturbation to keep.

The four functions above map to the work as follows:

1. `Renderer.render` converts z to engine-normalized values, creates a fresh synth,
   loads the frozen preset, sets controls and checks readbacks; it renders, checks
   stereo agreement and applies the same canonical conditioning.
2. `feature_distance` compares linear-frequency STFT magnitudes at FFT sizes
   512/1024/2048 with hops 128/256/512. Short windows resolve time more finely;
   longer windows resolve frequency more finely. This is not the CNN's log-mel image.
3. `perturbation_pair` changes only parameter j by delta=.02 in z. In the interior
   it uses z-.02 and z+.02. Near 0 or 1 it uses a one-sided pair with the original
   prediction at one endpoint. It never clips while pretending the span is unchanged.
4. `measure` checks the other 12 actual controls remain unchanged, uses the actual
   readback span, reuses the base at boundaries and verifies the prediction stayed frozen.

The diagnostic equations are:

```text
SC = norm(A-B) / (.5*(norm(A)+norm(B)) + 1e-12)
LM = mean(abs(log(max(A,1e-4)) - log(max(B,1e-4))))
D = average_over_three_resolutions(SC + LM)
R = D(target_audio, predicted_audio)
S_j = D(lower_audio_j, higher_audio_j) / (actual_z_plus_j-actual_z_minus_j)
```

SC measures spectral pattern disagreement relative to magnitude; LM compares
log magnitudes with a fixed floor. Both are combined by the predefined distance.
R is one clip-level score shared by all parameter calibrators. It is not a
validated perceptual scale: R=.1 does not mean 90% similarity.

S is an unsigned local activity measure. Low S means these two small moves have
little effect under this metric; high S means a stronger effect. S is not a signed
derivative of target loss, a confidence percentage, a perceptual threshold or a
proof that a knob is uniquely recoverable. Other knobs can compensate for it.

We never replace the original patch with a better perturbation. Otherwise the
experiment would mix better prediction with better reliability estimation.

Why not perturb every training clip? An interior patch needs up to 27 renders:
one base plus two per control. For 131,072 clips that is up to 3,538,944 renders
before audits. The 2,048 calibration plus 512 validation cases need up to 69,120,
before boundary reuse and audits. Derived diagnostic audio is normally streamed
and discarded; scores, readbacks and hashes are saved. Demo audio is retained selectively.
""",
    "Stop 7B: Reliability calibration and q": """
#### Explanation: teach a small judge what a correct estimate looks like

On research data we know true z. For each knob define
`y=1 if abs(predicted_z-actual_z)<=.05 else 0`. The tolerance is 5% of that
restricted parameter interval, not a sound-quality threshold. The same predictions
are also examined at .025 and .10, but .05 remains the primary event.

For each parameter, a regularized logistic regression learns q from the allowed
measurements. It is a small statistical model, not another large CNN:

```text
Transform U with log(max(U,1e-12)); S and R with log(1+value)
Standardize features using calibration-only mean and standard deviation
score = intercept + weight_U*scaled_U + weight_S*scaled_S + weight_R*scaled_R
q = sigmoid(score) = 1/(1+exp(-score))
```

Terms absent from an ablation are left out. Log transforms compress skewed
magnitudes; scaling makes coefficient fitting better behaved. Fitting uses 2,048
calibration cases with SciPy L-BFGS-B and mean binomial NLL plus
`norm(weights)^2/(2*C*n)`, with an unpenalized intercept. No class rebalancing is
used because the probabilities should reflect this sampled event prevalence.
A single-class calibration target returns its constant observed probability.

For each knob and feature variant, C is selected from .01/.1/1/10 by lowest Brier
on the separate 512 reliability-validation cases; smaller C breaks ties. Smaller
C means stronger regularization. Consequently the reported validation comparisons
are development estimates, not an unbiased final test.

q=.8 means that similarly scored in-domain predictions should succeed around 80%
of the time if calibration holds. It is not a promise about that one prediction.
There is no validated Accept/Approximate/Abstain threshold yet.

Fitted model path:
`D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/development_uncertainty_v1/calibration_tau_0.05/calibrators.json`.
This saves weights, intercepts, C, scalers and feature choices so inference reuses
them rather than fitting a new rule for each uploaded sound.
""",
    "Recap of forward diagnostics and reliability calibration": """
##### Explanation: the boundary that makes this a fair experiment

The inverse model is already trained. Its predicted settings and U are frozen.
R and S inspect those predictions with the synth. A separate model estimates q;
it does not edit the settings. True generating values are used to teach/evaluate
the correctness label, never as an input needed to calculate q on an unknown clip.

That separation is the central methodological control: all reliability methods
judge the same guesses. Improvement in q scores therefore cannot be explained
by quietly giving the full method a better reconstructed patch.
""",
    "8A. Compare reliability methods and statistical intervals": """
##### Explanation: what is compared, and what each score means

An ablation removes an input while keeping the predictions, IDs and tolerance
fixed. g0 is the per-knob calibration success rate. Raw U ranks likely failures
without a probability calibration; it has no probability Brier/ECE. g(U) is the
fair calibrated uncertainty-only baseline. g(U,S) and g(U,R) isolate additions;
g(U,S,R) uses all three. Comparing full against U+R specifically asks what S adds
once reconstruction mismatch is already available.

{probability_definitions}

For a concrete Brier example, q=.8 with y=1 costs (.8-1)^2=.04; the same q with
y=0 costs .64. An overconfident mistake costs much more. Brier measures overall
probability quality, not calibration alone. ECE compares mean q with observed
success in ten equal-count bins; it is bin-dependent, not proof of perfect calibration.
Failure AUROC and AP use 1-q as the score (raw U for its baseline). Higher is
better; AP depends strongly on the failure prevalence, so compare within a knob.

Coverage means the fraction retained after ranking by reliability. Risk is the
failure fraction among retained estimates; MAE-at-coverage measures their numeric
error. AURC averages prefix risks here, so lower is better. At 50% of 512 cases,
each parameter retains exactly 256 predictions. Parameters may retain different
audio IDs; this is not a defined whole-patch acceptance rule.

The saved macro results, with equal weight per parameter, are:

{macro_table}

The full method improves Brier/ECE slightly; g(U,S) has the lowest macro AURC.
No method needs to win every metric. The paired Brier differences are:

{interval_table}

The audit resamples whole audio clips with replacement 2,000 times, comparing
methods on the same resampled IDs and keeping their 13 controls together. This
preserves within-clip dependence. The 2.5th/97.5th percentiles give the interval.
These intervals condition on fitted models and development selection; they do
not include retraining uncertainty. Per-knob follow-ups are exploratory and not
adjusted for multiple comparisons. Excluding wave frame is also exploratory,
not a replacement for the declared 13-control comparison.

The full model's per-parameter reliability results are retained here too:

{full_parameter_table}

Failure counts matter. Amplitude release has only two failures out of 512 here,
so its ranking results are fragile. High AP for a mostly failing knob does not
by itself imply strong discrimination. Single-class AUROC/AP are undefined.

At the same 50% coverage, the saved comparison is:

{coverage_table}

This prevents a method from gaining credit simply by keeping fewer predictions.
Some controls worsen with full diagnostics. Do not replace these mixed results
with a claim of uniform improvement.
""",
    "8B. Perturbation step-size validation": """
##### Explanation: check whether the measuring ruler changes the conclusion

A very small move can be affected by numerical behavior; a larger move may no
longer describe the same local neighborhood. The study checks .01/.02/.05 on the
first 256 preassigned calibration ranks, with the same fixed predictions. It
reuses 256 existing .02 cases and adds 512 cases for .01 and .05, plus eight audits.
It does not select examples by which step gives the preferred result.

{stability_table}

Spearman rho compares ordering, not magnitude. The last column is the 95th
percentile of absolute differences in log(1+S); it is not a percentage or dB.
Wave frame and bend are more scale-dependent. Amplitude attack has very high rank
agreement but noticeably changing magnitude. Tiny boundary groups and constant
scores need caution. The check did not refit calibrators or replace default .02.

Magnitude figure path:
`D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/step_stability_v1/step_size_magnitude_agreement.png`.
Full table path:
`D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/step_stability_v1/step_size_agreement.csv`.
""",
    "8C. Implementation verification": """
##### Explanation: correct code is necessary, but is not the research result

The saved CPU suite discovered 43 tests: 41 passed and two CUDA-only checks were
skipped. The GPU-only checks passed in an earlier dedicated record. Report skips
honestly; a CPU run cannot establish that it ran CUDA checks.

Split protection, restart reproducibility, variance arithmetic, calibration
metrics, perturbation isolation and audio exports are implementation checks.
Repeated-render equality checks deterministic sound generation. Known-parameter
roundtrip checks that the recorded true settings reproduce their target. Frozen
prediction checks guard against diagnostics modifying the estimate. These do
not prove perceptual similarity, usefulness to people or unique parameter recovery.

GPU record path:
`D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/verification_gpu_v1/verification.json`.
Opening records in this walkthrough does not rerun those tests or evaluate test data.
""",
    "8D. Figures and interpretation": """
##### Explanation: how to read the saved research evidence

The Brier-difference figure shows which controls account for gains or regressions,
not just an appealing average. The matched-coverage figure compares what remains
when methods retain the same number. The step figure checks a measurement choice,
not prediction accuracy. Read the caption, axes, population and direction before
saying a bar or curve is better.

EDA means checking distributions and assumptions before treating a model score
as evidence. Useful saved figures include:

| Check | Why show it? | Full path |
|---|---|---|
| Parameter coverage and split balance | Inspect sampled ranges and non-test group comparability | `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/evidence_baseline_full_v1/target_distributions_and_split_balance.png` |
| Parameter correlation | Check sampling relationships, not acoustic independence | `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/evidence_baseline_full_v1/training_parameter_correlation.png` |
| Audio quality | Inspect levels, DC and fixed training audio conditions | `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/evidence_baseline_full_v1/training_audio_quality.png` |
| Error by parameter value | Find where recovery breaks down | `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/evidence_baseline_full_v1/validation_error_by_actual_value.png` |
| Reliability diagram | Compare q with observed success frequency | `D:/VSCode/GitHub/Synth-Inversion-RP/data/processed/c2_v4/development_uncertainty_v1/calibration_tau_0.05/reliability_diagrams.png` |

The baseline evidence pack has ten figures and the ensemble pack eleven, with
underlying CSVs/provenance. A low sampled-parameter correlation does not prove
controls have independent acoustic effects. Plots using true envelope depth are
descriptive research analysis, not inputs available for a new unknown recording.

The defensible current conclusion is a small development improvement over
calibrated U, concentrated partly in wave frame. The extra contribution of S
over U+R is not established by its interval. Keep that limitation visible when
explaining why the research question still needs locked-method test evaluation.
""",
    "B1. Open the local demo": """
#### Explanation: the page is a saved-results viewer

The local server serves HTML, JSON, figures and audio that already exist. Starting
it does not start training or a GPU job. The six examples are ordered by the
preassigned validation ranks, not by how convincing they sound. q and perturbation
audio were computed earlier; browser selection only changes what is displayed.

No full synthesizer has to be recreated in JavaScript for this viewer. A later
live service would validate an isolated clip, apply the frozen preprocessing,
run the ensemble, render with Vita/Vital, compute R/S, apply the saved calibrators
and offer a compatible patch export. Upload/new-clip inference and patch-download
interface remain pending. Today's page is not evidence that those are implemented.
""",
    "B2. Demonstrate audio, parameters and diagnostics": """
#### Explanation: what to say while moving through the audio screen

The original/predicted players answer what the two saved sounds are like. The
fixed-scale spectrogram comparison shows where time-frequency energy differs;
it is not a human similarity score. True settings are a research-only reference;
an arbitrary unknown uploaded clip would not reveal its original controls.

Selecting cutoff shows the same base prediction and two saved perturbations:
only that knob moves. The inspector does not retrain or improve the patch.
For Example 1, cutoff error is .001970, S is 1.769388, U is .001301 and full q
is .893669; global R is .098242. Those numbers have different units and meanings,
as worked through at Stop 6C. Drive is a useful contrasting failed parameter.

| Display | Plain-language explanation | Do not call it |
|---|---|---|
| Predicted setting | The knob position the model guessed | The guaranteed original setting |
| U | The ensemble's variance estimate | A correctness percentage |
| S | How much this knob locally changes the rendered sound | Proof the knob is uniquely identifiable |
| R | Whole-patch mismatch under the chosen audio distance | A similarity percentage |
| q | Estimated chance of being within the chosen parameter tolerance | A promise, or perceptual quality score |

Do not apply an unsupported good/bad threshold to R or S. The viewer displays
continuous q; Accept/Approximate/Abstain states have not been validated.
""",
    "B3. Compare reliability models and examples": """
#### Explanation: change the judge, not the answer it is judging

Switching from U only to U+R or U+S+R changes the probability model. It does not
change the ensemble's predicted settings, reconstructed audio or known outcome.
That is the visual version of the frozen-prediction ablation at Stop 8A.

The full model can produce a higher q, a lower q, or a worse probability for an
individual case. Evaluate it across the predefined population, not by whether
one example's number becomes more reassuring. Use other examples to show failure
cases and avoid claiming the six saved sounds represent all future recordings.
""",
    "B4. Show validation results and method": """
#### Explanation: connect the demonstration to the aggregate experiment

The validation screen summarizes the 512 reliability-validation cases, not the
4,096 inverse-validation recovery set. Brier/ECE judge probabilities; AUROC/AP
judge failure ranking; coverage plots judge errors among retained estimates.
Stop 8A above contains their definitions and measured tables in this same file.

The key numbers to say are full Brier .115385 versus U-only .116267, a difference
of -.000882. Full versus U+R is -.000187 with interval [-.000757,.000400], including
zero. Thus a broad claim that sensitivity is already proven useful beyond
reconstruction mismatch would overstate the evidence. These are development
results because reliability-validation also selected C. The test remains untouched.

The Method screen explains this implemented pipeline and restricted domain, not
general performance on arbitrary synths, notes, effects, music or recorded instruments.
""",
    "A short version if time is limited": """
#### Explanation: a compact spoken version of that same sequence

> I generated paired sounds and known settings within a fixed 13-control Vital
> domain. C2 keeps separate data for model fitting, reliability fitting, development
> selection and final testing. It converts audio to log-mel arrays and trains a
> CNN, then three probabilistic CNNs to provide predictions and variance. I freeze
> their predictions, render the patch to measure mismatch R, and perturb one knob
> at a time to measure local activity S. A per-knob logistic model estimates the
> probability of recovering the true setting within .05 of the restricted interval.
> I compare the same predictions under uncertainty-only and added-diagnostic
> variants. The development Brier gain is small; the extra benefit of S over U+R
> is uncertain. The saved viewer demonstrates real outputs, while live upload,
> final test evaluation and a small human study remain to be completed.

Use the full stop-by-stop notes above to expand whichever part needs explanation.
The separate reference remains available, but the main recovery, reliability,
coverage and perturbation-step numbers are now included here.
""",
    "Useful answers when asked to go deeper": """
#### Explanation: useful distinctions behind those answers

**Is this identifiability or just model difficulty?** S measures local acoustic
activity around a prediction. A low score can reflect an inactive route, but
cannot by itself establish global non-identifiability. Estimator capacity and
training error also affect recovery. The experiment tests whether measurements
help judge correctness rather than claiming a complete theoretical solution.

**Why logistic regression?** It is small, regularized and inspectable, making it
easier to compare a controlled set of U/S/R features. SciPy fits its coefficients;
PyTorch fits the CNNs; NumPy handles arrays; SciPy also supports signal processing;
CSV/Parquet/JSON preserve results and configuration; Matplotlib produces evidence
plots; HTML/CSS/JavaScript present saved outputs. Bigger models or other embeddings
are possible future comparisons, not automatically better choices.

**What would the final input/output be?** An isolated supported audio clip goes
in; predicted controls, a compatible patch/reconstruction and per-control
reliability information come out. That intended live interface is not the current
static viewer. Calibration evidence is restricted to the recipe and sampled domain.

**What should the small human study establish?** After the method/model is fixed,
use a predefined task and consent process to ask whether a small group understands
the display and finds it useful. Listening judgments can complement the measured
audio distance. Keep these questions separate from numerical recovery and
calibration, avoid treating a convenience sample as population proof, and do not
claim human-validation results before collecting them. Define the study before
seeing its answers; do not use final test outcomes to repeatedly redesign the method.

**What comes next scientifically?** Freeze the final method, comparisons and event
definition; perform the protected test evaluation once; then report its results
alongside the current development evidence and the later small human study.
No command in this guide initiates that evaluation.
""",
}


def build():
    original = SOURCE.read_text(encoding="utf-8")
    starts, fenced = [], False
    offset = 0
    for line in original.splitlines(keepends=True):
        if line.startswith("```"):
            fenced = not fenced
        if not fenced:
            heading = re.match(r"^#{1,4} (.+?)\s*$", line)
            if heading:
                starts.append((offset, heading[1]))
        offset += len(line)
    if fenced:
        raise ValueError("Unclosed source fence")
    keys = {title for _, title in starts}
    if set(NOTES) - keys:
        raise ValueError(f"Unknown insertion headings: {set(NOTES)-keys}")
    tables = {"recovery_table": metric_table(3), "probability_definitions": metric_table(5),
              "macro_table": metric_table(6), "interval_table": metric_table(12),
              "full_parameter_table": metric_table(8), "coverage_table": metric_table(10),
              "stability_table": metric_table(14)}
    original_blocks, output_blocks, inserted = [], [], []
    for i, (start, title) in enumerate(starts):
        end = starts[i+1][0] if i+1 < len(starts) else len(original)
        block = original[start:end]
        original_blocks.append(block)
        output_blocks.append(block)
        if title in NOTES:
            note = NOTES[title].strip()
            for token, value in tables.items():
                note = note.replace("{" + token + "}", value)
            output_blocks.append("\n" + note + "\n\n")
            inserted.append(title)
    if "".join(original_blocks) != original:
        raise ValueError("Source partition failed: original text would be lost")
    expanded = "".join(output_blocks)
    position = 0
    for block in original_blocks:
        found = expanded.find(block, position)
        if found < 0:
            raise ValueError("Original content/order was changed")
        position = found + len(block)
    original_commands = re.findall(r"```powershell\n(.*?)```", original, re.S)
    expanded_commands = re.findall(r"```powershell\n(.*?)```", expanded, re.S)
    if original_commands != expanded_commands:
        raise ValueError("Executable command blocks changed")
    OUTPUT.write_text(expanded, encoding="utf-8")
    record = {"source": str(SOURCE), "source_sha256": hashlib.sha256(original.encode()).hexdigest(),
              "output": str(OUTPUT), "output_sha256": hashlib.sha256(expanded.encode()).hexdigest(),
              "original_content_and_order_preserved": True,
              "original_powershell_blocks_preserved": len(original_commands),
              "inserted_explanation_sections": inserted,
              "measured_tables_source": str(METRICS),
              "measured_tables_source_sha256": hashlib.sha256(METRICS.read_bytes()).hexdigest(),
              "scope": "documentation only; no model, renderer or test evaluation run"}
    OUTPUT.with_suffix(".provenance.json").write_text(json.dumps(record, indent=2)+"\n", encoding="utf-8")
    print(f"Built {OUTPUT.name}: {len(inserted)} explanation sections; "
          f"{len(original_commands)} original command blocks unchanged")


if __name__ == "__main__":
    build()
