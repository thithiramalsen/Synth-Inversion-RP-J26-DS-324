# Synth Inversion Project: Progress Report

## Very short version

We are building a system that listens to a short synthesizer sound and tries to work out how the sound was made.

The project currently has:

- a controlled set of 1,024 generated synthesizer sounds;
- tools that describe the sounds using audio measurements;
- a working first machine-learning model that predicts eight synthesizer settings from audio;
- a working prototype that finds similar sounds and recommends more varied alternatives;
- a small listening-survey website for internal testing; and
- tests and saved output files so that important results can be repeated.

The most complete machine-learning result is Component 2. It is a first baseline, meaning a simple, repeatable starting point. It is not yet the final model or proof that the system is ready for participants.

## What problem are we solving?

Imagine someone gives us a sound made by a synthesizer, but not the synthesizer settings. We want software to estimate the settings that could have produced that sound.

The current pilot focuses on one oscillator, one filter, and the amplitude envelope. The eight settings being estimated are:

1. Wave-table position (`wave_frame`)
2. Filter cutoff (`filter_cutoff`)
3. Filter resonance (`filter_resonance`)
4. Filter drive (`filter_drive`)
5. Envelope attack (`amp_attack`)
6. Envelope decay (`amp_decay`)
7. Envelope sustain (`amp_sustain`)
8. Envelope release (`amp_release`)

The values are stored in normalized ranges. In simple terms, each setting is represented on a comparable scale, while the dataset configuration still remembers the actual allowed range for that control.

## Shared pilot dataset

The shared dataset is called `pilot_v1`. It contains 1,024 mono WAV files. Each file is:

- 44.1 kHz;
- 16-bit PCM;
- three seconds long;
- generated from a fixed MIDI note and velocity; and
- created from a controlled set of eight synth parameters.

The parameter combinations were selected with a scrambled Sobol sequence. This is a way of spreading points across the available settings so that the dataset does not accidentally bunch up in one area.

The generation configuration and parameter meanings are recorded in [data/manifests/pilot_v1_config.json](data/manifests/pilot_v1_config.json). The dataset summary is in [data/manifests/pilot_v1_summary.json](data/manifests/pilot_v1_summary.json).

The generation summary reports:

- 1,024 sounds generated;
- no silent samples;
- no clipped samples;
- the generation summary reports matching channel checks for all 1,024 files;
- a peak level below clipping; and
- 158 samples flagged for a relatively large DC offset warning.

The last item is a quality warning worth remembering. It did not stop the pilot from being used, but it should be investigated before treating the audio as final research material.

The data-generation code is [generation/scripts/05_generate_pilot_dataset.py](generation/scripts/05_generate_pilot_dataset.py). The project also contains dataset-archive tooling under [tools](tools).

## Component 1: basic timbre measurements

Component 1 asks: can ordinary audio measurements tell us something about a synthesizer setting?

The script reads the shared manifest and calculates, for every sound:

- spectral centroid, which is roughly the sound's center of brightness;
- spectral rolloff;
- loudness/RMS;
- zero-crossing rate; and
- 13 average MFCC values, which are compact numbers describing the sound's shape.

The first checkpoint comparison was filter cutoff versus spectral centroid. For 128 development sounds, the relationship was positive:

- Pearson correlation: `0.5197`;
- R-squared: `0.2701`; and
- slope: about `1,304.5 Hz` per normalized cutoff unit.

This is useful evidence that cutoff affects an easily measured part of the sound. It is not a perfect relationship, so it should not be treated as a complete explanation of timbre.

The implementation and instructions are in [c1_timbre/README.md](c1_timbre/README.md). The saved measurements are in [c1_timbre/outputs](c1_timbre/outputs).

## Component 2: estimating synth settings from audio

### The goal

Component 2 takes a sound file as input and predicts the eight synth settings that belong to it.

In beginner terms:

1. Turn each sound into a picture of its frequency content over time.
2. Show those pictures and the correct settings to a small neural network.
3. Test whether the network can predict the settings for sounds it did not train on.

The main implementation is [c2_estimation/pipeline.py](c2_estimation/pipeline.py), with the process described in [c2_estimation/README.md](c2_estimation/README.md).

### Step 1: check the input data

Before training, the pipeline checks that:

- the manifest contains the expected 1,024 rows;
- every sample ID and sample index is unique;
- sample indexes run from zero to 1,023;
- every WAV file exists;
- every file is mono, 44.1 kHz, and exactly three seconds;
- every target value is a real number; and
- every target is inside its configured allowed range.

This prevents the model from silently training on missing, malformed, or mismatched files.

### Step 2: make a fair, repeatable split

The 1,024 sounds are split into three groups:

- 819 training sounds: used to learn;
- 102 validation sounds: used to decide which training point is best; and
- 103 test sounds: kept aside until the end.

The split uses a fixed seed, `20260826`. Therefore, rerunning the same pipeline creates the same groups. The exact assignment is saved in [c2_estimation/outputs/split_manifest.csv](c2_estimation/outputs/split_manifest.csv), along with an assignment hash.

Why this matters: if we tested on sounds the model had already seen, the result could look impressive without showing whether the model generalizes. The held-out test set gives us a more honest check.

### Step 3: turn audio into model input

The model does not read raw WAV values directly. Each three-second waveform is converted into a log-mel spectrogram.

An ELI5 description: a spectrogram is like a heat-map. One direction is time, the other direction is frequency, and brighter or darker areas show how much energy is present. A mel scale groups frequencies in a way that is more similar to how people hear them.

The fixed settings are:

- 64 mel frequency bands;
- a 2,048-sample Hann window;
- a 512-sample hop between windows;
- frequencies from 20 Hz to 20 kHz;
- reflect padding at the edges; and
- an 80 dB floor using a fixed 0 dBFS reference.

Each input has shape `64 x 259`. The resulting feature cache is [data/processed/c2_pilot_v1_logmel.npz](data/processed/c2_pilot_v1_logmel.npz). It is reproducible from the audio and is excluded from version control.

The pipeline calculates the input mean and standard deviation using only the training sounds. Validation and test sounds do not influence this preprocessing step. This avoids leaking information from the test set into training.

Four example spectrogram images are saved in [c2_estimation/outputs/spectrogram_examples](c2_estimation/outputs/spectrogram_examples).

### Step 4: use one small CNN

The model is a small convolutional neural network called `ParameterCNN`.

In simple terms, it looks for useful visual patterns in the spectrogram. It has:

- three convolution, ReLU, and max-pooling blocks;
- adaptive average pooling so the representation has a fixed size;
- a small two-layer regressor; and
- eight outputs, one for each synth setting.

The outputs use sigmoid mapping so every prediction stays inside the configured parameter range. The model has 22,856 trainable parameters.

The training loss is range-normalized squared error. This means an error is measured relative to each control's allowed range, so a large-range parameter does not automatically dominate a small-range parameter.

Training uses Adam on the CPU with:

- batch size 32;
- learning rate `0.001`;
- weight decay `0.0001`;
- at most 60 epochs; and
- early stopping patience of 12 epochs.

The run completed 60 epochs, with the best validation result at epoch 56. Deterministic algorithms and fixed random seeds were used.

### Step 5: evaluate only on unseen sounds

After training, the model predicts the 103 test sounds. The main measurements are:

- MAE: average absolute error. Lower is better.
- RMSE: a measure that penalizes large errors more strongly. Lower is better.
- R-squared: how much of the variation is explained compared with a simple average prediction. Higher is better; a negative value means the model is worse than that simple comparison for that parameter.

The saved test results are in [c2_estimation/outputs/test_metrics.json](c2_estimation/outputs/test_metrics.json) and [c2_estimation/outputs/test_predictions.csv](c2_estimation/outputs/test_predictions.csv).

### Component 2 result

All values below are normalized synth-parameter units and use the 103 held-out test sounds.

| Parameter | MAE | RMSE | R-squared | Plain-English reading |
| --- | ---: | ---: | ---: | --- |
| Wave frame | 0.12371 | 0.16114 | 0.71015 | Reasonably useful first result |
| Filter cutoff | 0.06061 | 0.09006 | 0.73098 | Reasonably useful first result |
| Filter resonance | 0.19920 | 0.23003 | -0.03846 | Weak; currently not learned reliably |
| Filter drive | 0.18359 | 0.21071 | 0.17279 | Weak to moderate |
| Amp attack | 0.01878 | 0.02382 | 0.95722 | Strong result |
| Amp decay | 0.07430 | 0.08942 | 0.25699 | Mixed result |
| Amp sustain | 0.09174 | 0.12705 | 0.63209 | Moderately useful |
| Amp release | 0.01759 | 0.02459 | 0.94355 | Strong result |

