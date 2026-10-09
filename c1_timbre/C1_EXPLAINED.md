# C1 from sounds to human descriptions and control effects

Updated 9 October 2026. This describes the current repository, separates what is
built from what is proposed, and supersedes older 36-presentation explanations.

C1 asks two linked questions: **How would a listener describe this sound? What
happens to that description when we change a synth control?** Think of a synth
patch as a recipe, audio as the cooked food, and descriptor ratings as people's
judgments of its taste. A recipe number is not itself a human judgment.

## 1. Define the small synth world

The current architecture uses one oscillator with a fixed Basic Shapes wavetable;
oscillators 2/3, noise and effects are off. Filter type, routing, Bend mode and
other architecture choices are fixed. MIDI note is 60, velocity 0.8, note hold
1.5 seconds, render length 3 seconds, mono at 44.1 kHz.

The 13 varying controls are wavetable position, Bend amount, filter cutoff,
resonance, drive, amp attack, decay, sustain, release, and filter-envelope amount,
attack, decay and sustain. Bounds and wrapper mappings are versioned in the
generation profiles. “All sounds” means this declared domain, not every sound
Vital or a musician could make. Bounds are still described as provisional.

Each sound has **one complete combination of all 13 values**. Sixty-four sounds
are 64 combinations, not 13 separate mini-experiments. One control can mask
another: when filter-envelope amount is zero, its attack/decay/sustain cannot
move the cutoff. A parameter can be technically present but inactive in context.

## 2. Generate candidates and select study sounds

