# Synth Inversion Research Project

Research tools for understanding how synthesizer settings relate to sound: describe timbre, estimate the settings behind an isolated audio clip, recommend similar sounds with different parameter configurations, and compare audio similarity with human judgments.

The project uses **Vital through Vita**, a controlled synthetic-audio corpus, Python analysis and machine-learning pipelines, and a React/FastAPI listening-study application. It contains four research components, shared generation tools, reproducibility checks, and versioned study instruments.

## Project status

Documentation snapshot: **20 October 2026**. Several generations of experiments coexist; the dataset and workflow named in each section matter.

| Area | Implemented | Current scope |
| --- | --- | --- |
| Dataset generation | Controlled rendering, parameter readbacks, resumable parallel generation, audio QA, reference comparison | Completed **131,072-sound, 13-control v4 corpus** on the reference machine; bulk audio and private reproduction assets are distributed separately |
| **C1: Timbre** | Audio feature extraction, exploratory parameter/feature analysis, exact study-signal feature extraction | Descriptor-rating instrument is implemented; a validated predictor of human timbre ratings remains future work |
| **C2: Parameter estimation** | Deterministic CNN, three-member probabilistic ensemble, forward-render diagnostics, development reliability calibration, saved-results viewer | Full-corpus training and development analyses are complete; final test evaluation and a live upload/inference interface remain pending |
| **C3: Recommendation** | Working eight-control MFCC/MMR prototype; v4 data contracts, splits, selection code, audio checks, feature extraction and diagnostics | Full-corpus development tooling exists; final v4 evaluation and method selection remain pending |
| **C4: Similarity** | Historical MFCC comparison baseline; frozen real-audio CLAP triplet bank and listening instrument | Human-judgment collection infrastructure exists; a learned, human-aligned similarity metric is not yet implemented |
| Listening application | C1/C4 participant and review flows, consent, playback, resume, withdrawal, researcher access and exports | Versioned protocols and Docker/Render configuration are included; deployment configuration alone does not establish a running or approved study |

The C2 human-study application is a separate **local rehearsal**, with research collection disabled in code. Synthetic C4 answer files are software fixtures, not participant findings.

## Contents

