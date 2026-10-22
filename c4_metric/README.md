# C4 — Human-aligned synthesizer audio similarity

C4 asks whether a frozen pretrained audio representation can be adapted with human preferences from synthesizer-reconstruction comparisons. The deliverable is a scorer benchmarked against held-out listener choices; training a neural network by itself is not evidence of perceptual alignment.

## Current repository state

- `data/raw/audio/pilot_v1/` contains 1,024 verified eight-control development renders. The current `restricted_bend_sustain_v4` corpus contains 131,072 raw FLOAT renders with 13 normalized Vital controls and sample metadata.
- The proposal's 65,536-render set is a plan, not the corpus currently stored. Confirm the frozen dataset version with the supervisor before final study materials or claims.
- The hosted C4 interface in `survey/` is a supervisor review protocol. Its records are excluded from research analysis. This offline pipeline does not authorize recruitment or convert review responses into research evidence.
- The current survey export uses `reference`, `candidate_a`, `candidate_b`, and `choice`. The proposal describes target A and candidates B/C. Field and answer mappings are configurable.

## Similarity scoring

`similarity.score_similarity(reference_audio, candidate_audio, method)` returns `SimilarityResult(similarity, distance)`. **Higher similarity always means closer; lower distance always means closer.**

| Method | Definition | Status |
| --- | --- | --- |
| MFCC | 13-coefficient mel cepstra; omit energy coefficient C0; duration-pooled mean and standard deviation; cosine similarity | Implemented |
| Multi-scale STFT | Hann magnitude spectra at 512/1,024/2,048/4,096 points, quarter-window hop; compare duration-pooled log profiles and average scale-wise cosine similarities | Implemented |
| STFT | Single 2,048-point Hann magnitude baseline retained for diagnostics | Implemented |
| CLAP | Frozen `laion/clap-htsat-unfused`, revision `8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a`; cosine similarity | Implemented; local checkpoint/cache required unless downloads are enabled |
| Synth-aware | Euclidean distance over normalized Vital controls divided by `sqrt(parameter_count)`; similarity is `1 - distance` | Implemented for corpus IDs; a parameter-space baseline, not an audio-only metric |
| CDPAM | Published contrastive perceptual audio distance | Optional adapter for the authors' package and pretrained checkpoint; not installed in the current environment, so it is marked unavailable until installed |

Audio methods downmix to mono, resample to 44.1 kHz, apply the repository's 10 Hz DC high-pass, normalize clip RMS toward 0.03 with a 0.89 peak ceiling, then extract features. MFCC/STFT use duration-pooled summaries, so clips of different lengths need no frame padding. CLAP input is resampled from 44.1 to 48 kHz. CDPAM receives 22.05 kHz PCM16 through its published audio loader. MFCC/STFT scores map cosine to `[0,1]`; CLAP/C4 use native cosine in `[-1,1]`. Scores have method-specific scales and are not calibrated probabilities.

To score two audio files directly, pass their paths to `score_pair.py`:

```powershell
.\venv\Scripts\python.exe c4_metric\score_pair.py "C:\path\to\reference.wav" "C:\path\to\candidate.wav" --method c4 --allow-synthetic-checkpoint
```

The current C4 checkpoint was trained on synthetic preferences, so this command is for software demonstration only. For the frozen pretrained CLAP baseline, use `--method clap` and omit `--allow-synthetic-checkpoint`. MFCC and STFT are also available with `--method mfcc` or `--method stft`. Every result reports similarity and distance; higher similarity and lower distance mean more similar. The numeric score is not a percentage.

For a local drag-and-drop page, start the browser interface from the repository root:

```powershell
.\venv\Scripts\python.exe c4_metric\audio_similarity_app.py --checkpoint c4_metric\outputs\synthetic_training\best_model.pt --allow-synthetic-checkpoint
```

Open `http://127.0.0.1:8765`, drop two sounds in the boxes, choose C4, CLAP, MFCC, STFT, or multi-scale STFT, and press **Calculate similarity**. The server binds to localhost and reads the uploaded files locally. Stop it with Ctrl+C. The current C4 checkpoint is synthetic-demo-only; the interface labels it accordingly.

