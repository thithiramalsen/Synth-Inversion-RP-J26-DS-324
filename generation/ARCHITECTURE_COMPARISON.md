# A/B architecture comparison protocol

This experiment compares the current twelve-control configuration (A) with a
candidate that replaces variable filter-envelope sustain with oscillator Bend
amount (B). It does not change `restricted_config.py`, its preset, dataset
generation defaults, or any existing training dataset. It does not generate the
new 1,024-sound pool.

Run from the repository root using the existing Vita environment:

```powershell
.\venv\Scripts\python.exe -B -m generation.compare_architectures
```

The default experiment ID is `architecture_ab_v1`. Existing output directories
are refused. Use a new `--run-id` for a new experiment; results are not silently
overwritten. Factory-derived diagnostic presets and audio stay in the ignored
`generation/test_renders/<run-id>/` directory.

## What is varied and why

| Setting | A: current architecture | B: proposed architecture |
|---|---|---|
| Eleven common variable controls | Wavetable; cutoff/resonance/drive; amp ADSR; filter-envelope amount/attack/decay | Same |
| Twelfth variable control | Filter-envelope sustain | Oscillator 1 Bend amount |
| Filter-envelope sustain | Tested at 0, 0.4, 1 | Fixed at 0 |
| Oscillator wave warp | None | Bend, fixed mode |
| Bend amount | Inactive, fixed at 0.5 | Tested at 0.25, 0.5, 0.75; separate 0/1 stress probes |

The installed wrapper's Bend neutral point is calibrated at normalized 0.5 by
comparison to warp disabled. It is not assumed to be normalized zero. Wave-warp
phase is fixed at raw 0.5 and spread at raw 0. Spectral morph is disabled, its
amount fixed at 0.5 and spread at 0. Oscillator 2/3, noise and effects remain off.
The Basic Shapes asset, oscillator phase/randomization, unison and routing stay
fixed. The experiment uses the current 44.1 kHz, MIDI 60, velocity 0.8,
1.5-second held note and 3-second recording.

The main grid crosses **3 wavetable positions x 3 cutoffs x 4 backgrounds =
36 contexts**. Each has three A and three B variants, giving **216 main renders**.
Wavetable positions 0, 0.5 and 1 and cutoff values 0.30, 0.575 and 0.85 probe
endpoints and an interior point; these are technical samples, not representative
coverage of a continuous domain. Three Bend levels include both sides of neutral
and help distinguish a one-sided effect from symmetry around the center.

All values below are native normalized control values. Exact settings and actual
wrapper readbacks are saved in the manifest.

| Background | Resonance | Drive | Amp A/D/S/R | Filter amount/A/D |
|---|---:|---:|---|---|
| clean_held | .20 | 0 | .10/.30/.80/.30 | .53125/.20/.30 |
| resonant_held | .75 | 0 | .10/.30/.80/.30 | .53125/.20/.30 |
| driven_pluck | .20 | .75 | .05/.20/.20/.15 | .5625/.05/.20 |
| resonant_driven_swell | .75 | .75 | .35/.40/.80/.45 | .5625/.35/.40 |

The clean/resonant held pair isolates resonance. The other backgrounds combine
drive and envelope changes to stress different conditions; this is **not** a
full factorial estimate of separate drive/envelope interactions. Every A/B and
within-B comparison holds its background constant.

Two additional Bend extremes (0 and 1) are rendered at middle wavetable position,
low/high cutoff, and all four backgrounds: 16 stress renders. For the acoustic
overlap screen, a 9-position wavetable x 5-cutoff grid is rendered without Bend,
with ENV2 sustain zero, in each background. Reusing 36 main references leaves
144 additional reference renders. Total: **376 distinct sound settings**.
Repeatability/round-trip checks rerender selected settings without adding them to
the sound pool. This is a diagnostic design, not a Sobol training sample.

## Questions and operational checks

