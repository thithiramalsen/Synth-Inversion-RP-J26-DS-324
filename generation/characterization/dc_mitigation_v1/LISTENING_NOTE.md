# Researcher listening follow-up — 7 October 2026

After reviewing the DC comparison page, the researcher reported:

> soo i listened with soundidreference as well and without. there was virtually no difference i heard and no clicks or anything.

This records one researcher's informal listening feedback, with SoundID Reference
enabled and disabled. No clip-by-clip judgments, trial counts, randomized/blinded
protocol, headphone model or playback levels were supplied. The report supports
accepting the correction for the next engineering stage; it does not establish
population-level perceptual equivalence or formal descriptor validity. No ratings
have been inferred or filled into the listening page.

## Decision

Select **dc_highpass_10hz_v1**: one causal second-order Butterworth high-pass pass
at 10 Hz, at 44,100 Hz, using float64 SOS and zero initial state per independent
clip. Use the exact tested coefficients saved in the
[policy](../../audio_policies/dc_highpass_10hz_v1.json). The numerical check found
0/394 full-clip DC warnings and no clipping after this filter; the report retains
short-window/transient and peak measurements. The 10 Hz option was already the
recommended, less aggressive candidate. The researcher did not supply a separate
preference rating between 10 Hz and 20 Hz.

The informal listening check is complete. No further broad listening exercise is
needed solely to identify DC offsets: continue automated QA when new audio is
generated, and inspect any new anomalies.

## Integration boundary

The policy is selected and versioned; production integration remains pending.
Apply it exactly once to audio used by study playback, feature/model inputs,
reference/re-synthesized comparisons and inference. Already conditioned audio
must carry its policy ID so downstream consumers do not filter it twice.
Preserve original FLOAT renders and record pre/post-filter QA and hashes.
SoundID Reference is a reported listening condition, not part of exported audio.
This decision introduces no loudness normalization, gain changes, fades or
selective processing of flagged clips.

The thirteen-control architecture remains selected. The new 1,024-sound dataset
has not been generated; the generation hold remains in force.