Run available frozen baselines on one identical real audio pair. The default pair comes from the first C4 CLAP-bank triplet:

```powershell
.\venv\Scripts\python.exe c4_metric\benchmark_baselines.py
```

The JSON report is written under ignored `c4_metric/outputs/`. Smoke-test scores are implementation checks, not human results. Add `--checkpoint c4_metric\outputs\synthetic_training\best_model.pt --allow-synthetic-checkpoint` to exercise an adapted scorer on the same pair. The C3 adapter refuses synthetic-label checkpoints by default.

## Dependencies

The repository root requirements supply NumPy, SciPy and SoundFile. Install the C4 encoder/training packages in the existing virtual environment:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m pip install -r c4_metric\requirements.txt
```

`c4_metric/requirements.txt` pins PyTorch and Transformers. The scripts default to local checkpoint files. Use `--allow-model-download` only when a model must be fetched and network access is available.

## Synthetic data mode A: controlled embeddings

This creates deterministic embeddings where positive examples are closer to anchors than negatives. It exercises data loading, grouped splitting, loss, gradients, optimizer updates, checkpoint selection and training output without audio or participants:

```powershell
.\venv\Scripts\python.exe c4_metric\synthetic_data\generate_synthetic_embeddings.py --triplets 600 --dimension 128 --seed 20261014
.\venv\Scripts\python.exe c4_metric\splits.py c4_metric\synthetic_data\pipeline_smoke\synthetic_preference_triplets.csv --output c4_metric\outputs\dummy_splits\split_manifest.csv --summary c4_metric\outputs\dummy_splits\split_summary.json
.\venv\Scripts\python.exe c4_metric\train.py --triplets c4_metric\outputs\dummy_splits\split_manifest.csv --embeddings c4_metric\synthetic_data\pipeline_smoke\synthetic_embeddings.npz --output-dir c4_metric\outputs\dummy_training --allow-synthetic
```

## Synthetic data mode B: actual Vital sounds, simulated answers

The existing generator samples the actual 131,072-row corpus, embeds a seeded 1,024-sound pool with CLAP, creates a 200-triplet bank, and gives each synthetic listener a different 20-question set. Choices and confidence are simulated independently of CLAP. See [`synthetic_data/README.md`](synthetic_data/README.md).

Process and split those practice responses:

```powershell
.\venv\Scripts\python.exe c4_metric\preference_data.py c4_metric\synthetic_data\dummy_c4_responses.csv --manifest data\raw\corpus_v4\manifest.csv --mapping c4_metric\config\response_mapping.json --output-dir c4_metric\outputs\synthetic_responses --allow-synthetic
.\venv\Scripts\python.exe c4_metric\splits.py c4_metric\outputs\synthetic_responses\preference_triplets.csv --output c4_metric\outputs\synthetic_splits\split_manifest.csv --summary c4_metric\outputs\synthetic_splits\split_summary.json
```

Cache frozen CLAP embeddings for all IDs. This uses the scorer's audio preprocessing and writes model, revision and manifest hashes beside the cache:

```powershell
.\venv\Scripts\python.exe c4_metric\cache_embeddings.py c4_metric\synthetic_data\clap_triplets.csv --manifest data\raw\corpus_v4\manifest.csv --output c4_metric\outputs\embeddings\clap_corpus_v4.npz
```

Train only the small projection head; CLAP stays frozen. Validation loss selects the checkpoint; test labels are not used in training:

```powershell
.\venv\Scripts\python.exe c4_metric\train.py --triplets c4_metric\outputs\synthetic_splits\split_manifest.csv --embeddings c4_metric\outputs\embeddings\clap_corpus_v4.npz --output-dir c4_metric\outputs\synthetic_training --allow-synthetic
```

Exercise the evaluation output path. Synthetic evaluation suppresses accuracy, intervals and significance statistics:

```powershell
.\venv\Scripts\python.exe c4_metric\evaluate.py c4_metric\outputs\synthetic_splits\split_manifest.csv --manifest data\raw\corpus_v4\manifest.csv --checkpoint c4_metric\outputs\synthetic_training\best_model.pt --embeddings c4_metric\outputs\embeddings\clap_corpus_v4.npz --output-dir c4_metric\outputs\synthetic_evaluation --allow-synthetic
```

## Processing human survey CSVs later

Use `config/response_mapping.json` for the current C4 export or `config/response_mapping_proposal_bc.json` for target A and candidate B/C fields. Edit the JSON aliases when the real export differs. Do not pass `--allow-synthetic` for human data:

```powershell
.\venv\Scripts\python.exe c4_metric\preference_data.py path\to\approved_c4_responses.csv --manifest data\raw\corpus_v4\manifest.csv --mapping c4_metric\config\response_mapping.json --output-dir c4_metric\outputs\human_responses
```

The processor validates required IDs against the manifest, checks missing/malformed rows, choices and duplicate presentations, and writes:

- `cleaned_responses.csv`: original fields plus normalized fields; every listener answer is retained.
- `rejected_responses.csv`: source row and validation reason.
- `preference_triplets.csv`: one A/P/N row per decisive individual answer, with confidence metadata and the aggregate vote status.
- `aggregate_preference_triplets.csv`: one training triplet per unambiguous aggregated comparison; ties and unresolved outcomes are absent and counted in the quality summary.
- `aggregate_preferences.csv`: comparison IDs, first/second candidate vote counts, agreement, uncertainty counts, and `preference`, `tie`, or `unresolved` status.
- `quality_summary.json`: input, accepted, rejected, confidence-validity, vote-status, and excluded-comparison counts.

Uncertainty is not converted into a preference. Invalid or missing confidence does not invalidate an otherwise valid judgment; original values remain in the response CSV and normalized confidence is blank with a status. Confidence never changes labels, triplet selection, weights, or loss. Tied and unresolved aggregates are retained in the response artifacts and excluded by `splits.py` and defensively by `train.py`. Individual responses remain distinguishable from aggregate outcomes. The default 0.67 agreement threshold only marks aggregate rows. Synthetic and human rows cannot be combined. The current hosted review export has `analysis_include=false` and is excluded. A real study needs its own approved, versioned protocol and eligible export.

Run the independent descriptive confidence report after response normalization:

```powershell
.\venv\Scripts\python.exe c4_metric\analyze_confidence.py c4_metric\outputs\human_responses\cleaned_responses.csv --output c4_metric\outputs\human_responses\confidence_analysis.json
```

It reports counts and percentages for ratings 1–5, mean/median, confidence by aggregate comparison status, and within-participant consistency on repeated anchor/candidate sets when available. It does not modify training artifacts or infer correctness from confidence.

### C4 representation and C3 adapter

The default C4 representation is the frozen **CLAP audio encoder** `laion/clap-htsat-unfused`, pinned to revision `8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a`. Audio is loaded as mono float32, conditioned and level-matched at 44.1 kHz, resampled to 48 kHz for the CLAP processor, then encoded as finite, L2-normalized float32 vectors of shape `[samples, 512]`. The trainable C4 projection head consumes those vectors; the CLAP encoder remains frozen. Cache metadata records the model, revision, preprocessing, dimensions, and input hashes. Training checks the metadata and vector dimensions before optimizing.

The separate `cache_mfcc_embeddings.py` and MFCC26 adapter remain available as an experimental/recoverable implementation. They are not the default C4 path and do not alter C3's own candidate database or recommendation pipeline. `logmel_stats` is not used by either path.

Run this after exporting and normalizing the completed survey. The aggregation step creates only majority-winner triplets for training; confidence remains in the response artifacts for its separate report. CLAP model files must be cached locally unless `--allow-model-download` is supplied.

```powershell
.\venv\Scripts\python.exe c4_metric\preference_data.py path\to\completed_c4_responses.csv --manifest data\raw\corpus_v4\manifest.csv --mapping c4_metric\config\response_mapping.json --output-dir c4_metric\outputs\human_responses
.\venv\Scripts\python.exe c4_metric\splits.py c4_metric\outputs\human_responses\aggregate_preference_triplets.csv --output c4_metric\outputs\human_splits\split_manifest.csv --summary c4_metric\outputs\human_splits\split_summary.json
.\venv\Scripts\python.exe c4_metric\cache_embeddings.py c4_metric\outputs\human_responses\aggregate_preference_triplets.csv --manifest data\raw\corpus_v4\manifest.csv --output c4_metric\outputs\human_embeddings\clap_embeddings.npz
.\venv\Scripts\python.exe c4_metric\train.py --triplets c4_metric\outputs\human_splits\split_manifest.csv --embeddings c4_metric\outputs\human_embeddings\clap_embeddings.npz --output-dir c4_metric\outputs\human_training
.\venv\Scripts\python.exe c4_metric\evaluate.py c4_metric\outputs\human_splits\split_manifest.csv --manifest data\raw\corpus_v4\manifest.csv --checkpoint c4_metric\outputs\human_training\best_model.pt --embeddings c4_metric\outputs\human_embeddings\clap_embeddings.npz --output-dir c4_metric\outputs\human_evaluation --methods clap,mfcc,ms_stft,c4
```

`cache_embeddings.py` is a post-survey/offline step. It resolves and loads each referenced audio file, runs the pinned frozen CLAP encoder, and writes the normalized 512D cache. The C4 evaluator accepts the cache corresponding to the checkpoint's encoder. For aggregate triplets it reports comparison-level accuracy and audio-component bootstrap intervals rather than treating aggregate comparisons as individual participants. The C4 input loader is `train.load_arrays`; the scorer adapter uses the same pinned CLAP encoder:

```python
from c4_metric.c3_adapter import AdaptedScorer, score_reference_against_candidates

