# C2 full deterministic baseline: measured results

Completed 14 October 2026. This is the full-data **parameter-estimation baseline**;
ensemble uncertainty and calibrated reliability probabilities are the next stage.
All reported clips are inverse-validation examples. Final test evaluation remains reserved.

## Experiment

The completed 131,072-sound, 13-control v4 corpus uses the immutable C2 four-way
partition. This run fits on **98,304 training clips** and selects the model using
**4,096 inverse-validation clips**. Calibration, reliability-validation and test
examples are excluded from this training/evaluation command.

- Input: 64 x 259 fixed-reference log-mel; canonical DC conditioning on read.
- Model: existing compact three-block CNN, 13 bounded research-coordinate outputs.
- GPU pool: fixed 4x8 averaging, mathematically equivalent to the adaptive 2x4
  averaging for this input; equivalence and gradients checked.
- Training: Adam, learning rate .001, weight decay .0001, batch size 128, seed
  20261013, 60 maximum epochs, patience 12. All 60 epochs ran; **epoch 53** was best.
- Runtime: Python 3.13.14, PyTorch 2.13.0+cu130, CUDA 13.0, RTX 4060 Laptop GPU;
  strict deterministic algorithms, TF32 disabled, pinned scientific packages.
- Full feature preprocessing took about 985 seconds. Recorded training wall-clock
  time was about 2,702 seconds; these are observations of this run.

The original synthesis environment remains unchanged. Commands and the CUDA
overlay setup are documented in [V4_README.md](V4_README.md).

## Parameter recovery on 4,096 inverse-validation clips

Errors use `z=(actual_Vital_normalized-low)/(high-low)`. An MAE of .05 means
5% of that control's restricted research interval. This is not a perceptual JND.

| Control | MAE z | RMSE z | R2 |
|---|---:|---:|---:|
| Wavetable frame | .078432 | .106992 | .861098 |
| Bend amount | .216818 | .262532 | .165682 |
| Filter cutoff | .056082 | .081588 | .919057 |
| Filter resonance | .149575 | .191556 | .552953 |
| Filter drive | .180036 | .221752 | .404213 |
| Amp attack | .040772 | .053499 | .965886 |
| Amp decay | .090675 | .131770 | .790556 |
| Amp sustain | .049487 | .066501 | .947826 |
| Amp release | .025746 | .035617 | .984816 |
| Filter-envelope amount | .168136 | .210775 | .464376 |
| Filter-envelope attack | .171434 | .213378 | .457955 |
| Filter-envelope decay | .223305 | .266838 | .158404 |
| Filter-envelope sustain | .188961 | .233032 | .346583 |

Macro MAE z is **.126112**. Mean squared z error is **.031867**, compared with
**.083213** for always predicting the training-set mean. The delivered checkpoint
was independently reloaded and reproduced its validation predictions exactly.
Both z and Vital-normalized coordinate metrics are saved in the metric CSV.

Cutoff, amplitude attack/sustain/release and wavetable frame are the strongest
controls. Bend and filter-envelope decay have modest explained variance and large
remaining errors. The baseline has learned useful structure, but its outputs should
not all be presented with the same apparent certainty. This motivates evaluating
the reliability layer; it does not establish that the proposed diagnostics will help.

## Fair comparison with the development model

The development model was trained on 4,096 clips for eight CPU epochs. Comparing
its 512-clip scores directly with a 4,096-clip validation average would mix two
different evaluation sets. The comparison tool therefore aligns the **same original
512 inverse-validation IDs**, checks identical ground truth, and evaluates both
delivered prediction records on those IDs.

| Model | Training clips | Matched validation clips | Macro MAE z |
|---|---:|---:|---:|
| Development | 4,096 | 512 | .184187 |
| Full baseline | 98,304 | 512 | .126339 |

All **13 controls** have lower MAE on this matched set. The macro reduction is
about **31.4%**. This describes the complete training-regime change, including data,
epoch count, batch size and runtime; it does not isolate a causal effect of data size.
This is a development comparison, not final test evidence.

## Same audio example before and after full training

The earlier example ID `restricted_bend_sustain_v4_01394` was retained for comparison.
Its generating-parameter roundtrip still reproduces the target exactly. Diagnostic
rendering preserves the original prediction and isolates each perturbed control.

| Patch | Target distance under fixed MR-STFT D |
|---|---:|
| True generating parameters | .000000 |
| Research-range midpoint | 1.010885 |
| Development CNN | .363118 |
| Full CNN | .314926 |

The full model has lower numerical reconstruction distance for this clip. There
is no validated universal 'close enough' threshold and this number is not a
similarity percentage. Its component distances can trade off: spectral convergence
improved while log-magnitude discrepancy increased in this example.

The cutoff prediction also improved:

```text
True cutoff z:              .879103400
Development prediction z:   .810281694 -> error .068821707, outside tau=.05
Full prediction z:          .881722569 -> error .002619169, within tau=.05
```

One control's average improvement does not guarantee improvement for every clip.
For example, this clip's bend error increased, even though bend MAE improved across
the matched validation set. Parameter correctness and whole-audio reconstruction
remain distinct measurements. No U or q is claimed for this deterministic model.

## Saved evidence

Large artifacts are local and ignored by Git:

- `data/processed/c2_v4/baseline_full_v1/`: checkpoints, run configuration,
  training history, curves, 4,096 predictions, per-control metrics, mean baseline,
  and matched development comparison.
- `data/processed/c2_v4/worked_example_full_v1/`: target/prediction/perturbation
  WAVs, all 13 diagnostics and the numerical comparison record.
- `data/processed/c2_v4/cuda_environment.json`: actual runtime and dependency versions.

Checkpoint SHA-256:
`5bd9734ec7357d29cb4a1852c35e02aba3dcebc8b7caf9fec1edc6466d6c78fa`.

Prediction CSV SHA-256:
`f2e981d9560510c1727550fcf4a899f76d1de5d49090c95832f3742ea4a68a23`.

## Next research stage

Train probabilistic ensemble members with the same data protections. Start with
three members for development, then assess a five-member final run. Save within-member
variance, between-member disagreement and total variance; freeze the resulting
ensemble predictions before generating the diagnostic calibration data.

Then execute the 128-clip diagnostic smoke batch, bounded reliability experiment,
per-control calibration and controlled ablations. The small human usefulness study
comes after the reliability output and presentation are fixed.