The new pool already contains 1,024 Sobol-sampled 13-control patches and renders.
The old eight-control 1,024 pool was a separate generation test. Sobol spreads
combinations through the declared parameter ranges; it is not an exhaustive grid.
[SciPy's Sobol documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.qmc.Sobol.html)
explains why power-of-two sequence sizes preserve its balance properties. A
diversity-selected subset does not automatically retain those guarantees.

The selector checks audio validity and chooses 64 study sounds plus 3 separate
practice sounds. Its diversity measure combines normalized parameter distances
with acoustic summaries of spectral and temporal energy. It is a practical
selection heuristic, not evidence that every interaction or every human rating
value is represented. Min/max cutoff coverage alone cannot establish brightness
coverage. The pilot must show which perceptual regions are present or missing.

The relevant pool is `data/raw/audio/restricted_bend_sustain_v4/`, with parameter
and provenance records in `data/manifests/restricted_bend_sustain_v4.csv`.
The deployable review selection is `survey/deploy/study/bundle.json`.

## 3. Present controlled audio

The pipeline preserves raw FLOAT renders, applies the versioned 10 Hz DC filter
once, and applies constant per-clip gain to match note-on RMS with peak headroom.
It does not use a compressor or added fade. Equal RMS is not guaranteed equal
perceived loudness. These processing choices define what the ratings describe.

Participant `sound_###.wav` files are PCM16. The matching `_features.wav` files
are FLOAT copies of the corresponding processed signal, not additional trials
and not spreadsheets of extracted features. Hashes, gains and original source
IDs let the team join each rating to the exact audio and parameter recipe.
Any alternate feature input must be checked against the playback actually heard.

## 4. Ask people four independent questions

| Descriptor | Plain meaning |
|---|---|
| Brightness | How much treble/high-frequency character? |
| Roughness | How much rapid fluttering, beating or grating texture? |
| Percussiveness | How much like a struck/plucked event with a distinct onset and falling level? |
| Sustainedness | How much of a continuing, held quality after onset? |

Each uses 1 = not at all through 7 = very, plus cannot judge/term unclear. A sound
may have both a strong attack and a sustained body: percussiveness and
sustainedness are not forced opposites. We must check whether listeners
understand and distinguish these candidate descriptors.

After consent and experience questions, the listener sets comfortable volume,
completes a headphone check, hears 3 practice sounds, then rates **20 different
study sounds**, with a break after 10. Full playback is required; replay is
available. There are 80 study trait judgments and 12 practice judgments per person.
The current version has **no repeats**, so it cannot directly estimate whether
the same listener would repeat the same rating on a second presentation.

Assignments overlap between listeners. If the **first 16 assignments** are
completed by 16 distinct eligible people:

- 16 × 20 = 320 sound-listener evaluations.
- 320 / 64 = exactly 5 listeners per sound in that assignment design.
- 320 × 4 = 1,280 individual study descriptor scores before unclear/missing values.
- There are still only **64 distinct labelled audio examples**, not 1,280.

Sixteen is a workload/coverage target, not a demonstrated statistically sufficient
sample size for the final model. Dropouts, unclear answers and arbitrary missing
assignments reduce or unbalance usable coverage. Musicians and singers are in
the proposed practical-experience categories; supervisor confirmation remains
part of the recruitment protocol.

## 5. Use the pilot to improve the main study

Check completion, time, fatigue, comments, unclear answers, rating distributions,
per-sound coverage and between-listener disagreement. Determine whether sounds
span useful parts of each scale and whether descriptor wording needs revision.
Several high brightness ratings do not prove the physically brightest possible
sound was included; these are ratings within a selected study context.

Disagreement is evidence to understand, not a reason to delete inconvenient
listeners. Specify exclusions before analysis; separate withdrawn, incomplete,
replaced, practice and rehearsal records. Unknown ratings are missing numeric
judgments, not zero or neutral 4. Preserve corrections and protocol versions.
Changes to wording or audio require a new version. Pooling pilot and main data
needs an explicit justification; it is not automatic.

The hosted version is currently a **review**, with research-analysis inclusion
disabled. A functioning site is not proof of clearance or a finished main study.

## 6. Convert audio into measurable inputs

For each labelled sound, compute numbers from its waveform. Candidate inputs
include spectral centroid (where spectral energy is concentrated), rolloff,
spectral shape/MFCCs, level and temporal envelope measurements. For onset/body/
tail qualities, preserve how the sound changes over time; averaging the entire
clip can erase the very distinction we want to learn. Roughness-specific
representations must be justified and evaluated, not assumed to equal a generic
noise measure or zero-crossing rate.

**Existing code is only a baseline.** The precision audit found that nearly
silent frames can change centroid/MFCC summaries disproportionately when FLOAT
and PCM encodings differ. The C1 owner must define energy handling/spectral
floors, check stability on the exact study sounds, and document the revision
before model fitting. This can be repaired after the pilot without recollecting
ratings if the heard audio and task remain fixed. A necessary change to the
heard audio is a different matter.

## 7. Learn the relationship between audio measurements and ratings

Create a table with one sound's audio features as inputs and its human judgments
as targets. Retain individual ratings, counts and disagreement. A proposed simple
baseline is a separate regularized regression for each descriptor using a
predeclared aggregation of numeric ratings. Means make an approximate interval-
scale assumption about 1–7 responses; medians/ordinal or listener-aware models
are alternatives to evaluate, not interchangeable choices to hide.

For an inspectable starting model:

`predicted brightness = intercept + weight1 × feature1 + weight2 × feature2 + …`

Training chooses weights to reduce errors against human targets. Regularization
discourages unnecessarily large weights; it does not manufacture evidence.
[Ridge regression documentation](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html)
describes this baseline. This is a recommendation, **not an already fitted or
selected final C1 model**. Feature weights are not causal synth-knob effects.

## 8. Test whether the model predicts genuinely unseen sounds

Keep all ratings, encodings, repeats and related variants of a sound on the same
side of a train/test split. Otherwise the model is partly examined on sounds it
already learned. Group related patch families where appropriate. Learn feature
scaling and tune model choices on training/development data only. Group-based
validation is supported by [scikit-learn's guidance](https://scikit-learn.org/stable/modules/cross_validation.html).

Compare against a training-set average-score baseline. Report errors in rating
units, ranking agreement, uncertainty and failures by descriptor, respecting
shared sounds/listeners. Test new-listener generalization separately if claiming
it. With 64 sounds, conclusions are exploratory and uncertain; a main study may
need more independently labelled sounds, not merely more ratings of the same 64.

If one descriptor cannot be predicted reliably, report that limitation or
redesign it. Do not silently use an unreliable output as ground truth.

## 9. Apply the validated predictor to additional sounds

The large 131,072 corpus can be rendered independently of human ratings using
the accepted generator recipe. Applying a trained C1 model means extracting the
same features from each sound and producing **predicted** descriptor values.
It does not turn the corpus into 131,072 human-labelled examples or improve the
model simply by running it more often.

Assess where the large corpus lies outside the labelled acoustic region; a
shared parameter range is not enough to guarantee perceptual support. Seek
additional human labels for poorly supported regions and retain prediction
provenance/uncertainty. Re-selecting a subset from an unchanged valid corpus is
possible. A changed synth architecture, bounds or rendering/processing policy
may require versioned new renders. The same 1,024-prefix Sobol recipe can extend
to 131,072 by adding 130,048; generation and storage status must be checked before
launching that separate job.

## 10. Investigate what moving a control does

Take a known patch, render it, extract features and predict its four scores.
Move one control by a declared amount, keep the others fixed, render again,
apply the same declared processing policy, and predict again. Subtract the old
scores from the new ones.

Illustrative only: predicted brightness 3.1 before and 4.0 after a cutoff change
gives +0.9 rating units. That says the model predicts an increase for **this
patch and step**, not that a listener certainly hears +0.9 or that cutoff always
has that effect. Finite differences can be divided by the parameter step for
sensitivity; state normalized and native-unit mappings, boundary handling and
step size. Vital's cutoff wrapper units must not be called Hz without conversion.

Repeat across many backgrounds and step sizes. Inspect interactions and inactive
regions, not just an overall average. Use a fixed reproducible renderer and the
same level/DC feature pipeline; the level policy determines whether the result
includes or controls away overall level differences. Don't compare the old
unprocessed signal with a newly normalized perturbation.

Finally, ask humans about selected original/changed pairs. Good absolute-score
prediction does not by itself establish accurate small-change prediction. Report
predicted parameter effects separately from human-confirmed effects, particularly
when changes are small relative to model error. The 64 survey sounds need not
contain all these exact perturbation pairs; they can be generated later.

## Deliverables and responsibilities

C1 should deliver a versioned human-rating dataset, validated feature definitions,
a tested descriptor predictor, parameter-effect analysis and human validation of
selected changes, with explicit limits. A proposed output for one patch is four
predicted qualities plus evidence about which tested control changes increase or
decrease them. A universal automatic editing system is not established by this
pipeline alone.

Survey preparation supplies the frozen audio and mapping, questionnaire,
assignments, exports and quality-control audit. The C1 owner is responsible for
descriptor decisions, feature repair, modelling, validation and interpretation.
The team agrees shared synth/audio conventions. C2 estimates synth settings and
certainty; C3 finds alternative patches; C4 collects overall similarity judgments.
Neither C2/C3 having a large synthetic corpus nor C4's separate comparisons
automatically validates C1's descriptors.

**Built:** candidate pool, 64+3 selection, review survey and saving/export flow.
**Still required:** final clearance/protocol, formal pilot and analysis, main-study
design, feature repair, fitting/testing and perturbation validation. The old
analysis coverage check assumes eight listeners per sound and the research-export
inclusion rule recognizes an older production ID. Adapt and test those for the
approved 20-sound production version; never relabel review records to bypass them.