1. **Does Bend change audio?** Compare all three main Bend pairs per context.
   Relative waveform RMS difference above 0.0001 is called numerically active.
   This threshold rejects numerical noise; it is not an audibility threshold.
   Also report the waveform difference after held-note RMS matching and the
   spectral-shape difference, so a large phase/level change is not automatically
   called a timbral improvement.
2. **Is it audible/useful?** Human listening remains required. The listening page
   provides a predeclared 12-context shortlist (each background, all three
   cutoffs, rotating wavetable position), and access to every main context.
   These are informal engineering judgments, not a blinded listening experiment,
   a participant sample, or a population audibility estimate.
3. **Can wavetable/cutoff already provide it?** Compare each non-neutral main B
   sample to the best no-Bend match in the finite grid, holding the remaining
   controls and ENV2 sustain zero. Extract mean STFT power in 48 log-spaced bands
   from 40-16,000 Hz in windows 0-.2, .2-.7 and .7-1.5 seconds. Normalize band power
   separately per window and use equally weighted Hellinger distance. The
   signature is insensitive to uniform gain and discards phase. Constant frame
   detrending suppresses DC. A coarse grid can miss better continuous matches;
   this is not proof of independent information, perceptual novelty, or A/B
   equivalence. It also does not search all other A controls. Low-energy windows
   are normalized like others and can overemphasize inaudible residuals.
4. **Audio quality:** Measure peak, RMS, DC, DC/RMS and final-50-ms peak before
   writing any playback transformations. Silence threshold is -60 dBFS RMS;
   clipping/over-range threshold is peak >=1. A DC review flag means |mean| >=.005
   or |mean|/RMS >=.20. Flags are diagnostic, not listener-based quality limits.
   Compare main A/B counts separately from extreme/reference probes; the groups
   are deliberately constructed and do not estimate prevalence in a dataset.
5. **Determinism:** Fresh-instance repeats for 24 selected settings: A at its
   current .4 sustain, B at all three main Bend levels, and both Bend extremes,
   in every background. Maximum sample error must be <=1e-7.
6. **Wrapper/preset reliability:** At those same settings, check every requested
   parameter/fixed setting and modulation route after JSON and saved `.vital`
   round-trips, then compare rendered audio (<=1e-7 maximum sample error).
   Also test warp-disabled amount invariance and the neutral B vs A-sustain-zero
   comparison in all 36 contexts (<=2e-6, allowing small floating-point path
   differences). These tolerances are numerical, not psychoacoustic.

## How to listen

Open `generation/test_renders/architecture_ab_v1/LISTEN.html` in a browser.
The page has two playback views:

- **Native levels:** one common gain across all clips, preserving level differences.
- **Held-note RMS matched:** a scalar gain per clip using the 0-1.5-second window;
  a shared headroom factor prevents clipping. This is not perceptual loudness
  matching. No DC correction, EQ, compression or per-clip peak normalization is
  applied. Gains and achieved target are recorded in the summary/manifest.

Original float WAVs preserve unprocessed output, even if it exceeds PCM bounds.
Playback WAVs use PCM16 for browser compatibility. Computational measures use the
original samples. Both versions remain separate from all training audio.

Within each context:

1. Compare A sustain 0 and B Bend .5: this isolates the neutral-mode check.
2. Compare B .25/.5/.75 in both playback views: note a clear, subtle, absent or
   uncertain difference and describe the change/artifacts.
3. Compare A sustain 0/.4/1: assess the capability being removed, not just what
   Bend adds. Compare A .4 to B .5 to isolate removal of the sustained cutoff
   offset before judging a warped B version.
4. Expand the closest-grid-match players and compare their tone to the matching
   Bend clip; numerical nearest neighbors need not be perceptually equivalent.
5. Download listening notes before closing the tab. They are not sent anywhere
   and are not persisted automatically.

The saved engineering report should distinguish computational outcomes from the
remaining listener judgments. Neither 36 contexts nor 376 diagnostic sounds
establish full parameter/descriptor coverage or settle the human-study sample size.
