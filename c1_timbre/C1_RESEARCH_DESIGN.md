# Component 1: resolved research design

Reviewed 26 September 2026 against the supplied discussion, the current repository, and the primary sources linked below.

**Recommended title: Human-validated analysis of Vital parameter effects on perceived timbre.**

**Main question:** Within a defined Vital configuration, how do selected control changes affect perceived timbre, and how do those effects depend on the other control settings?

This document resolves the research design. It does not report a completed perceptual study, a trained perceptual model, or an approved change to the submitted proposal. The supplied discussion contains incomplete excerpts, so the exact submitted C1 wording and complete intended 16-control list remain unverified. Until clarified, retain 16 controls as the intended scope and use the implemented eight-control configuration for development.

## 1. The decision

C1's main deliverable is a **parameter-effect map with evidence and limits**: which control changes affect which traits, in which contexts, and whether listeners support selected findings.

Use a small listening study to establish whether a measurement method works on the actual Vital sounds. Then use controlled synth renders to measure effects across multiple contexts. Check the primary effect and interaction claims with listeners. Existing timbre predictors are candidate measurement tools; fitting a new predictor is a conditional fallback. A large rendered corpus supports exploration but is not a prerequisite for every C1 experiment.

The two distinct operations are:

1. **Measurement:** audio -> measured acoustic features or predicted perceptual traits.
2. **Experiment:** deliberately change a synth control -> render the resulting audio -> measure the change -> check selected changes with listeners.

The second operation answers C1. A second learned model from parameters to predicted traits can summarize a large corpus, but it is optional. Directly rendering interventions already lets us examine control effects without adding another model's approximation error.

The measurable research questions are:

1. Which candidate measurements predict listener ratings and listener-rated changes on held-out Vital examples better than simple baselines?
2. How much do selected control effects vary across the declared parameter contexts?
3. Do listeners support the primary interaction contrasts, and where do model predictions disagree with them?

This makes the comparison of **predicted changes against heard changes** a central result. Reproducing a familiar cutoff/centroid correlation alone would not answer these questions.

## 2. What was tangled in the discussion

| Issue | Resolution |
|---|---|
| Building a timbre predictor became the whole component | Treat it as an instrument used by C1; evaluate or adapt it only as needed. |
| Existing models were treated as ready-made Vital perception labels | Test transfer on actual Vital clips and on differences between clips. Availability and suitability are separate questions. |
| 120, 150, 160 and 256 sounds were successively presented as sufficient | These are budgets, not established sample-size requirements. Use pilot variance, precision or power planning, and learning curves when training is needed. |
| 135,000 machine-labelled sounds were used to justify perceptual coverage | Computational density does not create more independent human evidence or repair predictor bias. |
| Perturbations were alternately mandatory for everything or almost discarded | Use systematic controlled renders on a sampled set of contexts; use a smaller, separately planned listening experiment for primary claims. |
| Global SHAP/dependence plots were described as measured perceptual effects | They describe a fitted model. Controlled renders measure changes in audio or model output. Listener responses provide perceptual evidence. |
| A knob affecting timbre was taken to imply recoverability from audio | Sensitivity and inverse identifiability differ. Multiple settings can produce similar sounds. C2 must evaluate recovery itself. |
| Four existing survey scales and five proposed traits were mixed together | Version and freeze a new instrument after piloting its wording. Do not reinterpret old responses as new traits. |

## 3. What the literature supports

