# Keep Bend and filter-envelope sustain — 7 October 2026

The researcher explicitly chose to retain variable filter-envelope sustain after
choosing Bend. This supersedes the same-day twelve-control architecture-B choice
recorded in `2026-10-07_bend.md`; the old record and profile are preserved.

The selected profile is `restricted_bend_sustain_v4`, implemented in
`generation/bend_sustain_config.py`. It contains 13 controls: wavetable position;
Bend amount; filter cutoff/resonance/drive; amp ADSR; and filter-envelope
amount/attack/decay/sustain. The builder/generator CLI defaults select this version.
It has a separate preset and future manifest/audio paths. Existing datasets and
A/B renders retain their original parameter schemas.

## Rationale and limitations

Bend changes oscillator waveform shape; filter-envelope sustain controls the
held spectral trajectory. Keeping both preserves these two mechanisms. Thirteen
is not justified by the number itself, and retaining the controls does not prove
perceptual independence. Conditional inactivity remains: zero envelope amount
removes ENV2 effects, while sustain 1 makes its decay level drop zero. Other
masking/interactions need characterization in the combined domain.

The provisional Bend interval remains .25-.75 (neutral .5); filter-envelope sustain
uses 0-1 with base .4. Other ranges are inherited from architecture A. Oscillator
2/3, noise and effects remain off; wavetable asset, filter type, warp mode/phase,
routing, note/velocity and rendering protocol remain fixed.

The previous A/B evidence concerns different twelve-control architectures. The
new combined check contains only 18 settings (two envelope/filter backgrounds,
three Bend levels and three sustain levels, with wavetable .5 and cutoff .575).
It is a diagnostic check, not a space-filling study or descriptor validation.

## DC mitigation selection

The [measured check](../characterization/dc_mitigation_v1/REPORT.md) reused all 376
saved A/B renders and the 18 combined renders. Both causal second-order Butterworth
10 Hz and 20 Hz high-pass filters reduced 128/394 raw full-clip DC warnings to
0/394. Neither clipped; the maximum peak rose from .2814 raw to .3499 at 10 Hz
and .3601 at 20 Hz. All source WAVs were preserved and verified against hashes.

Select **10 Hz** as the less aggressive tested candidate. The researcher subsequently
reported virtually no audible difference and no clicks with and without SoundID
Reference; the [listening follow-up](../characterization/dc_mitigation_v1/LISTENING_NOTE.md)
records this as an informal engineering check. The exact selected settings are
versioned as [dc_highpass_10hz_v1](../audio_policies/dc_highpass_10hz_v1.json).
This is not a formal perceptual equivalence result. Whole-clip mean subtraction is unsuitable as the default
here: it introduced nonzero offsets into originally silent tails (maximum .0331).

No processing has been inserted into dataset generation/training/inference.
Integration must apply the selected fixed rule exactly once to study audio,
feature inputs, references/re-synthesis and incoming inference audio. Tag processed
audio with the policy ID to prevent downstream double filtering. Preserve raw FLOAT WAVs and
perform level/clipping/DC checks before and after conditioning; write playback
PCM only afterwards. DC filtering and loudness normalization are separate decisions.

The new 1,024-sound dataset remains on hold. No participant results or recovered
per-context votes are implied by this decision.
