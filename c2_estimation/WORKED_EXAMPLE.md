# C2 worked example: actual development measurements

Update 14 October 2026: the full deterministic model has now been trained.
[FULL_BASELINE_RESULTS.md](FULL_BASELINE_RESULTS.md) compares the same clip with
the earlier model. Its target distance changed from .363118 to .314926, and cutoff
error z changed from .068822 to .002619. The measurements below preserve the
original development example; the new audio is under
`data/processed/c2_v4/worked_example_full_v1/`.

Measured 13 October 2026. This is **one development example**, not final test
evidence and not an uncertainty-calibrated prediction. Its numbers are real, not
illustrative invented confidence scores.

## Inputs and selection

- Target ID: `restricted_bend_sustain_v4_01394`.
- Selection: lowest-index clip among the fixed inverse-validation predictions,
  chosen without examining its reconstruction quality.
- Model: `baseline_development_v3`, eight epochs, 4,096 training clips, 512
  inverse-validation clips, deterministic 13-output CNN. The test partition is unused.
- Input: conditioned 44.1 kHz mono audio, three seconds; 64 x 259 log-mel features.
- Ground truth: recorded Vital readbacks rescaled to each control's research interval.

Machine-readable evidence is in
`data/processed/c2_v4/worked_example_v3/example.json` and
`parameter_diagnostics.csv`. The corresponding model checkpoint, predictions and
metrics are in `data/processed/c2_v4/baseline_development_v3/`.

## 1. Can the known parameters reproduce the target?

We set the 13 recorded controls in a fresh instance of the frozen synth, preserving
the preset, note, velocity, phase and rendering settings. After the canonical DC
conditioning, the roundtrip audio equaled the target exactly for this clip:

```text
D(target, true-parameter reconstruction) = 0
maximum absolute waveform sample error = 0
```

This checks the mapping and rendering path. It does not establish correctness for
every possible patch or prove that only these parameters can produce this sound.

## 2. How well does the predicted patch reconstruct before perturbation?

Map the CNN's z outputs back to Vital controls and render the complete patch once.
Compare it against the same target with the fixed symmetric MR-STFT diagnostic.

| Reconstruction | Distance to target (lower is closer under D) |
|---|---:|
| True generating parameters | 0.000000 |
| All controls at research-range midpoint, z=.5 | 1.010885 |
| CNN's frozen prediction | 0.363118 |

For this clip the CNN's reconstruction is numerically closer than the midpoint
patch. **0.363118 is not 63.7% similarity, a probability, or proof of perceptual
equivalence.** There is no validated universal 'close enough' cutoff yet.

Repeated rendering of the predicted patch was exact. Peak absolute amplitudes were
about .201 for the target and .199 for the prediction. Files are FLOAT WAVs with no
independent normalization. Start playback at a comfortable low volume.

Listen to the actual files:

- [Target](../data/processed/c2_v4/worked_example_v3/target.wav)
- [CNN prediction](../data/processed/c2_v4/worked_example_v3/predicted.wav)
- [Midpoint patch](../data/processed/c2_v4/worked_example_v3/midpoint_patch.wav)
- [True-parameter reconstruction](../data/processed/c2_v4/worked_example_v3/true_parameter_roundtrip.wav)

## 3. Perturb one control: filter cutoff

The frozen predicted cutoff is z=0.810281694. The actual generating cutoff is
z=0.879103400. Its allowed Vital interval is [.30, .85], so:

```text
predicted Vital normalized cutoff = .30 + .55 * .810281694 = .745654932
true Vital normalized cutoff      = .30 + .55 * .879103400 = .783506870
delta_z = .02 -> delta_Vital = .011
minus requested z = .790281694
plus requested z  = .830281694
```

The other 12 engine control readbacks were checked to remain unchanged.

| Comparison | Measured distance |
|---|---:|
| Minus vs plus render | 0.037923922 |
| Target vs original predicted patch | 0.363117745 |
| Target vs minus render | 0.364875255 |
| Target vs plus render | 0.362375980 |

The engine-readback span was 0.040000026876, giving:

```text
S_cutoff = .037923921573 / .040000026876 = .948097402
```

The plus version has a slightly smaller target distance. **We do not choose it.**
The original predicted patch remains the delivered estimate, and the diagnostic
stage verifies that its prediction record did not change. Searching for and keeping
the best perturbation would be refinement, which is outside this C2 experiment.

- [Cutoff minus](../data/processed/c2_v4/worked_example_v3/cutoff_minus.wav)
- [Cutoff plus](../data/processed/c2_v4/worked_example_v3/cutoff_plus.wav)

## 4. Is the cutoff prediction correct within the stated tolerance?

```text
error_z = abs(.810281694 - .879103400) = .068821707
tau_z   = .05
y_cutoff = 0
```

The cutoff misses the tolerance even though the overall reconstruction improves
over the midpoint baseline. R is a global audio discrepancy; it is not a per-control
correctness label. S describes local activity; it is not itself a correctness score.

## 5. All 13 control measurements

All values below are in research-range coordinates. S is acoustic distance per z
unit, evaluated around the frozen prediction with the other controls held fixed.

| Control | True z | Predicted z | Absolute error z | S | Within .05? |
|---|---:|---:|---:|---:|:---:|
| Wavetable frame | .446821 | .417218 | .029603 | 6.846138 | Yes |
| Bend amount | .369763 | .480201 | .110438 | 2.337926 | No |
| Filter cutoff | .879103 | .810282 | .068822 | .948097 | No |
| Filter resonance | .029343 | .487109 | .457766 | .788935 | No |
| Filter drive | .033195 | .472112 | .438917 | .648792 | No |
| Amp attack | .079006 | .154452 | .075446 | 1.415193 | No |
| Amp decay | .965022 | .951848 | .013174 | 1.818800 | Yes |
| Amp sustain | .043265 | .063689 | .020424 | 1.956800 | Yes |
| Amp release | .326837 | .346185 | .019348 | .081046 | Yes |
| Filter-envelope amount | .291150 | .573634 | .282484 | .144004 | No |
| Filter-envelope attack | .447676 | .531224 | .083549 | .234812 | No |
| Filter-envelope decay | .016693 | .591182 | .574489 | .039338 | No |
| Filter-envelope sustain | .462519 | .490542 | .028023 | .076636 | Yes |

Do not infer a general association between S and correctness from this one clip.
For example, low local activity can accompany either a correct or incorrect value.
That is precisely why the reliability relationship must be learned and tested.

## 6. Sanity checks and the missing final stage

The separate positive-control fixture set filter-envelope depth to zero, then
perturbed its attack. Its measured audio distance was exactly zero, as expected.
Same-patch determinism, one-control isolation and frozen-prediction preservation
also passed. These are implementation checks, not a complete identifiability proof.

No U or q is reported: this deterministic model does not provide ensemble variance
and no calibrator has been trained. After the ensemble and calibration stages, the
same procedure supplies U/S/R to a calibrator fitted on separate examples. Its q
must then be evaluated over many held-out clips against known correctness labels.
This example alone cannot demonstrate a reliability improvement.

## Reproduce

See [V4_README.md](V4_README.md) for the preparation/training commands. Once the
saved development run exists, use a new output directory:

```powershell
.\venv\Scripts\python.exe -B -m c2_estimation.v4.diagnostics --run data/processed/c2_v4/baseline_development_v3 --output data/processed/c2_v4/worked_example_recheck
```

Source corpus files and predicted parameter records are never overwritten.