TTP-RANE uses a frozen embedding and a shallow head. Its labels describe imagined instrument archetypes and are assigned by instrument class. The reported `r = .663` pools 620 instrument-by-trait averages; it is not a within-Vital, individual-clip accuracy result. The `.698` human-to-mean comparison is not a demonstrated hard upper bound for predicting population means. My methodological conclusion is that transfer and sensitivity to knob changes require separate evidence. The paper links a companion page, but a runnable checkpoint and its reuse conditions could not be verified in this review. Reusing its architecture does not itself supply trained weights. [Chasle Cauchy et al., 2026, sections 2.1, 2.6 and 4](https://arxiv.org/html/2606.30369v1)

Parameter-to-timbre mapping also predates this paper. TSAM analyzes changes in synthesis controls using audio descriptors and builds timbre-space mappings. Therefore, moving from timbre prediction to parameter mapping does not automatically establish novelty. [Fasciani, TSAM, 2016](https://stefanofasciani.com/2016/04/10/timbre-space-analyzer-mapper/)

A study of subtractive synthesis constructed a perceptual space from listener dissimilarity ratings for 15 selected sounds. It supplies relevant precedent, but its sample size does not justify a predictor over a much wider parameter domain. [Vahidi et al., 2020](https://arxiv.org/abs/2009.11706)

Audio Commons already provides models for brightness, roughness and warmth, among other attributes. Its repository is explicitly unmaintained; the models are still candidates to benchmark, subject to a reproducibility check and Vital-specific validation. [Audio Commons implementation](https://github.com/AudioCommons/timbral_models)

**Defensible proposed contribution:** a reproducible empirical study of selected Vital control effects and interactions, comparing acoustic measurements and candidate perceptual predictors against direct listener evidence, and identifying where those measurements work or fail. This is a candidate incremental contribution, not a verified claim to be the first such study. A focused comparison with the closest work is still needed for the proposal's novelty argument.

## 4. Current repository evidence

| Item | Verified state on review date | Consequence |
|---|---|---|
| Shared manifest and audio | 1,024 manifest rows; all 1,024 referenced WAV files exist | This is the available development corpus, not 135,000 sounds. |
| Varied controls | Eight: wavetable position, cutoff, resonance, filter drive, attack, decay, sustain and release | Additional controls need a versioned schema and rendering validation. |
| Fixed context | MIDI 60, velocity 0.8, note held 1.5 s, render 3 s; one oscillator and fixed filter setup | Findings cannot automatically generalize to other notes, articulations or synth architectures. |
| Existing C1 output | 128 feature rows and a 128-sound cutoff/centroid summary | Historical checkpoint output; not a result over the current 1,024-sound corpus. |
| Historical association | Pearson `r = 0.5197`, `R² = 0.2701` | Acoustic association, not listener validation or an isolated intervention. |
| C1 survey | 20 clips/session, four bipolar scales | Internal prototype; does not implement the proposed formal design. |
| Quality summary | 158 DC-offset warnings; RMS levels span roughly -51 to -16 dBFS | Resolve presentation processing before collecting perceptual judgments. |
| Learned perceptual pipeline | No trained perceptual predictor or its validation results found in C1 | Do not describe transfer, training or human validation as completed. |

Evidence: [manifest](../data/manifests/pilot_v1.csv), [frozen generation configuration](../data/manifests/pilot_v1_config.json), [generation summary](../data/manifests/pilot_v1_summary.json), [C1 summary](outputs/cutoff_vs_centroid_summary.csv), [survey configuration](../survey/config/c1_descriptors.json).

The current generation source has a default count of 100, while the saved manifest/configuration records 1,024. Use the saved configuration to describe this corpus and record explicit generation arguments for future versions. Do not infer a dataset's size from a mutable default.

## 5. Component boundaries

| Component | Question | C1's relationship to it |
|---|---|---|
| C1 | What changes perceptually when controls change, and in which contexts? | Owns descriptor validity, control-effect experiments and the resulting map. |
| C2 | Which settings can be estimated from an input sound, and with what accuracy? | May use C1 findings to interpret weak controls; C1 is not proof of recoverability. |
| C3 | Which candidate patches should be recommended? | May consume validated C1 tags and explanations; retrieval and ranking remain C3. |
| C4 | Does an audio-similarity measure agree with listeners? | Owns general similarity judgments. A C1 pair asks about a named trait or trait change, not overall similarity. |

No component should claim that a C1 trait vector is already a validated general perceptual distance.

## 6. Traits and listening presentation

My recommended starting instrument has **three primary candidate traits**: brightness, roughness and percussiveness. Warmth and sustainedness can be exploratory candidates if they are required by the proposal or prove useful in the pilot. Do not promise that all five will survive validation. In the present restricted synth configuration, some traits may have too little audible variation to support useful analysis.

Use separate unipolar 1–7 scales, from 'not at all' to 'very', with short definitions and practice examples. Exact wording is a pilot decision, not an already validated questionnaire. In particular:

- Thin and warm are not established opposites in this project.
- Clip length, an abrupt attack, a sustained body and a release tail are different properties. All current clips last three seconds, so 'short' needs much clearer meaning.
- A sound can have a percussive onset and a sustained body; do not force these into one bipolar scale.
- Keep a predictor's native labels. TTP terms such as 'sparkling/brilliant' or 'raspy/grainy' are not automatically interchangeable with brightness or roughness. Either rate the exact native term or fit and validate a separate mapping. [TTP trait definitions](https://arxiv.org/html/2606.30369v1#S2.SS1)

For the primary timbre study, use a fixed, documented presentation-level policy and preserve the amplitude envelope. Choose the gain procedure during the pilot, audition its results, retain raw files, and save per-file processing/gain metadata. RMS normalization is not proof of equal perceived loudness. Avoid compression or limiting that alters the trait being studied. Investigate DC removal and tail truncation; apply any agreed processing identically to human playback and predictor input.

Level matching defines the experiment: effects concern the sound after that presentation processing. If natural output level is a research question, evaluate it separately. Do not quietly alternate between raw and adjusted renders. Fix pitch, note duration, velocity, synth version, preset, phase/reset behavior and effects routing for the main experiment. Testing across pitch would be a separate extension.

## 7. A staged method that can actually finish

### A. Freeze the experimental domain

Document each included control, type, valid range, native display value, required routing and whether it is active in the chosen configuration. An inactive control producing no effect is not evidence that listeners cannot perceive that control in general. Keep categorical/discrete controls separate from continuous finite-difference tests.

Use the eight-control pilot to exercise the procedure. Keep the intended 16-control study conditional on supplying and validating the missing control definitions. Do not invent them from scattered examples in the discussion.

### B. Validate a measurement method on Vital

Select a reproducible set spanning parameter settings and acoustic diversity, plus an independently sampled validation set from the declared target distribution. Include plausible weak-effect regions; do not select only examples a model already predicts confidently. Record inclusion/exclusion rules and coverage.

Compare a small, predeclared set of candidates:

1. Mean-rating baseline and simple acoustic features with a small calibrated regressor. Add temporal envelope features for percussiveness; the current average spectral features alone are not sufficient to assume that trait is covered.
2. Applicable existing perceptual models, including Audio Commons or TTP-RANE if runnable weights and suitable output labels are obtained.
3. Only if needed, frozen audio embeddings with ridge regression or another small regularized head trained on Vital listener ratings.

Training a head is not training an audio foundation model from scratch. Do not force a single candidate to win for every trait.

Use development data for wording, method choice, feature scaling, calibration and hyperparameters. Freeze these before final validation. Split by sound and, for related variants, base-patch family. Never split individual ratings of the same sound between model training and testing. Keep near-duplicate variants together under a documented grouping rule. If claiming generalization to new listeners as well as new sounds, use a separate listener group for the final evaluation.

Report per-trait MAE, rank/linear correlation, mean-baseline improvement, rating distributions and listener agreement with uncertainty. Do not rely on a correlation pooled across traits. Estimate reliability for the actual incomplete rating design, for example with a crossed sound/listener model; avoid applying a fully crossed ICC formula indiscriminately. Ratings from different people on the same sound improve its label estimate but do not create additional unique training sounds.

Before final data collection, set a tolerable error in rating units and the precision needed for the intended effect sizes. Use pilot variance and a mixed-effects simulation or precision calculation to choose the final sample size. There is no universal '.6 correlation means valid' rule. Also test whether predicted **differences** agree with perceived differences: good absolute ratings need not imply accurate local changes.

**Failure rule:** if a trait fails validation, do not scale it as a valid perceptual label. Calibrate using development data and obtain fresh final validation, collect more labels, drop the trait, or finish a narrower direct-listening study. A failed transfer is a reportable finding; it need not trigger a much larger model project.

### C. Measure controlled effects

For a continuous control, define a study-range coordinate `q` in `[0,1]`. Convert it to the configured Vital range `[a,b]` by `a + (b-a)q`. This is different from treating every restricted Vital range as the full native `[0,1]` range.

For a base context `c`, render two settings of control `i`, holding everything else fixed. If `S` is the renderer and `g_d` the frozen measurement for trait `d`, measure:

`Delta(i,d,c) = g_d(S(c, q_i_high)) - g_d(S(c, q_i_low))`.

Save the actual step and both native settings. A provisional development step is 0.10 of the allowed range on either side of an interior base value; compare a second step size as a robustness check. Do not silently clip endpoints and still describe the step as symmetric. Use separate boundary cases or divide by the actual distance when reporting a slope. These are finite changes, not exact derivatives.

An illustrative computational screening budget is 64 base contexts, each with two variants for each continuous control:

- Eight controls: `64 + 64 x 8 x 2 = 1,088` renders including bases.
- Sixteen controls: `64 + 64 x 16 x 2 = 2,112` renders including bases.

These are feasibility examples, not statistically justified final context counts. Increase or change the design when effect estimates are unstable. Account for synth randomness by controlling seeds/phase or using replicated renders. Log silence, clipping and other failures rather than removing inconvenient cases without reporting them.

For an interaction between controls `i` and `j`, use a matched 2 x 2 design. Keep all remaining controls identical and compare:

`Interaction = [trait(i_high,j_high) - trait(i_low,j_high)] - [trait(i_high,j_low) - trait(i_low,j_low)]`.

Repeat across independent background contexts. A single interaction context requires four renders. Changes in effect between unrelated patches are insufficient to isolate the interaction with `j`.

Predeclare a small number of primary hypotheses. Suggested candidates for the current architecture are cutoff x resonance on brightness and attack x sustain on percussiveness. The expected directions remain hypotheses. Screen other relationships as exploratory, including weak and null regions; 16 controls imply 120 possible pairs, which should not all become human-study primary claims.

### D. Human-check the primary effects and interactions

Use fresh matched examples and listeners who do not see control names or model predictions. Counterbalance A/B order. Ask about a named trait and the signed magnitude of the difference, with a no-change option. A preference or general-similarity question cannot answer this question.

For the interaction test, compare trait-change magnitude across both levels of the context control. Merely confirming the same direction for two pairs does not establish an interaction.

Analyze listener responses with sound/context and participant dependence accounted for. Report effect sizes and intervals, the smallest effect considered meaningful, and the planned multiplicity treatment. An insignificant result does not prove no effect; equivalence needs a predefined margin and sufficient precision. Validate preregistered contrasts or use fresh confirmatory contexts after exploration. Only show surprising examples as exploratory demonstrations if they were selected after seeing the results.

### E. Extend to the large corpus if useful

After validation, score the available shared corpus with the frozen measurement method. Keep human ratings, acoustic measurements and predicted ratings in separate fields. Mark out-of-support regions and failed traits; a 16-control corpus may fall outside the domain validated using eight controls.

A parameter-to-score surrogate, dependence plots or SHAP can summarize this surface, provided surrogate accuracy is checked on held-out renders. Label its conclusions as model-based. Avoid treating thousands of predictions as independent human observations or reporting tiny perceptual p-values based on that count. Carry the measurement model's limitations into every map.

Do not perturb every large-corpus patch. At 135,000 patches and 16 controls, two variants per control would require 4,320,000 additional renders. The controlled context sample is the manageable experiment; the large corpus is optional additional coverage. A Sobol sampling sequence alone is not a completed Sobol sensitivity-index experiment.

## 8. One coherent planning budget

The following is a **provisional, arithmetically balanced budget**, not a power result or recruitment instruction. Recalculate it after the pilot. Use different participants between stages in this example.

| Stage | Unique study items | Participants | Scored items per participant | Ratings per item |
|---|---:|---:|---:|---:|
| Wording/method pilot and development | 64 individual clips | 16 | 32 clips | 8 |
| Frozen-method validation | 128 new individual clips | 32 | 32 clips | 8 |
| Primary effect/interaction verification | 32 comparison pairs | 24 | 16 pairs | 12 |

The arithmetic is `16 x 32 = 64 x 8`, `32 x 32 = 128 x 8`, and `24 x 16 = 32 x 12`. Assignment must be balanced in the study schedule; unconstrained random draws do not guarantee those counts. Dropped or incomplete sessions also change the achieved counts.

One possible allocation of 32 pairs is two interactions x eight background contexts x two context levels. That entails 16 four-render interaction sets, hence 64 rendered clips. For each participant, assign both context-level comparisons for each allocated background context, without exposing the hypothesis or fixing presentation order. Twelve listeners per pair does not make eight background contexts into 96 independent contexts; the pilot may show that more contexts are needed.

At three traits, a 32-clip session contains 96 scalar ratings; at five traits, 160. A 16-pair verification session has 32 clip presentations and 16 comparison responses if each pair tests one designated trait. Replays, practice, headphone checks and repeat trials add time or presentations and must be counted in the final participant information. Measure completion time in the pilot instead of promising a duration.

This example uses **72 distinct people overall** and 192 individually rated clips, plus 64 clips in the interaction sets. No person is assigned all stages. Reusing people reduces unique recruitment but adds sessions and creates dependence that must be recorded.

The plan is most economical if an existing method can be frozen after the pilot. If fitting on 64 development clips is inadequate, expand development deliberately; keep the final validation set untouched. The 128 validation clips cannot be used to select a model and then still be reported as its untouched final test. If the questionnaire changes after the pilot, pilot ratings are not automatically compatible training labels.

## 9. Deliverables and completion criteria

The final package should contain:

- A frozen synth domain, trait definitions and preprocessing specification.
- Versioned listening assignments, ratings, exclusions and reliability estimates.
- A candidate-measurement comparison with held-out per-trait validation and explicit failed traits.
- A paired-render manifest recording base context, changed controls, actual settings, audio hashes, processing, model version and support flags.
- An effect table with control, trait, context, step, estimated change, uncertainty method and evidence type.
- Matched interaction plots and direct-listener results for the primary claims, including disagreements and null/uncertain outcomes.
- Optional corpus tags and a simple query such as 'what effect is supported for this control in this region?'. An inverse-control optimizer is outside the core scope.

Use explicit evidence labels: **acoustic measurement**, **model-estimated trait change**, and **listener-supported trait change**. Human evidence supports the tested domain and contrasts; it does not certify every predicted cell in a large map.

An experiment can finish with negative results. If prediction fails, a bounded direct-listening study of selected controls/interactions still answers a narrower C1 question. Do not call the component complete simply because a predictor ran over many files.

## 10. Immediate work in order

1. Confirm the submitted scope and complete 16-control list; preserve the eight-control pilot as the development baseline.
2. Freeze the candidate traits and resolve DC, presentation level and tail-duration handling.
3. Implement a versioned listening manifest and balanced assignments; the current 20-clip/four-scale prototype is not the formal instrument.
4. Run the small wording and measurement pilot, including controlled-change examples.
5. Use its results to fix hypotheses, sample size, success criteria and the frozen method. Follow the project's existing participant-approval process before recruitment.
6. Collect untouched validation and the matched effect/interaction study; expand only where its evidence justifies expansion.
7. Generate the evidence-labelled map and optional larger-corpus predictions.

The current feature script remains useful as an acoustic baseline. Its whole-clip feature averages include padded/silent frames and lack explicit onset/body/tail summaries. For the formal study, document the frame policy and add the temporal information needed by the chosen traits. Do not rename spectral centroid as a measured human brightness rating or present RMS as perceptual loudness.
