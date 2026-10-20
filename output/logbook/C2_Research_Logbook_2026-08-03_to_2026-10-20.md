# C2 Research Logbook

Audio to synthesizer parameter estimation and reliability calibration

Student name: ____________________________
Student ID: IT23203280

Record period: 03 August to 20 October 2026
Compiled: 20 October 2026

Entries group related work by date. Weekly review comments and signatures are completed by the reviewer using the actual signing date.

## Week 1   03 to 09 August 2026

Initial setup and audio generation

### 03 Aug

Set up the Python environment, repository and Vital/Vita rendering tools. Investigated the initial Vita compatibility issue.

Result: Established the first working route for generating synthesizer audio.

### 04 Aug

Generated and validated the initial 1,024-sample pilot. Checked mono output, file count, sample rate and duration.

Result: Saved an initial dataset and validation outputs for pipeline development.

### 06-07 Aug

Reviewed the first audio examples and the generation settings. Listed sound-quality issues to investigate.

Result: Made audio quality and consistent rendering the immediate priorities.

### Weekly outcome

The initial generator and pilot were available for further technical checks.

### Next step

Check audio consistency and the relationship between recorded settings and sound.

### Weekly review

Reviewer comments: ____________________________________________

_____________________________________________________________

Reviewed by: __________________    Role: Supervisor / Co supervisor

Signature: ____________________    Date actually signed: ____ / ____ / ______

---

## Week 2   10 to 16 August 2026

Basic audio checks and parameter records

### 10-11 Aug

Reviewed WAV handling, mono conversion and note timing. Checked that each clip had a corresponding parameter record.

Result: Clarified the inputs and labels needed for later model training.

### 13 Aug

Reviewed possible clipping, quiet output and incomplete release tails in generated audio.

Result: Separated audio-generation concerns from later model-performance concerns.

### 16 Aug

Reviewed the first two weeks of setup and pilot work. Collected the main issues and settings in project notes.

Result: Kept a short list of diagnostics needed before expanding the pipeline.

### Weekly outcome

The audio checks and parameter-record requirements were clearer.

### Next step

Make the rendering and validation process easier to repeat.

### Weekly review

Reviewer comments: ____________________________________________

_____________________________________________________________

Reviewed by: __________________    Role: Supervisor / Co supervisor

Signature: ____________________    Date actually signed: ____ / ____ / ______

---

## Week 3   17 to 23 August 2026

Rendering consistency and dataset organisation

### 17-18 Aug

Reviewed the eight pilot controls and their allowed ranges. Kept the note, velocity and recording duration fixed.

Result: Reduced avoidable variation between examples.

### 20 Aug

Reviewed file naming, sample identities and the manifest used to link audio with synthesizer settings.

Result: Established a consistent basis for selecting and loading examples.

### 21-23 Aug

Checked the first-version workflow and documented the remaining generation and storage issues.

Result: Prepared the pilot workflow for repeatable preprocessing and training.

### Weekly outcome

The first version had a clearer generation recipe and dataset structure.

### Next step

Finish storage and progress tracking, then run the initial estimation baseline.

### Weekly review

Reviewer comments: ____________________________________________

_____________________________________________________________

Reviewed by: __________________    Role: Supervisor / Co supervisor

Signature: ____________________    Date actually signed: ____ / ____ / ______

---

## Week 4   24 to 30 August 2026

Pilot stabilisation and first estimation baseline

### 24 Aug

Updated pilot storage to PCM16 and set the generation checkpoint interval to 1,024 samples.

Result: Made the small pilot easier to store and resume.

### 25 Aug

Added generation progress reporting and checked the canonical pilot configuration.

Result: Made generation progress visible and kept the dataset settings recorded.

### 26 Aug

Ran the first C2 baseline using log-mel inputs and a small CNN for eight controls. Used 819 training, 102 validation and 103 test clips.

Result: Saved the model, spectrograms, learning curves and per-control MAE, RMSE and R squared.

### 28-30 Aug

Reviewed the pilot results and reproducibility checks. Attack and release were recovered better than resonance and drive.

Result: Recorded the weaknesses of the small-data baseline rather than relying only on its average score.

### Weekly outcome

The first version connected validated pilot audio to a repeatable estimation baseline.

### Next step

Consolidate the first version and define the research work needed for C2.

### Weekly review

Reviewer comments: ____________________________________________

_____________________________________________________________

Reviewed by: __________________    Role: Supervisor / Co supervisor

Signature: ____________________    Date actually signed: ____ / ____ / ______