- [Repository structure](#repository-structure)
- [Requirements and setup](#requirements-and-setup)
- [Datasets and audio contracts](#datasets-and-audio-contracts)
- [Reproduce the full corpus](#reproduce-the-full-corpus)
- [Research components](#research-components)
- [Run the listening application](#run-the-listening-application)
- [Tests and verification](#tests-and-verification)
- [Research limits and reproducibility](#research-limits-and-reproducibility)
- [Documentation index](#documentation-index)

## Repository structure

```text
Synth-Inversion-RP/
|-- generation/          Vital profiles, presets, renderers, QA and reproduction tools
|-- c1_timbre/           Timbre features, exploratory analysis and research plans
|-- c2_estimation/       Historical baseline, v4 models, diagnostics and local viewers
|   |-- v4/             Full-corpus training, uncertainty and calibration workflows
|   |-- viewer/         Source templates for the saved-results demonstration
|   `-- human_study/    Separate C2 local rehearsal application
|-- c3_recommendation/   Historical retrieval prototype and v4 recommendation tooling
|   |-- src/c3/         Data, audio, retrieval, selection, metrics and evaluation modules
|   |-- scripts/        Staged inspection, splitting, checking and feature workflows
|   `-- configs/        v4 paths, seeds and experimental settings
|-- c4_metric/          Similarity baselines, triplet selection and synthetic fixtures
|-- survey/
|   |-- frontend/       React/Vite participant and researcher interfaces
|   |-- backend/        FastAPI, authentication and SQLite/PostgreSQL storage
|   |-- config/         Versioned study protocols and assignments
|   `-- deploy/         Study bundles, packaging, Docker and production startup
|-- data/
|   |-- manifests/      Historical dataset metadata and saved configurations
|   |-- raw/            Local generated audio and the full v4 corpus (ignored)
|   `-- processed/      Local features, protocols, models and analysis artifacts (ignored)
|-- validation/         Historical listening-subset preparation
|-- tools/              Dataset snapshot/archive utilities
|-- output/             Generated reports and document exports
|-- requirements.txt    Pinned synthesis/runtime dependencies
`-- render.yaml         Listening-application deployment configuration
```

The private reproduction bundle also installs a `reference/` directory. A Git clone does not contain all datasets, factory-derived presets, model checkpoints or generated viewers. Some small study playback assets and historical results are tracked.

## Requirements and setup

Commands below use **PowerShell**, run from the repository root unless stated otherwise.

| Workflow | Requirements |
| --- | --- |
| Exact v4 corpus reproduction | Windows x64, **Python 3.13.14**, Git, pinned `vita==0.0.5`, private reproduction ZIP, at least **80 GiB free** |
| Python analysis | Component-specific dependencies listed below; source audio/reference artifacts for the selected experiment |
| C2 GPU training | Compatible NVIDIA GPU and the CUDA overlay described in the [C2 runbook](c2_estimation/V4_README.md); CPU development is also supported |
| Listening frontend | Node.js **22.12+** on the Node 22 line used by the Docker build, and npm |
| Hosted listening application | Docker or the included Render configuration, persistent PostgreSQL, researcher credentials and matching study assets |

Clone the repository, then select the branch containing the workflow you need:

```powershell
git clone https://github.com/thithiramalsen/Synth-Inversion-RP-J26-DS-324.git
cd Synth-Inversion-RP-J26-DS-324
```

For ordinary analysis, create and activate a virtual environment before installing the relevant dependency file:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

| Component | Dependency file |
| --- | --- |
| Synthesis and shared scientific runtime | `requirements.txt` |
| C1 features | `c1_timbre/requirements.txt` |
| C2 models | `requirements.txt` plus `c2_estimation/requirements.txt` |
| C2 local human-study rehearsal | C2 dependencies plus `survey/backend/requirements.txt` for FastAPI, Uvicorn and HTTPX |
| C3 historical prototype | `c3_recommendation/requirements.txt` |
| C3 v4 | `c3_recommendation/requirements_v4.txt` |
| C4 historical triplet tools | `c1_timbre/requirements.txt` for feature preparation and NumPy; the export scorer uses the standard library |
| Survey API and Python tests | `survey/backend/requirements.txt` |
| Survey production container | `survey/deploy/requirements.txt` |

Install a selected file with `python -m pip install -r <path>`. These files serve different workflows and contain different pins; use separate environments where needed. **Exact corpus reproduction uses the dedicated `venv` procedure below.** Preserve its pinned runtime and frozen source files. The root requirements file is not an installer for the entire project.

## Datasets and audio contracts

### Historical pilot and current corpus

| Dataset/profile | Variable controls | Role and storage |
| --- | ---: | --- |
| `pilot_v1` | 8 | Historical 1,024-sound engineering dataset; mono 44.1 kHz, three-second PCM16 WAVs; used by the original C1/C2/C3 pipelines and development survey |
| `restricted_v2` | 12 | Preserved architecture A for characterization and comparison |
| `restricted_bend_v3` | 12 | Preserved Bend architecture with fixed filter-envelope sustain |
| `restricted_bend_sustain_v4` | 13 | Selected research domain; original 1,024-sound candidate pool and completed 131,072-sound corpus; FLOAT masters with versioned DC conditioning |

The 13 current controls are:

- Oscillator: wavetable position and Bend amount.
- Filter: cutoff, resonance and drive.
- Amplitude envelope: attack, decay, sustain and release.
- Filter envelope: amount, attack, decay and sustain.

The selected domain fixes one Basic Shapes oscillator, a low-pass filter, routing and other settings. Rendering uses **MIDI note 60**, velocity **0.8**, a **1.5-second held note**, **three-second recordings**, mono **44,100 Hz**, and scrambled Sobol sampling with seed **20260803**. Bounds remain research choices, rather than evidence of exhaustive perceptual coverage. See [generation details](generation/README.md) and [parameter units](generation/PARAMETER_UNITS.md).

### Read full-corpus audio through its adapter

The full corpus stores raw FLOAT audio and derives the canonical DC-conditioned float32 signal on read. It uses `raw_float_dc_on_read_v1`, `dc_highpass_10hz_v1`, and the recorded float32 underflow policy.

```python
import pandas as pd
from generation.corpus_audio import load_audio

manifest = pd.read_parquet("data/raw/corpus_v4/manifest.parquet")
audio, sample_rate = load_audio(manifest.iloc[0].to_dict(), verify=True)
```

Use **`sample_id`** to join audio, parameters and study records. The full-corpus schema exposes `raw_audio_path`; it does not provide the historical processed-WAV `audio_path` contract. Renaming that column would skip the required conditioning. C2 v4 uses the shared adapter; C3 v4 implements and verifies the same recorded processing contract in its reader. Historical pipelines require their original data or an explicit adaptation.

Study bundles can add a separately versioned playback/level policy. C1 study feature extraction reads the bundle's exact analysis signal without applying filtering or gain again. PCM16 browser playback copies do not replace the FLOAT research masters.

## Reproduce the full corpus

Start with the [fresh-clone quickstart](generation/TEAM_CLONE_QUICKSTART.md). Obtain **`team_v4_131072_SHARE.zip`** privately from the project maintainer. It contains the exact preset, frozen code, pinned requirements, parameter references and waveform references; Git alone is insufficient.

The setup command below is for a **fresh clone**. It verifies the supplied ZIP, restores frozen files, and backs up historical pilot metadata that must not be mistaken for locally generated audio. It refuses conflicting files or an existing corpus. Do not apply it to the original completed-dataset folder.

```powershell
# Confirm Python 3.13.14 before proceeding.
python --version
python -B generation/prepare_team_clone.py --bundle "C:\path\to\team_v4_131072_SHARE.zip" --apply
python -B generation/verify_reproduction.py --reference reference/clone_integrity.json --stage candidates

python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# Run generation only after the read-only check succeeds.
.\venv\Scripts\python.exe -B -u -m generation.generate_corpus --check --count 131072
.\venv\Scripts\python.exe -B -u -m generation.generate_corpus --generate --count 131072 --workers 4
```

Four workers are a starting point; adjust for your hardware. Rerun the identical `--generate` command after interruption to resume. The runner checks the recipe, saved parameters and waveforms, and rejects conflicting audio. This route renders all 131,072 sounds in a fresh clone; a separate pilot-generation stage is optional.

After completion, compare parameters and every raw/conditioned waveform with the supplied references:

```powershell
.\venv\Scripts\python.exe -B generation/verify_parameter_reference.py --reference reference/parameters_full.parquet --manifest data/raw/corpus_v4/manifest.parquet
.\venv\Scripts\python.exe -B -u -m generation.audit_full_corpus --count 131072 --workers 4 --reference reference/full_waveform_reference.json
```

The raw audio payload is approximately **64.6 GiB**; allow additional space for feature caches, checkpoints and backups. Outputs are under `data/raw/corpus_v4/`: `raw_float/`, `recipe.json`, incremental `chunks/`, final CSV/Parquet manifests and `summary.json`. Imported prefix rows retain their original raw paths, so preserve those folders too. Checkpoints are authoritative during an interrupted run.

Matching settings or a small prefix does not establish full audio equality across computers; the complete waveform comparison does. See the [teammate handoff](generation/TEAM_DATASET_HANDOFF.md) for the extracted-package route and [full-run internals](generation/FULL_DATASET_RUNBOOK.md) for storage and recovery details. Earlier runbook status notes are historical; the completed-corpus handoff describes the current reproduction route.

## Research components

### C1: Timbre analysis

Implemented features include spectral centroid, spectral rolloff, RMS, zero-crossing rate and MFCC summaries. The historical analysis explores filter cutoff versus brightness-related measurements. Predicting the four human-rated descriptors remains a later modelling stage.

After installing `c1_timbre/requirements.txt`, run the historical analysis with its `pilot_v1` manifest and audio:

```powershell
python c1_timbre/feature_extraction.py --manifest data/manifests/pilot_v1.csv --output-dir output/c1-development
```

This writes feature CSVs and a cutoff/centroid figure. For a separately prepared C1 study bundle:

```powershell
python -B -m c1_timbre.extract_pilot_features --bundle data/processed/c1_pilot_v1/bundle.json --output data/processed/c1-features.csv
```

The bundle extractor verifies provenance and refuses to overwrite its output. Saved historical C1 results cover 128 sounds, not the full v4 corpus. Quiet-frame spectral handling needs a versioned revision before treating FLOAT and PCM16 feature summaries as interchangeable. See the [C1 README](c1_timbre/README.md) and [research plan](c1_timbre/C1_RESEARCH_AND_ENGINEERING_PLAN.md).

### C2: Synthesizer parameter estimation

The current v4 pipeline maps fixed-reference log-mel spectrograms to 13 controls. It includes a deterministic CNN, a three-member probabilistic ensemble, reconstruction residuals, local parameter-sensitivity probes, and development calibration of per-control correctness probabilities.

The deterministic model was trained on **98,304 clips** and selected on **4,096 inverse-validation clips**. Its reported macro MAE is **0.126112** in research-range coordinates, where `z = (Vital_normalized - lower_bound) / (upper_bound - lower_bound)`. This is a validation result, not a perceptual similarity score. See [full baseline results](c2_estimation/FULL_BASELINE_RESULTS.md) and [development calibration results](c2_estimation/VALIDATION_RESULTS.md).

The locked C2 partition is:

| Partition | Clips | Purpose |
| --- | ---: | --- |
| Training | 98,304 | Model fitting; includes the previously studied v4 prefix |
| Calibration | 16,384 | Calibration pool; 2,048 clips used in the completed diagnostic workflow |
| Inverse validation | 4,096 | Inverse-model selection |
| Reliability validation | 4,096 | Development calibration selection; 512 diagnostic clips |
| Reserved test | 8,192 | Final evaluation, still pending |

To run a small CPU development experiment, first install the root and C2 requirements in the chosen analysis environment and provide the verified corpus. **Preparation currently also requires the private parameter reference at `data/processed/team_handoff_v4_131072/parameters_full.parquet`.** Fresh-clone setup installs that table under `reference/`; provide an identical copy at the C2-required path before preparation.

```powershell
python -B -m c2_estimation.v4.data
python -B -m c2_estimation.v4.features --cache data/processed/c2_v4/features_development_v1 --scope development --workers 4
python -B -m c2_estimation.v4.baseline --cache data/processed/c2_v4/features_development_v1 --output data/processed/c2_v4/baseline_readme_example --epochs 8 --patience 4 --batch-size 64 --threads 4 --device cpu
```

Use a new model output directory for a new experiment. The [v4 runbook](c2_estimation/V4_README.md) covers full training, the dedicated `.venv-c2` CUDA overlay, ensembles, resumable diagnostics and calibration. Large generated models and feature caches are excluded from Git.

If the generated viewer has been supplied or built locally, replay six saved examples without training:

```powershell
python -B -m http.server 8765 --bind 127.0.0.1 --directory data/processed/c2_v4/viewer_v1
```

Open [the local C2 viewer](http://127.0.0.1:8765/). This interface displays saved predictions and verified audio; it does not accept uploads or run live inference. See [demo instructions](c2_estimation/DEMO.md).

The separate [C2 human-study rehearsal](c2_estimation/human_study/README.md) uses port 8766 and its own database. With its generated bundle and additional API dependencies available, launch it with:

```powershell
python -B -m c2_estimation.human_study.server
```

All responses in that application remain rehearsal data, with research collection disabled.

The original `python c2_estimation/pipeline.py` remains the **eight-control `pilot_v1` baseline**. Its checkpoints, split and test scores are historical results, separate from v4.

### C3: Similar-sound recommendation

The historical prototype retrieves similar patches using MFCC audio features, then applies **maximal marginal relevance (MMR)** to return parameter-diverse alternatives from the retrieved pool. C2 predictions do not replace audio retrieval.

With `c3_recommendation/requirements.txt` installed and the historical pilot audio available:

```powershell
python c3_recommendation/pipeline.py
python c3_recommendation/pipeline.py --query-audio "C:\path\to\isolated_synth.wav"
```

Outputs include the candidate database, baseline/MMR recommendations, comparison tables and the relevance/diversity tradeoff under `c3_recommendation/outputs/`. The [C3 README](c3_recommendation/README.md) describes this historical prototype and its measured 32-query result.

The newer **13-control v4 implementation** lives in `src/c3/`, `scripts/`, and `configs/c3_v4.yaml`. It provides frozen bank/validation/test assignments, normalized parameter distances, top-k/MMR/random selection, streaming audio access, MFCC26 and log-mel features, and validation diagnostics. Its references and generated artifacts must be supplied or recreated separately. The default configuration expects the private `reference/` files even when reading audio from `corpus_v4`.

After installing `c3_recommendation/requirements_v4.txt`, checking those paths, and completing the audio gate documented in the source and decisions:

```powershell
python c3_recommendation/scripts/00_inspect_data.py
python c3_recommendation/scripts/02_make_splits.py
# Feature commands require the verified, completed corpus.
python c3_recommendation/scripts/06_extract_features.py --workers 4
python c3_recommendation/scripts/06_feature_diagnostics.py
```

The audio gate is `scripts/05_audio_gate.py`; it requires a saved successful official waveform-comparison log. See [data contracts](c3_recommendation/docs/DATA_CONTRACT.md) and [decisions and measured development checks](c3_recommendation/docs/DECISIONS.md). Proxy smoke-test results are implementation checks. Final v4 evaluation is still locked by `final_test.enabled: false`. C3 splits are separate from C2 splits and must be coordinated before cross-component evaluation.

### C4: Perceptual similarity

C4 compares audio-similarity measures with relative human judgments: listen to a reference and choose which candidate sounds closer. The historical tools select ten MFCC-based development triplets and score matching-format response exports:

```powershell
# Requires historical C1 features and the pilot dataset.
python c4_metric/select_triplets.py
python c4_metric/mfcc_baseline.py "C:\path\to\c4_triplets_responses.csv"
```

These commands use the historical schema. They are not the analysis pipeline for current participant exports.

The current `/c4` survey uses a frozen **200-triplet CLAP bank of real audio**. `c4_metric/synthetic_data/` also contains simulated response/session fixtures; those answers must never be reported as human evidence. Regenerating the bank requires the full local corpus and additional model dependencies and may replace generated outputs; follow the [fixture/bank documentation](c4_metric/synthetic_data/README.md). A learned human-aligned metric remains future work.

## Run the listening application

### Current instruments

| Route | Current protocol | Per-listener tasks |
| --- | --- | --- |
| `/pilot` | C1 `c1_20_participants_v1`: 64-sound bank; brightness, roughness, percussiveness and sustainedness on 1–7 scales | 20 unique study sounds and three practices; no hidden repeats |
| `/c4` | C4 `c4_clap_participants_v1`: 200-triplet bank | 20 unique comparisons, two hidden repeats and two practices; A/B/cannot-decide plus confidence |
| `/researcher` | Public researcher landing page | Navigation to the researcher tools |
| `/pilot/admin`, `/c4/admin` | Authenticated study administration | Assignment management, response inspection and study administration |

The current C1/C4 participant protocols request headphones and a quiet setting but omit the six-trial headphone screen retained by older versions. C1 includes 26 assignment slots; its first 16 assignments cover each bank sound five times. C4 includes 100 assignments with a planned 50–100 completed listeners. These are study-design targets, not achieved recruitment counts.

Use the current [C1 participant guide](survey/C1_PARTICIPANT_DEPLOYMENT.md), [C4 participant guide](survey/C4_PARTICIPANT_DEPLOYMENT.md), and versioned configs for these flows. Older review and development instructions describe different designs.

### Local development

A survey-only environment needs the backend requirements and tracked study playback assets; it does not need the full synthesis corpus to serve the current packaged instruments.

```powershell
python -m pip install -r survey/backend/requirements.txt
npm ci --prefix survey/frontend

python -B -m survey.deploy.build_c1_participants --check
python -B -m survey.deploy.build_c4_participants
python -B -m survey.deploy.build_c4_participants --check

# Keep new participant entry closed during local code exploration.
$env:SURVEY_C1_OPEN = "0"
$env:SURVEY_C4_OPEN = "0"
python -m uvicorn main:app --app-dir survey/backend --reload --host 127.0.0.1 --port 8000
```

The C4 builder materializes the tracked playback clips locally; it does not render synth audio. In a second terminal:

```powershell
npm run dev --prefix survey/frontend
```

Open [C1](http://localhost:5173/pilot) or [C4](http://localhost:5173/c4). New entry remains closed with the settings above. For a participant-flow rehearsal, use the dedicated preparation/run instructions in the component guides. The Vite development server sends API requests to port 8000; built frontend assets use the same origin as the API. `VITE_API_URL` can override the public API URL.

### Configuration and storage

Environment variables are read from the process; **`.env` files are not loaded automatically**. [The survey example](survey/.env.example) is a configuration reference, not a ready-to-run current participant configuration. Set credentials in your local environment or hosting secrets.

| Variable | Purpose |
| --- | --- |
| `SURVEY_DATABASE_PATH` | Local SQLite file; defaults to `survey/backend/survey.db` |
| `SURVEY_DATABASE_URL` | Persistent PostgreSQL connection; takes precedence over SQLite |
| `SURVEY_ADMIN_TOKEN` | Random secret of at least 32 characters for admin access and, by default, invitation encryption |
| `SURVEY_INVITATION_SECRET` | Optional separate persistent invitation-encryption secret |
| `SURVEY_RESEARCHER_USERNAME` | Researcher login name |
| `SURVEY_RESEARCHER_PASSWORD_HASH` | Salted password hash generated by `python survey/deploy/make_password_hash.py` |
| `SURVEY_C1_BUNDLE`, `SURVEY_C1_CONFIG` | Matching C1 stimulus bundle and protocol |
| `SURVEY_C4_BUNDLE`, `SURVEY_C4_CONFIG` | Matching C4 stimulus bundle and protocol |
| `SURVEY_C1_OPEN`, `SURVEY_C4_OPEN` | New-entry switches; current participant defaults are `1` |
| `SURVEY_REMOTE_MODE` | Disables historical development APIs and API documentation |
| `SURVEY_ALLOWED_ORIGINS` | Allowed frontend origins for cross-origin API access |

Keep database backups with the matching protocol/audio versions and persistent encryption secret. Response exports and administration require authentication. Credentials, private invitations and participant records must remain outside Git and frontend environment variables. Historical study APIs are disabled in remote mode.

### Build and deployment

```powershell
npm run build --prefix survey/frontend
docker build -f survey/deploy/Dockerfile -t synth-listening-survey .
```

The Docker build tests/builds the frontend and packages the minimal Python service with verified playback assets. Production startup requires PostgreSQL, researcher credentials and an admin secret, and checks bundle audio hashes. `render.yaml` defines the service, participant bundle/config paths and `/api/health` check. It currently enables both participant entry switches; review the intended release settings before deployment.

Follow the [deployment guide](survey/deploy/README.md), current participant guides and [shared-assignment guide](survey/SHARED_ASSIGNMENTS.md) for persistent storage, researcher access and recruitment operations. Current protocol files record institutional review status as `not_recorded`; participant-mode software is not evidence of approval or completed participant research.

## Tests and verification

Use the environment containing the dependencies for the selected suite. These commands test implementation behavior; they do not rerun full training or establish scientific validity.

```powershell
# Generation and historical/current C2 implementations
python -m unittest discover -s generation/tests -v
python -m unittest discover -s c2_estimation/tests -v

# Historical C3 and v4 recommendation tooling
python -m unittest discover -s c3_recommendation/tests -v
python -m pytest c3_recommendation/tests_v4 -p no:cacheprovider

# Survey API, preparation, deployment and UI
python -m pytest survey/backend/tests survey/tests -p no:cacheprovider
npm test --prefix survey/frontend
npm run build --prefix survey/frontend

# Isolated C2 human-study rehearsal
python -m unittest c2_estimation.human_study.test_study -v
```

C2 CUDA checks skip when a compatible GPU environment is unavailable. PostgreSQL integration tests require `SURVEY_TEST_POSTGRES_URL` pointing to a dedicated test database. Full-corpus integrity and cross-machine reproduction use the parameter and waveform verification commands above, separately from unit tests.

## Research limits and reproducibility

- **Scope:** current models concern a restricted Vital preset, fixed note and rendering conditions. Generalization to arbitrary instruments, notes, effects or recordings is unestablished.
- **Identifiability:** different parameter combinations can produce similar audio. Low audio distance does not prove recovery of the original controls.
- **Evidence:** C2's current v4 results are development/validation results; its final reserved test remains unevaluated. Historical eight-control test results do not transfer to v4.
- **Human data:** real study audio, rehearsal responses, synthetic answers and completed participant evidence have distinct roles. Preserve their study IDs and analysis exclusions.
- **Data integrity:** retain stable IDs, frozen splits, presets, recipes, package versions and checksums. Use new versioned output directories when changing an experiment; do not bypass hash checks or replace local hashes with reference values.
- **Storage:** generated audio, features, model weights and private references are generally ignored by Git. A reproducible checkout also needs the appropriate external artifacts or generation steps.

No repository-wide license file is currently included. Confirm reuse and redistribution terms with the project maintainers, including terms for third-party software, model weights and factory-derived Vital assets.

## Documentation index

| Topic | Start here |
| --- | --- |
| Fresh-clone corpus reproduction | [Team clone quickstart](generation/TEAM_CLONE_QUICKSTART.md) |
| Shared parameters and waveform verification | [Dataset handoff](generation/TEAM_DATASET_HANDOFF.md) |
| Synthesis profiles and parameter interpretation | [Generation](generation/README.md), [parameter units](generation/PARAMETER_UNITS.md) |
| C1 research and features | [C1 README](c1_timbre/README.md), [teammate handoff](c1_timbre/C1_TEAMMATE_HANDOFF.md) |
| C2 implementation and results | [v4 runbook](c2_estimation/V4_README.md), [baseline results](c2_estimation/FULL_BASELINE_RESULTS.md), [validation results](c2_estimation/VALIDATION_RESULTS.md) |
| C2 explanation and demonstrations | [Study guide](c2_estimation/notes/COMPONENT_STUDY_GUIDE.md), [saved-results demo](c2_estimation/DEMO.md), [human-study rehearsal](c2_estimation/human_study/README.md) |
| C3 pilot and v4 contracts | [Historical prototype](c3_recommendation/README.md), [data contract](c3_recommendation/docs/DATA_CONTRACT.md), [decisions](c3_recommendation/docs/DECISIONS.md) |
| C4 baselines, bank and fixtures | [C4 README](c4_metric/README.md), [synthetic-data notes](c4_metric/synthetic_data/README.md), [triplet protocol](survey/C4_REVIEW_PROTOCOL.md) |
| Current participant releases | [C1 deployment](survey/C1_PARTICIPANT_DEPLOYMENT.md), [C4 deployment](survey/C4_PARTICIPANT_DEPLOYMENT.md) |
| Hosting and shared recruitment | [Deployment](survey/deploy/README.md), [shared assignments](survey/SHARED_ASSIGNMENTS.md) |
| Earlier project milestones | [Progress report](PROJECT_PROGRESS_REPORT.md); dated sections preserve earlier project states |
