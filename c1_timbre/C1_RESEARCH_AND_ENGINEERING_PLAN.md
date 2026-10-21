# Full C1 research and engineering plan

14 October 2026. This describes the whole research component, rather than just
the implemented scripts. Recommendations are proposals; they are not claims that
models, feature repairs or human validation have already been completed.

## Purpose and research questions

C1 connects audible sound qualities to synthesizer controls. Given a sound, it
should estimate how listeners describe it. Given a known patch and a control
change, it should estimate how those descriptions change, then test selected
estimates with people.

Three research questions follow:

1. Can listeners understand and use the proposed descriptors consistently in
   the declared synth domain?
2. Can audio measurements predict their judgments for unseen sounds?
3. Can differences between predictions correctly describe the direction and
   useful magnitude of changes caused by moving synth controls?

The proposed descriptors are brightness, roughness, percussiveness and
sustainedness. They are candidates to investigate, not four established
independent perceptual axes. C1's contribution is the evaluated connection
between judgments, audio and control changes. A cutoff/centroid correlation
alone would be a preliminary measurement, not that entire contribution.

## Domain and shared corpus

The declared world is one Vital Basic Shapes oscillator with a fixed wavetable,
filter type, routing, Bend mode and other architecture settings. Oscillators 2/3,
noise and effects are off. MIDI note 60, velocity 0.8, mono 44.1 kHz, 1.5-second
note hold and three-second recording are fixed.

The 13 varying controls are:

- Wavetable position and Bend amount.
- Filter cutoff, resonance and drive.
- Amp attack, decay, sustain and release.
- Filter-envelope amount, attack, decay and sustain.

The full 131,072-sound v4 corpus was generated and verified on the reference PC.
Its first 1,024 combinations include the v4 study-candidate pool. The old
eight-control `pilot_v1` engineering dataset is separate.

Every corpus row contains one combination of all 13 controls and its rendered
audio. Parameter Parquets are genuine generating-control labels. They contain
no human timbre ratings. The large corpus supplies audio for engineering,
candidate selection and later prediction; it does not supply 131,072 perceptual
training targets.

The exact restricted ranges and native-unit mappings are in
[PARAMETER_UNITS.md](../generation/PARAMETER_UNITS.md). For example, current
base cutoff is nominally about 119–6,959 Hz before envelope modulation. The
cutoff control uses a pitch coordinate; it must not be described as uniformly
sampling every Hz from 20 to 20,000. The reproduction recipe is frozen even
though its historical metadata calls these bounds provisional.

## Human study and target labels

| Descriptor | Intended question |
|---|---|
| Brightness | How much high-frequency or treble character is audible? |
| Roughness | How much rapid fluttering, beating or grating texture is audible? |
| Percussiveness | How strongly is there a struck/plucked onset followed by falling level? |
| Sustainedness | How strongly does the sound continue with a held quality after onset? |

A strong attack can coexist with a sustained body. Percussiveness and
sustainedness should not be coded as obligatory opposites. Roughness should not
be defined as distortion amount or generic noisiness. Test whether this
one-oscillator domain actually contains enough variation for each descriptor.

Current proposed pilot: 64 study sounds, three separate practice sounds,
20 unique study sounds per participant, four 1–7 ratings per sound, an unclear
option and a break after ten study sounds. There are no within-session repeats.

The first 16 distinct, eligible, completed assignments supply 320 sound-listener
evaluations and five listeners per sound. There are 1,280 study descriptor scores
before unclear/missing values, but only 64 distinct labelled sounds. Individual
listeners rate several sounds, and each sound is rated by several listeners;
these observations are not all independent. The assignment must be completed
as designed to obtain the balanced coverage.

This is a workload/coverage target, not a statistical proof of model adequacy.
The pilot should assess wording, unclear responses, fatigue, completion, usable
scale ranges, target disagreement and preliminary predictive feasibility.
Current absence of repeats prevents a within-listener test-retest estimate.
Practical music experience may include instrumentalists and singers, under the
eligibility definition the supervisor approves.

For a later main study, an approximate workload equation is
`participants = ceil(unique_sounds * listeners_per_sound / sounds_per_person)`.
At 20 sounds per person and five listeners per sound, 64/128/256 sounds require
16/32/64 completed people respectively, with a suitable balanced assignment.
These are planning examples, not justified final sample sizes. Use pilot noise,
learning curves, perceptual gaps and recruitment feasibility to choose the main
design. More listeners improve existing targets; more distinct sounds broaden
the labelled acoustic examples. The existing 64-sound assignment code does not
automatically support a 128- or 256-sound design.

Preserve individual ratings and missingness. For a first baseline, a per-sound
mean of valid numerical ratings is a transparent target, with an explicitly
stated approximate interval-scale assumption. Store count and spread alongside
it; compare medians or an ordinal/listener-aware approach as a robustness check.
An unclear judgment is missing, not 0 or 4. Do not pool changed protocols or
turn rehearsal records into approved research responses retrospectively.

