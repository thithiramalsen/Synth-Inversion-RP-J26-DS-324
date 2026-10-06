# DC-mitigation engineering check

Saved A/B renders: 376. New combined Bend/sustain diagnostic settings: 18.
No new 1,024-sound dataset was generated. Source float WAVs are preserved and hash-verified.

## Measurements

| Group | Method | Clips | DC flags | Clipping | Max absolute mean | Max peak | Max final 50 ms peak |
|---|---|---:|---:|---:|---:|---:|---:|
| previous_AB | raw | 376 | 122 | 0 | 0.03309175 | 0.2814208 | 0 |
| previous_AB | subtract_clip_mean | 376 | 0 | 0 | 1.203035e-17 | 0.2829672 | 0.03309175 |
| previous_AB | highpass_10hz | 376 | 0 | 0 | 1.610978e-12 | 0.3498697 | 3.515896e-09 |
| previous_AB | highpass_20hz | 376 | 0 | 0 | 8.704246e-15 | 0.3600965 | 1.558659e-12 |
| combined_13 | raw | 18 | 6 | 0 | 0.02165172 | 0.1871648 | 0 |
| combined_13 | subtract_clip_mean | 18 | 0 | 0 | 5.509996e-18 | 0.2034367 | 0.02165172 |
| combined_13 | highpass_10hz | 18 | 0 | 0 | 1.057422e-12 | 0.2500175 | 2.284245e-09 |
| combined_13 | highpass_20hz | 18 | 0 | 0 | 5.70186e-15 | 0.257304 | 1.01267e-12 |
| all | raw | 394 | 128 | 0 | 0.03309175 | 0.2814208 | 0 |
| all | subtract_clip_mean | 394 | 0 | 0 | 1.203035e-17 | 0.2829672 | 0.03309175 |
| all | highpass_10hz | 394 | 0 | 0 | 1.610978e-12 | 0.3498697 | 3.515896e-09 |
| all | highpass_20hz | 394 | 0 | 0 | 8.704246e-15 | 0.3600965 | 1.558659e-12 |

The flag is abs(mean) >= .005 or abs(mean)/RMS >= .20. A full-clip mean is a finite-window diagnostic, not proof of a stationary DC component or an audibility test. `metrics.csv` also records held-note mean, maximum absolute sliding 50 ms mean, and ending samples; envelope transients and ordinary low-frequency signal can contribute to these measurements.

## Processing and limits

Both high-pass candidates are second-order Butterworth filters, designed at 44,100 Hz and applied causally in float64 with SOS and zero initial state. The same filter applies to every sample, with no gain normalization, fades, padding or selective correction. Summary JSON records coefficients and steady-state magnitude at DC, 20 Hz, 50 Hz and MIDI 60's fundamental. Those responses do not establish transparency for attacks/tails.

Subtracting a clip's mean is a diagnostic comparison only: it shifts any otherwise silent tail by that mean. A high-pass filter instead rejects a constant component while also affecting slow changes/transients; it can ring or alter peak level. Check those effects rather than assuming zero mean alone is sufficient.

The 18 new renders hold wavetable .5 and cutoff .575, cross Bend .25/.5/.75 with filter-envelope sustain 0/.4/1 under driven-pluck and resonant-driven-swell backgrounds. They test combined controls at a few settings, not full 13-dimensional coverage. Prior A/B conclusions cannot simply be assigned to the combined architecture.

## Listening and adoption

The initial recommendation is **10 Hz**, the less aggressive of the two tested
cutoffs: both cleared the full-clip DC screen, and the 10 Hz version had the smaller
maximum peak (.3499 versus .3601). This is not proof of perceptual transparency.
Neither filter makes every short-window mean exactly zero: the largest absolute
50 ms mean was .0150 at 10 Hz versus .0919 raw. Transient behavior still matters.

Open `generation/test_renders/dc_mitigation_v1/LISTEN.html` for a small set of original/10 Hz/20 Hz comparisons. Selection rules and hashes are in `listening_examples.csv`. Playback copies share gain 1.0 and PCM16 encoding. No human listening result has been recorded by this script.

Before adopting: listen for clicks and unwanted changes to attack, body and release on these examples; freeze one conditioning policy/version; apply it consistently to study playback, model feature inputs, reference/re-synthesized audio and incoming inference audio. Preserve raw audio, compute QA before and after filtering, and re-check ranges/descriptor behavior on the final architecture. No conditioning has been added to production generation/training/inference by this experiment.

References: [Smith, DC Blocker](https://www.dsprelated.com/freebooks/filters/DC_Blocker.html); [SciPy Butterworth design](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.butter.html); [SciPy SOS filtering](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.sosfilt.html).