---

## Week 5   31 August to 06 September 2026

First-version review and transition to C2

### 31 Aug-01 Sep

Consolidated notes on the pilot, audio checks and baseline outputs.

Result: Kept the first version as a reference for later changes.

### 02-03 Sep

Reviewed preprocessing, fixed splits and saved metrics from the initial pipeline.

Result: Completed the first-version review and identified its research limitations.

### 05 Sep

Shifted the main focus to C2. Defined the need to estimate synthesizer controls and explain when those estimates are reliable.

Result: Set parameter estimation and reliability calibration as the component's main tasks.

### 06 Sep

Outlined the C2 workflow from audio features to predicted controls, reconstruction and reliability assessment.

Result: Retained the small CNN as the starting baseline.

### Weekly outcome

C2 became the main focus after the first-version setup and diagnostic work.

### Next step

Develop the uncertainty and acoustic-identifiability rationale.

### Weekly review

Reviewer comments: ____________________________________________

_____________________________________________________________

Reviewed by: __________________    Role: Supervisor / Co supervisor

Signature: ____________________    Date actually signed: ____ / ____ / ______

---

## Week 6   07 to 13 September 2026

C2 scope and uncertainty design

### 07-08 Sep

Examined why different synthesizer settings can produce similar sounds and why some controls may be difficult to recover.

Result: Defined parameter-recovery reliability separately from perceived sound similarity.

### 10-11 Sep

Reviewed the pilot model's stronger and weaker controls and the limits of reporting one overall error.

Result: Made per-control evaluation a requirement for the extended component.

### 12-13 Sep

Outlined the use of several independently trained models to estimate uncertainty.

Result: Planned an ensemble comparison while keeping the deterministic baseline for reference.

### Weekly outcome

The component's uncertainty question was linked to observable weaknesses in parameter recovery.

### Next step

Define reliability metrics and the forward-rendering checks.

### Weekly review

Reviewer comments: ____________________________________________

_____________________________________________________________

Reviewed by: __________________    Role: Supervisor / Co supervisor

Signature: ____________________    Date actually signed: ____ / ____ / ______

---

## Week 7   14 to 20 September 2026

Evaluation planning and progress review

### 14-15 Sep

Consolidated the completed first-version work and the proposed C2 direction in the project progress report.

Result: Separated implemented results from the planned uncertainty work.

### 17-18 Sep

Reviewed probability-quality and calibration measures alongside MAE, RMSE and R squared.

Result: Identified Brier score, calibration plots and risk-coverage analysis for the reliability stage.

### 20 Sep

Reviewed the previous two weeks of C2 planning and the evidence needed to justify its claims.

Result: Kept acoustic ambiguity and the need for independent validation explicit.

### Weekly outcome

The evaluation plan covered both point predictions and the quality of reliability estimates.

### Next step

Specify the uncertainty, sensitivity and reconstruction comparisons.

### Weekly review

Reviewer comments: ____________________________________________

_____________________________________________________________

Reviewed by: __________________    Role: Supervisor / Co supervisor

Signature: ____________________    Date actually signed: ____ / ____ / ______

---

## Week 8   21 to 27 September 2026

Forward diagnostics and reliability comparisons

### 21-23 Sep

Outlined local parameter perturbations around a predicted patch and comparison of the resulting audio.

Result: Planned sensitivity measurements without changing the delivered prediction.

### 24-25 Sep

Planned comparisons using uncertainty alone, uncertainty with sensitivity, uncertainty with reconstruction error, and all three together.

Result: Made the contribution of each reliability input testable.

### 27 Sep

Reviewed the proposed perturbation workload and the distinction between training data and diagnostic examples.

Result: Chose to investigate fixed subsets rather than perturb the entire corpus.

### Weekly outcome

The C2 design had a concrete comparison strategy for its reliability inputs.

### Next step

Plan protected data partitions and the parameter-correctness event.

### Weekly review

Reviewer comments: ____________________________________________

_____________________________________________________________

Reviewed by: __________________    Role: Supervisor / Co supervisor

Signature: ____________________    Date actually signed: ____ / ____ / ______

---

## Week 9   28 September to 04 October 2026

Validation protocol and research design review

### 28-30 Sep

Planned separate roles for training, calibration, model selection and final testing.

Result: Established the need to prevent reliability fitting and final evaluation from sharing examples.

### 01-02 Oct

Outlined reliability as the chance of recovering a control within a declared tolerance in its research range.

