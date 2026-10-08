# C1 handoff: listening pilot and descriptor modelling

Prepared 8 October 2026. This note is for the C1 component owner. The survey is
being prepared by the C2 teammate to share the audio/survey workload; ownership
of C1's feature design, descriptor model and scientific analysis remains with C1.

## The shared project structure

- **C1:** human timbre descriptors, prediction of those judgments from audio,
  and investigation of descriptor changes under synth-control perturbations.
- **C2:** synth inversion, perturbation-based diagnostics and certainty/reliability.
- **C3:** alternative synth patches that can produce a similar sound.
- **C4:** human perceptual-similarity judgments between sounds.

C1 and C4 have the main human-data studies. All four components are expected to
have smaller human validation studies later. The repository's existing models
and feature routines are development implementations, not the final component
definitions or completed validation.

## What is ready to inherit

- A 1,024-candidate pool from the selected **13-control**, one-oscillator Vital
  configuration, including Bend and filter-envelope sustain. The older
  eight-control `pilot_v1` is a separate generation/model development dataset.
- A fixed selection of **64 study sounds plus 3 practice sounds**.
- A C1 survey for **brightness, roughness and percussiveness**, each rated 1–7,
  with a separate cannot-judge/unclear response. These remain candidate
  descriptors/instructions, not perceptually validated dimensions.
- Sixteen overlapping assignments: each participant hears 3 practice clips,
  32 distinct study clips and 4 hidden repeats, for **39 presentations**.
  Sixteen eligible completed assignments would give each study sound eight
  independent primary listeners. This is a feasibility budget, not a power result.
- Consent/background questions, volume/headphone setup, practice, break, resume,
  completion feedback, withdrawal and researcher exports. Previous-answer
  correction is allowed until the next presentation is explicitly started;
  original and corrected answers are retained in an audit trail.

The local short rehearsal on port 8771, when running, is not the full pilot.
See the [launch checklist](../survey/C1_PILOT_NEXT_STEPS.md) for the full rehearsal
and remaining participant-facing work. No formal pilot response collection is
confirmed in this handoff. Researcher/automated rehearsal responses are excluded
from research analysis.

## Audio and data locations

Paths below are relative to the repository root and are intentionally portable.

| Item | Location |
|---|---|
| DC-conditioned candidate FLOAT masters | `data/raw/audio/restricted_bend_sustain_v4/` |
| Preserved unconditioned FLOAT renders | `data/raw/audio/restricted_bend_sustain_v4/raw_float/` |
| Parameter values, source IDs and hashes | `data/manifests/restricted_bend_sustain_v4.csv` |
| Generator settings | `data/manifests/restricted_bend_sustain_v4_config.json` |
| Exact selected audio, gains, source mapping and assignments | `data/processed/c1_pilot_v1/bundle.json` |
| Participant playback | `data/processed/c1_pilot_v1/audio/sound_001.wav` through `sound_067.wav` |
| FLOAT copies for analysis | Matching `sound_###_features.wav` files in that directory |
| Descriptor wording and participant information | `survey/config/c1_pilot_v1.json` |
| Current descriptive response analysis | `survey/analyze_c1_pilot.py` |
| Development feature extraction | `c1_timbre/extract_pilot_features.py`, `feature_extraction.py` |

Sounds 001–064 are study items; 065–067 are practice. Use the bundle's source IDs
to join ratings to the original parameter manifest, not file order or guessed
candidate numbering. Hidden repeats reuse a sound ID but have distinct
presentation IDs. Local audio/databases are Git-ignored: a code checkout alone
does not transfer these files or collected responses.

## Audio processing that must be preserved

The sources are mono, 44.1 kHz, with a fixed MIDI note held for 1.5 seconds and
three seconds rendered in total. A versioned 10 Hz high-pass removes DC exactly
once. The selected study then applies constant gain per clip to match RMS over
0–1.5 seconds, using a common target with peak headroom. Gains and hashes are
recorded in the bundle. This is level control, not proof of equal perceived
loudness. There is no added compressor or fade.

`sound_###.wav` is PCM16 playback. `_features.wav` is the corresponding FLOAT
signal, not a second trial or a table of features. Never DC-filter or normalize
either study copy again silently. Feature inputs should correspond to what
participants heard; explicit handling of encoding differences is required.

