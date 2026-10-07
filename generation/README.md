# Vital generation configurations

## Current selection: 13 controls, Bend plus filter-envelope sustain

On 7 October 2026 the researcher chose to keep **both Bend and variable
filter-envelope sustain**, superseding the earlier twelve-control B selection.
The current profile is **`restricted_bend_sustain_v4`** in
`bend_sustain_config.py`: wavetable position, Bend amount, cutoff/resonance/drive,
amp ADSR and filter-envelope amount/attack/decay/sustain. Oscillator 2 remains off.
See [the combined-architecture decision](decisions/2026-10-07_bend_and_sustain.md).

The Bend mode/phase/spread and unused spectral morph controls are fixed. Bend .5
is neutral; .25-.75 is the provisional interval from the main A/B comparison.
All other ranges and note/rendering settings are inherited from architecture A
below. The build and generator defaults now select `restricted_bend_sustain_v4` with a
separate preset, audio directory and manifest prefix. Older versions remain
available explicitly by `--profile`.

| Variable control | Provisional normalized interval |
|---|---|
| Wavetable position | 0-1 |
| Bend amount | .25-.75; neutral .5 |
| Filter cutoff | .30-.85 |
| Filter resonance | 0-.80 |
| Filter drive | 0-.75 |
| Amp attack | .05-.35 |
| Amp decay | .15-.40 |
| Amp sustain | .20-1 |
| Amp release | .10-.45 |
| Filter-envelope amount | .50-.5625; zero depth .50 |
| Filter-envelope attack | .05-.35 |
| Filter-envelope decay | .15-.40 |
| Filter-envelope sustain | 0-1 |

The separate Bend preset can be built and checked without generating a dataset:

```powershell
.\venv\Scripts\python.exe generation/scripts/03_create_base_preset.py --profile restricted_bend_sustain_v4
.\venv\Scripts\python.exe -m unittest discover -s generation/tests -v
```

**The new 1,024-sound pool remains on hold.** The
[DC-mitigation check](characterization/dc_mitigation_v1/REPORT.md) compared 376
saved A/B WAVs plus 18 combined-control diagnostic renders. Both causal 10 Hz and
20 Hz second-order high-pass filters reduced the engineering DC-flag count from
128/394 to 0/394, with no clipping. The researcher subsequently reported virtually
no audible difference and no clicks, with and without SoundID Reference. The
[informal listening check](characterization/dc_mitigation_v1/LISTENING_NOTE.md)
is complete, and **[dc_highpass_10hz_v1](audio_policies/dc_highpass_10hz_v1.json)**
is the selected processing policy. The v4 generator now applies it exactly once,
preserving raw FLOAT WAVs and writing separate DC-conditioned FLOAT WAVs with
pre/post QA, hashes and policy metadata. Resume verifies both raw and processed
files and preserves the Sobol prefix. An isolated two-to-four-sample extension
and tamper test passed; the new 1,024 pool has not been rendered.
Historical datasets and training/inference implementations have not been converted.
Original WAVs are preserved. Six original/10 Hz/20 Hz listening examples are in
`test_renders/dc_mitigation_v1/LISTEN.html`.

The separate [C1 preparation](../survey/C1_PILOT_RUNBOOK.md) selects study sounds
and applies a versioned constant-gain level rule after DC filtering. The rule needs
researcher audition before recruitment. Feature extraction reads the bundle's
already conditioned signal without applying either policy again.
SoundID Reference is not part of the
dataset processing. The listening feedback is an informal engineering check,
not a formal perceptual equivalence or descriptor study.

The extra control increases the space to characterize. Neither the A/B comparison
nor the 18 combined settings establish coverage of the 13-dimensional domain or
perceptual independence. ENV2 controls remain inactive at zero modulation depth;
at sustain 1 the filter-envelope decay stage has no level drop to control.
The preserved B profile (`restricted_bend_v3`) still fixes sustain at zero, so
the original A/B experiment remains reproducible. The earlier qualitative Bend
preference is informal; available page/downloads contained no per-context ratings.

## Preserved architecture A: restricted_v2