The overall averages are:

- MAE: `0.09619`;
- RMSE: `0.11960`; and
- R-squared: `0.54566`.

The clearest success is envelope timing: attack and release are predicted well. Wave position, cutoff, and sustain show useful signal too. Resonance is the clearest failure, and drive is also difficult. This is an important scientific result because it tells us where the first model and/or the current audio representation are insufficient.

### What was saved for Component 2

The output folder [c2_estimation/outputs](c2_estimation/outputs) contains:

- `best_model.pt`: the best checkpoint, including model weights and preprocessing/target metadata;
- `split_manifest.csv`: the exact train, validation, and test assignments;
- `training_history.csv`: training and validation loss by epoch;
- `learning_curves.png`: a visual summary of learning;
- `test_predictions.csv`: actual values, predictions, and errors for every held-out test sound;
- `test_metrics.csv` and `test_metrics.json`: per-control and overall scores;
- `spectrogram_examples`: fixed example input pictures; and
- `run_config.json`: hashes, settings, package versions, split details, and summary metrics.

### Component 2 reproducibility checks

The project documentation records these checks:

- three focused tests pass for split reproducibility, split completeness, and metric calculation;
- the checkpoint reloads and contains the expected eight-target metadata; and
- a second complete CPU run reproduced the split manifest, all 103 test predictions, and the metric CSV byte-for-byte.

The focused tests are in [c2_estimation/tests/test_pipeline.py](c2_estimation/tests/test_pipeline.py). The documented commands are:

```powershell
python c2_estimation/pipeline.py
python -m unittest discover -s c2_estimation/tests -v
```

### What Component 2 does not claim yet

This is deliberately only a baseline. It does not yet include:

- the planned 65,536-sample dataset;
- multiple models or an ensemble;
- uncertainty estimates or uncertainty calibration;
- a human listening evaluation of prediction quality; or
- the Component 3 recommendation system inside the model.

The negative resonance result and weak drive result should therefore be treated as guidance for the next experiment, not as proof that those controls can never be estimated.

## Component 3: finding similar sounds and making recommendations

Component 3 starts with an isolated audio clip and retrieves similar pilot sounds using MFCC audio features. It then uses maximal marginal relevance, or MMR, to avoid returning five nearly identical parameter settings.

In simple terms:

1. Find sounds that sound similar.
2. Keep the first result very similar.
3. For later results, prefer sounds that are still similar but use different synth settings.

The prototype evaluates 32 fixed in-dataset query sounds. It uses the top 50 audio matches as the pool and returns five recommendations. At `lambda = 0.75`:

- mean audio similarity changes from `0.91831` to `0.90422`;
- mean pairwise parameter distance increases from `0.31961` to `0.38014`;
- the minimum pairwise parameter distance increases from `0.20411` to `0.29043`.

So the prototype gives up about 1.5% of average audio similarity to gain about 18.9% more parameter diversity. It also reduces near-duplicate recommendations. This is a prototype result, not evidence that `lambda = 0.75` is the best setting for users.

Component 3 intentionally does not use Component 2 predictions as a replacement for audio retrieval. It also does not yet include DPP, timbre-description input, or user-preference evaluation.

The implementation and details are in [c3_recommendation/README.md](c3_recommendation/README.md). The saved comparison is [c3_recommendation/outputs/comparison_summary.json](c3_recommendation/outputs/comparison_summary.json).

## Component 4: perceptual similarity check

Component 4 prepares a simple listening test to compare an audio-distance baseline with human judgments.

The current development version freezes ten triplets. Each triplet contains:

- a reference sound;
- Candidate A; and
- Candidate B.

The listener chooses which candidate sounds more like the reference and gives a confidence score from 1 to 5. The file [c4_metric/development_triplets.csv](c4_metric/development_triplets.csv) freezes the triplet choices, selection seed, and MFCC baseline choice so the test can be repeated.

This is internal development testing. It is not yet evidence from formal research participants. The MFCC baseline checker is [c4_metric/mfcc_baseline.py](c4_metric/mfcc_baseline.py), and the instructions are in [c4_metric/README.md](c4_metric/README.md).

## Listening-survey application