## Audio, features and the predictor

Write the processing chain explicitly:

`patch -> render -> declared audio processing -> measured features -> predicted ratings`

Training uses the exact study signal and human ratings joined by stable source
IDs. The study applies DC conditioning once and recorded constant gain per clip
with peak headroom. PCM16 playback and corresponding FLOAT analysis copies are
encodings of that study signal. Equal RMS is not proof of equal perceived
loudness. Full-corpus raw masters only get DC conditioning from the audio adapter;
study level matching is an additional step. Specify a compatible level policy
for future inference and perturbations rather than silently changing it by batch.

Candidate feature families include spectral energy distribution, centroid,
rolloff, spectral shape/MFCC summaries, temporal envelope/attack measurements,
early/body/tail energy ratios and justified roughness-specific measures. A
whole-clip average alone can erase attack/body differences.

The current extractor is a baseline with a documented problem: extremely quiet
frames and spectral bins can disproportionately affect centroid/MFCC summaries.
The audit found a maximum 760 Hz centroid difference between selected FLOAT and
PCM16 study copies under that extractor. This is numerical feature instability,
not proof that listeners hear different brightness. Specify energy handling,
spectral floors, temporal summaries and numerical tests before relying on it.
Keep useful quiet tails; a blanket deletion rule could erase sustainedness cues.
Changing feature definitions preserves ratings if the heard audio remains fixed.

For an inspectable first model, fit one regularized regression per descriptor:

`predicted score = intercept + sum(weight_k * standardized_audio_feature_k)`.

Ridge regression minimizes squared target error plus a penalty on large weights.
Fit feature scaling and model selection using training data only. Compare against
a training-set mean predictor. Use a compact, justified feature set, then compare
one nonlinear alternative if real held-out performance warrants it. Do not
assume a large neural network is appropriate for 64 labelled sounds. A parameter-
to-rating model can be a comparator for known patches; an audio-based predictor
is needed when the input sound's true parameters are unknown.

Evaluate by held-out sounds, keeping all ratings/encodings/related variants of a
source sound together. Group related patch families where needed. Hyperparameter
selection and final evaluation must be separated. Listener generalization is a
separate claim requiring its own evaluation.

Report descriptor-wise absolute error in score units, ranking agreement,
baseline improvement, uncertainty and failures across acoustic regions. Check
range compression and constant targets; correlation cannot rescue a descriptor
with no useful variation. Ridge predictions can exceed 1–7, so any bounded
display/calibration rule must be explicit and included in evaluation. Human
disagreement and model uncertainty are distinct quantities.

## Using the model across the large corpus

Apply the validated feature/prediction pipeline to the 131,072 sounds. Store
predictions with model, feature, audio-policy and label-source provenance.
They are model predictions, not newly collected human labels. Running inference
on many sounds does not improve a predictor trained on a small labelled set.

Check how new audio compares with labelled feature regions. Where support is
weak, flag the prediction and select additional human examples. Feature-distance
flags are useful diagnostics, not guaranteed calibrated confidence. Additional
survey subsets can be selected from the existing corpus when its architecture
and rendering remain appropriate. New architecture/processing policies require
separate versions and may require new renders.

Sobol gives a low-discrepancy numerical design; it does not guarantee a uniform
human descriptor distribution. Report separate parameter, acoustic and observed
perceptual coverage. The 64 selected sounds are a diversity subset and do not
inherit the full sequence's balance guarantee. State the observed ranges and
held-out errors instead of claiming the entire continuous 13D space is covered.

## Parameter effects and human validation

For a known patch theta, define
`g(theta) = predictor(features(processing(render(theta))))`.
Change only control j, within the declared bounds, and calculate
`effect_j = g(theta_changed) - g(theta)` for each descriptor.

For example, 3.1 before and 4.0 after gives a predicted brightness increase of
0.9 score units. This is illustrative, not a measured result. Divide by the
declared step to obtain a sensitivity if needed. State whether the step is a
fraction of the restricted range, an actual normalized value, or a native unit.
Respect boundaries and test several backgrounds/step sizes.

The result is a local 13-by-4 control/descriptor effect table. It is conditional
on the patch, processing and model. At zero filter-envelope depth its timing
controls are inactive; at envelope sustain 1 its decay can be inactive. These
contexts must be represented rather than hidden by an overall average. An audio
feature regression coefficient is not a causal synth-control coefficient.

Validate selected original/changed pairs with listeners: include predicted
increases, decreases, negligible effects and weaker-support cases; vary patch
backgrounds; randomize presentation order; check perceived direction/magnitude.
Accurate absolute ratings do not automatically establish accurate small-change
predictions. Report computational predictions and human-confirmed effects
separately. C1's timbre effects differ from C2's inversion/certainty diagnostics,
although they can share rendering infrastructure.