The short endings reported for sounds 002, 003, 018 and 019 were traced to short
amp releases after scheduled note-off. Moving note-off moved the endings, and
longer release lengthened them. No replacement renders were warranted by that
check. It was not a formal perceptual equivalence test.

## Known challenge: encoding-sensitive development features

The [full precision audit](../generation/characterization/pcm_precision_v1/REPORT.md)
compared all 1,024 FLOAT candidates with PCM16 and PCM24, plus the selected study
copies. No candidate clipped under conversion. However, the current C1
centroid/MFCC calculations can give very quiet frames and weak spectral values
too much influence. Tiny encoding changes then cause disproportionately large
summary-feature changes.

Examples: a candidate's mean centroid changed by up to 1,435.66 Hz under PCM16;
about 89% of that worst shift came from frames below -60 dBFS RMS. Even PCM24
changed some C1 values. For the already prepared 67 study files, the existing
extractor's FLOAT/playback centroid difference had a median of 240.56 Hz and a
maximum of 760.27 Hz. These numbers do not demonstrate audible brightness
changes or make FLOAT features perceptual ground truth.

**C1 owner action before model fitting:** specify and version meaningful frame
energy handling and spectral floors; check feature stability on the exact study
audio; preserve useful temporal/envelope information explicitly. Then evaluate
predictive usefulness against held-out human judgments. Do not simply discard
unfavourable samples or choose features using test labels. A trained C1 model has
not yet been established here.

This work can follow the pilot because features can be recomputed from the same
frozen sounds. **Descriptor wording, rating task, presented audio and inclusion
rules cannot be silently changed retrospectively.** Agree those now and record
any later study version separately.

The C1 64-sound selector uses a separate combination of parameter spread and
energy-based acoustic summaries; it does not call the flagged C1 MFCC extractor.
The precision finding therefore does not by itself require discarding this
selection. This is not a claim of complete parameter/perceptual coverage.

## What belongs to whom

| Responsibility | Owner / timing |
|---|---|
| Stable playback, assignments, response saving, exports and audio provenance | Survey preparation, before collection |
| Descriptor wording, study aims and planned response interpretation | C1 owner with survey preparer, before collection |
| Feature definitions, modelling and leakage-free validation | C1 owner, before relying on the descriptor model |
| Clipping/format policy for the shared master corpus | Team decision; PCM16 is not yet frozen as an interchangeable master |
| Encoding-sensitive C3 MFCC retrieval | C3 owner, before relying on those rankings |
| C4 comparison selection | C4 owner with survey preparer, before finalising C4 stimuli |

The old C4 triplet selector reads the development C1 MFCC table. Review or
replace that dependence before constructing C4's main study. MFCC rankings are
not human correct answers. C2 log-mel changes were small in this audit, but it
did not validate trained-model accuracy, certainty or perturbation diagnostics.

## What to provide after collection

Give the C1 owner the frozen protocol snapshot/hash, bundle and exact presented
audio, candidate source mapping, response export, session/exclusion audit,
correction history and this finding/report. Keep contact/recruitment information
and invitation/admin secrets separate from the analysis handoff.

Before analysis:

1. Account for completed, partial, replaced, withdrawn and rehearsal sessions.
2. Keep practice separate; never count hidden repeats as independent listeners.
3. Keep unclear responses distinct from rating 4 or zero.
4. Check per-sound coverage, participant/sound dependence, repeat differences,
   descriptor understanding and rating distributions.
5. Treat the 64 labelled sounds as 64 distinct audio examples, not hundreds of
   independent examples because each sound has multiple ratings.
6. Split model development/evaluation by sound and related-source families as
   appropriate; fit preprocessing on development/training data only.
7. Do not claim that predicting labels for 131,072 synthetic sounds creates
   additional human-labelled evidence or proves full-domain validity.

Suggested research-log wording:

> During audio-format evaluation, the development C1 feature extractor showed
> sensitivity to low-energy spectral content and encoding precision. The study
> audio and ratings were preserved. Feature definitions require explicit energy
> and numerical-floor handling before descriptor-model fitting. The audit is
> engineering evidence; perceptual validity remains to be evaluated.

Update that paragraph with the actual fix and validation once completed; it is
not currently a claim that the issue has been resolved.