For the separate Bend-versus-filter-envelope-sustain experiment, see
[the comparison protocol](ARCHITECTURE_COMPARISON.md) and
[measured A/B results](characterization/architecture_ab_v1/REPORT.md).
The experiment and its original architecture-A reference are preserved.

Architecture A uses one oscillator, one fixed Basic Shapes
wavetable, one Analog 12 dB low-pass filter, an amplitude envelope and a filter
envelope. Oscillators 2/3, the sample/noise source and effects remain off. The
wavetable asset is fixed; its position varies. MIDI note 60, velocity 0.8,
44.1 kHz mono PCM16, a 1.5 s held note and a 3 s recording are fixed.

`restricted_config.py` defines the preserved `restricted_v2` comparison domain.
`params_config.py` preserves the historical eight-control `pilot_v1` engineering
test. Existing C1 features, C2/C3 outputs and survey sessions still refer to
`pilot_v1`; they have not become results for the selected thirteen-control domain.

### Architecture A controls and provisional ranges

All table bounds below are **native Vital normalized values**, not Hz or seconds.
They are initial technical bounds, not evidence of complete perceptual coverage.

| # | Parameter | Vital control | Min | Max | Reason / qualification |
|---|---|---|---:|---:|---|
| 1 | Wavetable position | `osc_1_wave_frame` | 0 | 1 | Spectral shape within the fixed eight-keyframe table. |
| 2 | Filter cutoff | `filter_1_cutoff` | .30 | .85 | Nominal unmodulated cutoff about 119-6959 Hz; inherited candidate range. |
| 3 | Filter resonance | `filter_1_resonance` | 0 | .80 | Emphasis near cutoff; depends on source spectrum and cutoff. |
| 4 | Filter drive | `filter_1_drive` | 0 | .75 | Nonlinear spectral change; inspect DC-offset warnings. |
| 5 | Amp attack | `env_1_attack` | .05 | .35 | Approximately 0.0002-0.4802 s. |
| 6 | Amp decay | `env_1_decay` | .15 | .40 | Approximately 0.0162-0.8192 s; inactive at sustain 1. |
| 7 | Amp sustain | `env_1_sustain` | .20 | 1 | Held amplitude relative to the peak. |
| 8 | Amp release | `env_1_release` | .10 | .45 | Approximately 0.0032-1.3122 s; fits after note-off in the candidate recording. |
| 9 | Filter-envelope amount | `modulation_1_amount` | .50 | .5625 | Positive depth: raw 0-.125, nominal 0-16 semitones. **Normalized .5 is zero depth.** |
| 10 | Filter-envelope attack | `env_2_attack` | .05 | .35 | Rise of the cutoff envelope, about 0.0002-0.4802 s. |
| 11 | Filter-envelope decay | `env_2_decay` | .15 | .40 | Fall toward filter-envelope sustain, about 0.0162-0.8192 s. |
| 12 | Filter-envelope sustain | `env_2_sustain` | 0 | 1 | Held fraction of cutoff modulation depth. |

Compared with the eight-control test, the candidate amp attack/decay maxima are
shorter: their sum is about 1.2994 s, leaving time for a held segment before the
1.5 s note-off. The same bound applies to ENV 2. This is a recording-window
constraint, not a claim that longer envelopes are unimportant. Positive cutoff
depth is initially limited to 16 semitones; the maximum base raw cutoff 116.8
plus 16 remains below the control maximum 136. Other bounds are retained as
engineering starting points. Human coverage, duration and playback-level policy
must still be assessed before collecting a formal descriptor dataset.

Envelope 2 is connected to Filter 1 cutoff in modulation slot 1, unipolar,
unbypassed, without stereo modulation or a modulation curve. Its release is
fixed at normalized .30 (about .2592 s). Envelope delays and holds are zero;
attack curves are fixed at raw 0 and decay/release curves at raw -2. Oscillator
level, phase, unison, filter type/blend, routing and key tracking are fixed.
Exact settings are recorded in the profile and generated dataset configuration.

