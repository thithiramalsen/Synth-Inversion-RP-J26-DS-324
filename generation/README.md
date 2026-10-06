# Twelve-control Vital configuration

The agreed research architecture uses one oscillator, one fixed Basic Shapes
wavetable, one Analog 12 dB low-pass filter, an amplitude envelope and a filter
envelope. Oscillators 2/3, the sample/noise source and effects remain off. The
wavetable asset is fixed; its position varies. MIDI note 60, velocity 0.8,
44.1 kHz mono PCM16, a 1.5 s held note and a 3 s recording are fixed.

`restricted_config.py` defines the new `restricted_v2` candidate domain.
`params_config.py` preserves the historical eight-control `pilot_v1` engineering
test. Existing C1 features, C2/C3 outputs and survey sessions still refer to
`pilot_v1`; they have not become twelve-control results.

## Controls and provisional ranges

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

## Build and characterize

Use the repository's existing Vita 0.0.5 environment:

```powershell
.\venv\Scripts\python.exe generation/scripts/03_create_base_preset.py
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

## Generate a separate candidate dataset when its specification is settled

```powershell
.\venv\Scripts\python.exe generation/scripts/05_generate_pilot_dataset.py --profile restricted_v2 --count 1024
```

Audio goes to `data/raw/audio/restricted_v2/`, and metadata to
`data/manifests/restricted_v2*`. The saved configuration includes parameter
order/ranges, fixed controls, modulation assignments, renderer versions, generator
hash and preset hash. Each row records the Sobol coordinates, actual normalized
and raw values, display values, QA metrics and WAV hash. No per-clip normalization
is performed. Silence/DC/clipping flags must be reviewed before stimulus selection.

The generator's new default is `restricted_v2`; legacy generation requires
`--profile pilot_v1`. Script 04 remains an engineering test for the old preset.
To explicitly recreate that old preset, use script 03 with `--profile pilot_v1`.
The saved `pilot_v1_config.json`, not mutable script defaults, documents the
historical 1024-sound run.

## Extend without regenerating existing sounds

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