Result: Defined a measurable event for calibration rather than treating raw variance as a probability.

### 04 Oct

Reviewed two weeks of diagnostic and validation planning. Identified the need to revisit the synthesis domain before scaling the work.

Result: Set parameter-domain checks and a larger controlled corpus as the next dependencies.

### Weekly outcome

The proposed protocol linked each metric and data subset to a specific research purpose.

### Next step

Confirm the control set and audio-processing policy.

### Weekly review

Reviewer comments: ____________________________________________

_____________________________________________________________

Reviewed by: __________________    Role: Supervisor / Co supervisor

Signature: ____________________    Date actually signed: ____ / ____ / ______

---

## Week 10   05 to 11 October 2026

Research domain and audio conditioning

### 05-06 Oct

Reviewed the expanded single-oscillator domain and the roles of the amplitude and filter envelopes.

Result: Moved beyond the initial eight-control engineering pilot.

### 07 Oct

Selected the final 13-control domain, retaining Bend and filter-envelope sustain. Investigated DC offset and compared mitigation options.

Result: Selected a fixed 10 Hz high-pass rule, preserving raw audio and recording the processing policy.

### 08-09 Oct

Reviewed storage precision and quiet spectral energy, together with generation and resume requirements.

Result: Kept FLOAT research masters and separate PCM16 playback copies.

### 10-11 Oct

Prepared the larger-corpus workflow, fixed parameter ranges and reproducibility requirements for C2.

Result: Defined the data and runtime checks needed before full model training.

### Weekly outcome

C2 had a specified 13-control domain and a consistent audio-conditioning rule.

### Next step

Complete the corpus checks, freeze C2 partitions and train the full models.

### Weekly review

Reviewer comments: ____________________________________________

_____________________________________________________________

Reviewed by: __________________    Role: Supervisor / Co supervisor

Signature: ____________________    Date actually signed: ____ / ____ / ______

---

## Week 11   12 to 18 October 2026

Full C2 training and development validation

### 12-13 Oct

Completed checks for the 131,072-clip v4 corpus, including the FLOAT resume issue. Froze 98,304 training, 16,384 calibration, 8,192 validation and 8,192 test assignments.

Result: Split validation equally between inverse-model and reliability selection; kept the earlier 1,024 v4 clips in training.

### 13 Oct

Trained the deterministic 13-output CNN and saved data distributions, spectrograms, learning curves and per-control metrics.

Result: Measured inverse-validation macro z MAE of 0.126112 and retained the saved model and predictions.

### 14 Oct

Completed the three-member ensemble and diagnostics on 2,048 calibration and 512 reliability-validation clips.

Result: Ensemble MAE was 0.127991. Brier was 0.116267 for uncertainty alone and 0.115385 for all three inputs.

### 14-15 Oct

Audited the reliability comparisons and tested perturbation steps 0.01, 0.02 and 0.05 on 256 fixed calibration examples.

Result: Retained step 0.02. The audit did not establish an extra sensitivity benefit beyond uncertainty plus reconstruction error.

### 15 Oct

Built the saved-results viewer and organised the technical and demonstration guides.

Result: Made target/reconstruction audio, controls, reliability estimates and saved evidence easier to inspect.

### 18 Oct

Built and checked the separate C2 human-study rehearsal with one practice case, eight scored cases and counterbalanced reliability displays.

Result: Prepared a target of 12 completions with a 16-enrolment cap. Five automated tests passed; research collection remained disabled.

### Weekly outcome

The development pipeline, reliability audit and study rehearsal were available. The 13-control final test remained reserved.

### Next step

Confirm the human-study materials and approvals, then lock the method before final testing.

### Weekly review

Reviewer comments: ____________________________________________

_____________________________________________________________

Reviewed by: __________________    Role: Supervisor / Co supervisor

Signature: ____________________    Date actually signed: ____ / ____ / ______

---

## Week 12   19 to 20 October 2026

Documentation and remaining validation work

### 20 Oct

Organised the C2 research record and prepared this logbook. Reviewed the saved outputs, study design and remaining validation tasks.

Result: Kept development results, study preparation and pending final evaluation clearly distinguished.

### Weekly outcome

The C2 work was documented for review through 20 October 2026.

### Next step

Rehearse and time the study, finalise approved materials, and complete the remaining evaluation stages.

### Weekly review

Reviewer comments: ____________________________________________

_____________________________________________________________

Reviewed by: __________________    Role: Supervisor / Co supervisor

Signature: ____________________    Date actually signed: ____ / ____ / ______

---
