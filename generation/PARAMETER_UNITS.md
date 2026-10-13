# Vital/Vita units for the 13-control v4 dataset

Audit date: 13 October 2026. The installed Vita **0.0.5**, with the actual frozen
`base_restricted_bend_sustain_v4.vital`, was inspected without rendering audio.
All **221 control points** (17 per parameter) passed normalized/native round trips,
native/display mapping checks and **17 complete preset serialization round trips**.
All 13 selected controls are continuous according to the installed wrapper metadata.

Machine-readable evidence: [control_units_v4/summary.json](characterization/control_units_v4/summary.json).
Audit implementation: [audit_control_units.py](audit_control_units.py).
The generator, preset, dataset and frozen teammate package were not changed.

## Coordinates must not be mixed

- `q = *_sample_01`: Sobol coordinate within the RESTRICTED research interval.
- `n = *_normalized`: actual normalized wrapper control value within its full range.
- `r = *_raw`: native value returned by the engine; not universally a physical unit.
- `*_display`: wrapper-formatted text, including display scaling/offset and rounding.

The sampler maps `n_requested = low + q * (high - low)`. The wrapper is set with
`set_normalized(n_requested)`; the actual normalized/native values are read back
and recorded. Generation does not treat q or n as Hz/seconds. For reconstruction,
use `set_normalized(n)` or the native setter `set(r)`, never interchange them.
Do not parse rounded display strings as model targets.

## All selected controls

| Control | Restricted n | Native/display interpretation |
|---|---|---|
| Wavetable position | 0–1 | Native frame coordinate `r = 256n`, continuous; not an index into eight categorical choices. The embedded wavetable stays fixed. |
| Bend amount | .25–.75 | Native `r=n`, wrapper display 25–75%. For fixed Bend mode, .5 is the previously characterized neutral position; 0% is not the neutral midpoint. |
| Filter cutoff | .30–.85 | Native pitch coordinate `r=8+128n`; wrapper text is `r-60` semitones. Nominal unmodulated frequency about 119.265–6959.140 Hz. |
| Filter resonance | 0–.80 | Native 0–.8; wrapper display 0–80%. This is not a measured Q factor or gain in dB. |
| Filter drive | 0–.75 | Native/display `20n` dB, hence 0–15 dB. Not linear output loudness; the filter is nonlinear. |
| Amp attack | .05–.35 | Native pre-quartic value; nominal duration .000200–.480205 s. |
| Amp decay | .15–.40 | Native pre-quartic value; nominal duration .016200–.819208 s. |
| Amp sustain | .20–1 | Unitless envelope sustain control, .2–1. Not seconds or a direct perceived loudness percentage. |
| Amp release | .10–.45 | Native pre-quartic value; nominal duration .003200–1.312213 s. |
| Filter-envelope amount | .50–.5625 | Native `r=2n-1`, hence 0–.125. Normalized .5 is ZERO depth. Nominal peak cutoff movement 0–16 semitones for the fixed unipolar route. |
| Filter-envelope attack | .05–.35 | Same time mapping as amp attack: .000200–.480205 s. |
| Filter-envelope decay | .15–.40 | Same time mapping as amp decay: .016200–.819208 s. |
| Filter-envelope sustain | 0–1 | Unitless held fraction of filter-envelope depth. At zero depth this and the envelope timing controls are acoustically inactive. |

These are nominal settings, not measured acoustic feature values or guarantees of
audibility. The display values above are from `Vita.get_control_text`, not a claim
about every graphical Vital UI's chosen display formatting.

## Cutoff: native pitch, displayed offset, nominal frequency

With native cutoff r and the frozen default tuning:

`base_hz = 440 * 2 ** ((r - 69) / 12)`

For example `n=.5` gives native 72, wrapper text +12 semitones, and approximately
523.25 Hz. **Native 72 is not 72 Hz; displayed +12 is not MIDI note 12.**
The -60 display offset is relative to MIDI note 60, not automatically the currently
played note. Filter keytracking is fixed off in this preset. ENV2 then moves the
cutoff over time, so the static base-Hz label is not the whole cutoff trajectory.

## Envelope times: fourth-power scale

For the selected attack/decay/release controls, the installed native range is
0–2.3784201145. Within this wrapper, native r is approximately `2.3784201145*n`,
and the nominal time is **`r**4` seconds**, approximately `32*n**4`.
Thus n=.2 is about .0512 s, not .2 s; n=.4 is about .8192 s.
Fixed curve-shape controls affect envelope behavior too. The nominal stage time
does not assert that a waveform remains audibly active for exactly that duration.

## Envelope amount: destination-relative scaling

For the fixed ENV2-to-cutoff route, raw depth .125 nominally spans .125 times
the cutoff native range of 128 semitones: 16 semitones at full source output.
This is neither .125 Hz nor .125 semitones. The earlier restricted_v2 acoustic
characterization compared this against static cutoff offsets 0/8/16/24; 16 had
the lowest relative error (~.00197) and passed its .01 criterion. This is supporting
evidence for the unchanged route, not a fresh exhaustive acoustic test of v4.
Actual movement follows the envelope; sustain 1 also makes its decay ineffective.

## Implications for the research

Sobol is space-filling in the selected normalized coordinates, not uniformly in
Hz, seconds or perceptual descriptor values. Cutoff here is uniform in native
semitones/log-frequency; the envelope-time distribution follows the quartic map.
These are defensible coordinate choices if reported explicitly, not conversion
bugs. Changing that sampling distribution now is a new recipe decision.

Existing C2/C3 target loading uses `*_normalized`; it does not mistake cutoff
native values for Hz. C2 scales outputs to configured intervals; C3 parameter
distance rescales each restricted interval. Such distances are parameter-space
distances, not proof of perceptual similarity.

When implementing perturbations, declare the coordinate of the step. Equal n
steps are unequal Hz/second steps, especially for envelope times. The generation
mapping itself passed this audit; no unit-related rerender is indicated. The
full-corpus model/feature-loader integration remains a separate task.

## Supporting upstream source

The local pinned-build measurements above are the evidence for this dataset.
Upstream [parameter definitions](https://github.com/mtytel/vital/blob/main/src/common/synth_parameters.cpp)
also define cutoff's -60 display offset, quartic envelope scales and drive units.
[Synth-module scaling](https://github.com/mtytel/vital/blob/main/src/synthesis/framework/synth_module.cpp)
applies the quartic envelope transform; [frequency utilities](https://github.com/mtytel/vital/blob/main/src/synthesis/framework/futils.h)
map pitch offsets exponentially to frequency. Upstream main may change; do not
substitute its current code or packages for the frozen dataset runtime.

To rerun this no-render audit into a NEW report:

```powershell
.\venv\Scripts\python.exe -B -m generation.audit_control_units --output data/processed/control_units_recheck.json
```