At zero depth, ENV 2 attack/decay/sustain have no cutoff effect. At ENV 2 sustain
1, its decay is inactive. Base cutoff, depth and sustain can compensate for
each other, and the amplitude envelope can mask spectral transients. These are
conditional effects to analyze, not grounds for claiming unique identifiability.

### Build and characterize architecture A

Use the repository's existing Vita 0.0.5 environment:

```powershell
.\venv\Scripts\python.exe generation/scripts/03_create_base_preset.py --profile restricted_v2
.\venv\Scripts\python.exe -m generation.characterize
.\venv\Scripts\python.exe -m unittest discover -s generation/tests -v
```

The builder requires the local factory-derived
`presets/basic_shapes_source_RP.vital`. It creates a separate
`presets/base_restricted_v2.vital`, verifies the twelve controls, fixed settings,
modulation route and preset serialization. Factory-derived presets remain
excluded from Git. Do not replace a preset already bound to a generated dataset.

Characterization records calibration at low/middle/high values and renders all
twelve controls at three values across three background patches (108 sweep
renders). Additional checks test repeatability, zero-depth invariance,
sustain-one decay invariance and the nominal modulation-depth mapping.
Reports are in [characterization/restricted_v2](characterization/restricted_v2/);
listening WAVs are in `test_renders/restricted_v2/` (ignored by Git).

The activity threshold (relative waveform RMS difference > 0.0001) and invariance
tolerance (maximum sample difference <= 0.0000001) are numerical checks, **not
audibility thresholds**. Depth calibration compares a constant envelope against
static cutoff offsets in a 0.1-1.4 s window, allowing 1% relative waveform RMS
error. The saved run passed these checks, with no silent/clipped sweep renders.
Two high-cutoff drive cases have DC warnings; inspect their WAVs before deciding
on preprocessing. Passing these probes does not validate all parameter
combinations, listener agreement, the descriptors, or the final parameter bounds.

### Architecture A generation reference

```powershell
.\venv\Scripts\python.exe generation/scripts/05_generate_pilot_dataset.py --profile restricted_v2 --count 1024
```

Audio goes to `data/raw/audio/restricted_v2/`, and metadata to
`data/manifests/restricted_v2*`. The saved configuration includes parameter
order/ranges, fixed controls, modulation assignments, renderer versions, generator
hash and preset hash. Each row records the Sobol coordinates, actual normalized
and raw values, display values, QA metrics and WAV hash. No per-clip normalization
is performed. Silence/DC/clipping flags must be reviewed before stimulus selection.

The generator's current default is `restricted_bend_sustain_v4`; reproducing this older
domain requires `--profile restricted_v2`. Legacy eight-control generation
requires `--profile pilot_v1`. Script 04 remains an engineering test for the old preset.
To explicitly recreate that old preset, use script 03 with `--profile pilot_v1`.
The saved `pilot_v1_config.json`, not mutable script defaults, documents the
historical 1024-sound run.

### Extend architecture A without regenerating existing sounds

If the configuration is unchanged, the first 1024 twelve-control renders can
remain the prefix of the larger corpus:

```powershell
.\venv\Scripts\python.exe generation/scripts/05_generate_pilot_dataset.py --profile restricted_v2 --count 131072 --resume
```

`--count` is the **total**, so this would render 130048 additional WAVs. The
old eight-control 1024 sounds are a different dataset and do not count toward
this prefix. New totals must be powers of two to retain Sobol balance. Selected
listening subsets are not themselves claimed to retain full Sobol balance.

Resume checks configuration/versions, preset and generator hashes, Sobol row
order, stored parameter values and existing WAV hashes. It does not overwrite
existing WAVs or shrink a dataset. Changed bounds, rendering, routing, code or
assets require a new version. A crash may leave WAVs beyond the last manifest
checkpoint; resume stops and identifies their presence so they can be inspected
and archived, rather than silently overwritten. `--overwrite` explicitly
replaces only the selected dataset and is incompatible with `--resume`.

Keep development-used human ratings separate from untouched evaluation data even
when their WAVs belong to the larger corpus. Diagnostic perturbation renders are
additional experiments, not additional independent training labels.