The repository contains a local React/Vite frontend and FastAPI backend. It currently supports three internal studies:

- `pilot_quality`: quality ratings for the pilot sounds;
- `c1_descriptors`: four bipolar timbre ratings such as dark/bright and smooth/rough; and
- `c4_triplets`: the ten reference-versus-A/B perceptual comparisons.

The backend:

- loads the shared audio manifest;
- serves WAV files;
- randomizes the trial order per session;
- saves responses in SQLite;
- validates study-specific answers; and
- exports CSV files for local analysis.

The frontend provides the study pages, playback controls, rating controls, progress information, and an admin/export view. A separate demo screen was also added with four example audio files so the app can be shown without running a full study session.

The application instructions and important safety note are in [survey/README.md](survey/README.md). The export routes are currently unauthenticated and are intended to remain local until protected before any network hosting.

The documented checks are:

```powershell
python -m pytest survey/backend/tests
cd survey/frontend
npm run build
```

## Work history visible in Git

The recent project milestones are visible in the repository history:

- `db6a5b1`: added the first C1 and C4 components and connected the survey work;
- `9d45c32`: added dataset archive tooling;
- `7cd537f`: regenerated the 1,024-sound 16-bit PCM pilot;
- `85f540d`: improved the generation progress reporting;
- `1619409`: added the complete Component 2 deterministic CNN baseline and outputs;
- `ee74879`: added the complete Component 3 recommendation prototype and outputs; and
- `f1e51f1`: added the local app demo screen and demo audio.

The current checked-out branch is `dev-survey-app-c2`. The working tree was clean when this report was prepared.

## Honest status for the supervisor

### Completed

- A controlled 1,024-sound pilot dataset exists.
- The data has manifests, configuration, summaries, and archive support.
- C1 audio descriptors and a cutoff/brightness analysis exist.
- C2 has a reproducible CNN baseline with a held-out test result.
- C3 has a reproducible MFCC retrieval plus diversity reranking prototype.
- C4 has frozen development triplets and a baseline comparison tool.
- The local survey app supports the current internal studies.
- Important code paths have focused tests and saved outputs.

### Still limited or incomplete

- The survey work is internal development testing, not formal participant research.
- The current listening application documentation describes a 128-sample listening subset while the C2 dataset uses 1,024 samples; the intended formal listening subset still needs to be documented before collection.
- Component 2 is trained on the 1,024-sample pilot, not the planned 65,536-sample dataset.
- Component 2 is a single small CNN and has no uncertainty estimates.
- Component 2 performs poorly on resonance and is weak on drive.
- Component 3's diversity setting has not been validated with user preferences.
- Component 4's ten triplets are a development instrument, not a participant result.
- The generated-data summary contains DC-offset warnings for 158 sounds.
- The local survey export endpoints need authentication or network restrictions before deployment.

## Sensible next steps

1. Investigate the 158 DC-offset warnings and confirm whether they affect listening or model training.
2. Decide and document which sounds belong in the formal listening study.
3. Use the Component 2 weaknesses to design the next dataset/model experiment, especially for resonance and drive.
4. Compare the baseline against stronger representations or an ensemble, while keeping the current deterministic baseline for comparison.
5. Run and analyze the internal C4 listening trials before making claims about perceptual similarity.
6. Protect the survey export routes before putting the app on any network.
7. Only then broaden participant testing, subject to supervisor and ethics approval.

## Main files to show tomorrow

- [c2_estimation/README.md](c2_estimation/README.md): simple Component 2 explanation and exact result table.
- [c2_estimation/outputs/test_metrics.json](c2_estimation/outputs/test_metrics.json): Component 2 scores.
- [c2_estimation/outputs/learning_curves.png](c2_estimation/outputs/learning_curves.png): training behavior.
- [c2_estimation/outputs/spectrogram_examples](c2_estimation/outputs/spectrogram_examples): examples of the model input.
- [c2_estimation/outputs/test_predictions.csv](c2_estimation/outputs/test_predictions.csv): individual held-out predictions.
- [data/manifests/pilot_v1_config.json](data/manifests/pilot_v1_config.json): what was generated and which parameters changed.
- [c3_recommendation/outputs/comparison_summary.json](c3_recommendation/outputs/comparison_summary.json): recommendation comparison.
- [survey/README.md](survey/README.md): what the local listening application does and its current limits.