## Engineering with dummy data while approval is pending

Yes: use the real synthetic audio/parameter corpus and clearly fabricated survey
records to build the machinery. The physical synth labels are genuine. Simulated
listener ratings are engineering fixtures, not perceptual evidence.

Use three stages:

1. **Schema/flow fixtures.** Fake IDs such as `SIM_P001`, the real assignment
   structure and sound mapping, four dummy responses, timestamps and explicit
   completion/withdrawal/rehearsal states. Exercise joining, saving/export,
   corrections, unclear values, partial sessions and malformed records.
2. **Learnable toy targets.** Choose a documented artificial function of audio
   features, then add reproducible listener offsets and noise and discretize to
   1–7. For example, a centroid-based toy brightness target can test training and
   prediction. It does not establish that people use that rule. Test several
   noise/disagreement/missingness cases rather than one perfect simulation.
3. **Negative controls.** Shuffle targets, remove informative features and use
   constant/noise-only targets. Check that evaluation does not falsely report
   meaningful prediction and that uncertain/undefined metrics are handled.

Keep dummy records in a separate database/output directory and a separate study
ID; record `label_source=synthetic_proxy` or `simulated`, generator version and
seed. Demo model outputs and reports must visibly state their origin. Never mix
them into the approved human-label training/evaluation table or count them as
participants. Existing review records also remain separate under their original
status; calling a session a dummy study does not change genuine human data into
simulated data.

With dummy targets the teammate can build loaders, features, target aggregation,
splits, model fitting/saving/loading, metrics, plots, inference, control-effect
experiments and integrations. Predicted dummy score changes only establish that
software applies the chosen artificial rule; they do not validate perception.
There is no need to fabricate descriptor labels for all 131,072 to achieve this.

After approval and the real pilot, reuse the engineering pipeline but replace
dummy targets, refit preprocessing/model parameters and evaluate with real
held-out human labels. Do not retain the dummy-trained predictor as the final
validated C1 model. Unlabelled-audio pretraining is a possible later experiment,
with independent evaluation and declared partition rules; it is not needed to
start the recommended baseline.

SLIIT's published process starts with preliminary supervisor review and, where
formal review is required, instructs researchers to await the ERC decision.
Continue synthetic/software engineering while the study's applicable approval
is pending; formal human collection follows the documented outcome.

## Suggested work order and deliverables

Before approval: verify shared labels/audio; repair and version the features;
build isolated dummy-response fixtures and a compact baseline pipeline; implement
sound-grouped evaluation and control-effect calculations; finish the study
documents and production-version/export compatibility. Keep the existing survey
stimuli fixed unless a genuine playback problem requires a new version.

After approval: run the formal pilot; analyze wording, coverage, disagreement,
fatigue and exploratory prediction; choose the main design with evidence; collect
and evaluate real labels; extend predictions with support diagnostics; validate
selected control effects with people.

C1 should deliver a versioned human-rating dataset, exact stimulus/source mapping,
stable feature specification, saved predictor/preprocessing/splits, evaluation
report, local control-effect analysis, human validation and declared limitations.
The survey preparer supplies presentation/export/provenance machinery; the C1
owner handles feature definitions, modelling and scientific interpretation. The
team agrees shared rendering, processing and partition conventions.

The old analysis currently expects eight listeners per sound and the research
export recognizes the historical production ID. An approved 20-sound production
version must update/test that compatibility explicitly, preserving exclusion of
review records. Hosting success alone does not perform that transition.

## Backing

- [McAdams, Beauchamp and Meneguzzi (1999)](https://www.mcgill.ca/mpcl/files/mpcl/mcadams_1999_jasa.pdf): empirical evidence that spectrotemporal simplifications can affect timbre discrimination; it does not validate this exact four-descriptor survey.
- [SciPy Sobol documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.qmc.Sobol.html): numerical sampling and balance properties, including the warning on thinning.
- [Ridge documentation](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html): proposed regression baseline.
- [scikit-learn leakage guidance](https://scikit-learn.org/stable/common_pitfalls.html) and [GroupKFold](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GroupKFold.html): training-only preprocessing and grouped evaluation.
- [Judd, Westfall and Kenny (2012)](https://torwager.github.io/ComputationalFoundations/_downloads/62ec54e758b3f7a9fef871892b6c48db/Judd_Westfall_Kenny_2012_JPSP.pdf): accounting for participants and stimuli, rather than treating every rating as independent.
- [SLIIT Ethics Review Process](https://elibrary.sliit.lk/Ethics%20Review%20Process%20%281%29.pdf): institutional review stages.
- [Local feature precision audit](../generation/characterization/pcm_precision_v1/REPORT.md): evidence for the existing feature-stability challenge; historical statements in that report precede completion of the full corpus.