scorer = AdaptedScorer("c4_metric/outputs/human_training/best_model.pt")
ranked = score_reference_against_candidates(reference_audio, candidate_audios,
                                             method="c4", scorer=scorer)
```

The adapter requires a checkpoint trained from the pinned 512D CLAP cache; it rejects incompatible checkpoints rather than reshaping another feature type. It returns `SimilarityResult` scores (higher is closer). This adapter can be used by callers that already use the C4 adapter interface; the standalone C3 pipeline remains unchanged.

## Leakage-safe splits and model

`splits.py` joins records into connected components using all audio IDs in each A/P/N triplet, then assigns whole components to train/validation/test. This prevents anchors and candidates from crossing folds. If repeated audio connects the entire graph, splitting fails clearly instead of leaking identities. Listeners can appear in multiple folds, so this is a held-out-audio comparison, not an unseen-listener split. The evaluator independently verifies the audio disjointness before scoring.

`model.py` implements the required objective with cosine distance:

```text
d(x,y) = 1 - cosine_similarity(x,y)
L = mean(max(0, d(A,P) - d(A,N) + margin))
```

`train.py` applies a trainable linear projection and L2 normalization to frozen encoder vectors. It uses mini-batches, AdamW, a fixed seed, validation loss for checkpoint selection and early stopping. It saves `best_model.pt`, `training_history.csv`, and `run_config.json`. Test rows are not used for training or model selection. Lower dummy loss shows the training code runs; it does not show human alignment.

`evaluate.py` compares adapted C4 with original frozen CLAP, MFCC, multi-scale STFT, optional CDPAM, and synth-aware parameter distance on exactly the same held-out human responses. It selects the strongest baseline on validation only, then reports C4 versus every available baseline. Human results include response-level triplet-choice accuracy, participant-macro accuracy, two-way participant/audio-component bootstrap 95% intervals, paired participant sign tests with Holm correction, and descriptive test rankings. Model-score ties count as half-correct. Test labels are never used to train C4 or select a checkpoint/baseline.

The paired sign test treats participants as independent clusters. Confidence intervals resample both listeners and audio-disjoint components. Hard-case output summarizes high-consensus and ambiguous human triplets only when each has at least five raters and at least five triplets, plus any supplied `case_type`, `comparison_type`, or `hard_case_type` groups with enough held-out items. These summaries are exploratory. Synthetic evaluation suppresses accuracy, intervals, tests, and hard-case results.

### Run the human benchmark

After the approved survey export is normalized, split the aggregate majority-vote triplets, cache frozen CLAP embeddings, train on train/validation, and evaluate the held-out comparisons once:

```powershell
.\venv\Scripts\python.exe c4_metric\preference_data.py C:\path\to\approved_human_responses.csv --manifest data\raw\corpus_v4\manifest.csv --mapping c4_metric\config\response_mapping.json --output-dir c4_metric\outputs\human_responses
.\venv\Scripts\python.exe c4_metric\splits.py c4_metric\outputs\human_responses\aggregate_preference_triplets.csv --output c4_metric\outputs\human_splits\split_manifest.csv --summary c4_metric\outputs\human_splits\split_summary.json
.\venv\Scripts\python.exe c4_metric\cache_embeddings.py c4_metric\outputs\human_responses\aggregate_preference_triplets.csv --manifest data\raw\corpus_v4\manifest.csv --output c4_metric\outputs\human_embeddings\clap_embeddings.npz
.\venv\Scripts\python.exe c4_metric\train.py --triplets c4_metric\outputs\human_splits\split_manifest.csv --embeddings c4_metric\outputs\human_embeddings\clap_embeddings.npz --output-dir c4_metric\outputs\human_training
.\venv\Scripts\python.exe c4_metric\evaluate.py c4_metric\outputs\human_splits\split_manifest.csv --manifest data\raw\corpus_v4\manifest.csv --checkpoint c4_metric\outputs\human_training\best_model.pt --embeddings c4_metric\outputs\human_embeddings\clap_embeddings.npz --output-dir c4_metric\outputs\human_evaluation --methods clap,mfcc,ms_stft,c4
```

The evaluator writes validation/test comparison scores and `benchmark_config.json`, which records input hashes, available methods, split checks, validation baseline selection, test metrics, paired tests, confidence intervals and hard-case counts. The frozen CLAP scorer and adapted C4 use the same pinned CLAP representation when the validated cache covers both samples. Frozen test embeddings can be cached because no human test labels enter training or model selection. If CDPAM is installed and loads its pretrained weights, the evaluator includes it on those same rows; otherwise the report gives its failure reason. The published [CDPAM implementation](https://github.com/pranaymanocha/PerceptualAudio/tree/master/cdpam) documents installation with `pip install cdpam` and its runtime requirements; see the [paper](https://arxiv.org/abs/2102.05109). This environment currently has no CDPAM package. Synthetic labels and synthetic checkpoints remain software-only and are not evidence of human perceptual similarity.

## C3 adapter

After training on approved human preferences, C3 can create `c4_metric.c3_adapter.AdaptedScorer(checkpoint)` and call `score(reference, candidate)`. It checks the checkpoint's frozen CLAP model and revision, then returns higher-is-closer scores. `score_reference_against_candidates` returns candidates ranked most-to-least similar. The adapter refuses checkpoints trained with synthetic labels unless the caller explicitly enables a software-only check.

## Tests

```powershell
.\venv\Scripts\python.exe -m unittest discover -s c4_metric\tests -v
.\venv\Scripts\python.exe c4_metric\benchmark_baselines.py --checkpoint c4_metric\outputs\synthetic_training\best_model.pt --allow-synthetic-checkpoint
```

Tests cover MFCC/STFT direction, stereo/duration handling, triplet-loss math, zero and positive loss, gradients, parameter updates, survey validation, disagreement/ties/uncertainty, manifest matching, identity-grouped splits and a synthetic end-to-end training run. The pair-scoring smoke helper checks MFCC, single-scale STFT, CLAP, synth-aware and optionally adapted C4; the human benchmark also computes multi-scale STFT and optional CDPAM. Generated checkpoints and outputs live under ignored `c4_metric/outputs/`.

## Research boundary

The synthetic listeners, responses, consent/experience placeholders and labels are not participants. Do not combine these files with human exports or cite their scores as evidence. Only ethics-approved, held-out human preferences can establish whether C4 agrees better than the strongest validated baseline. If it does not, retain that baseline for C3.
