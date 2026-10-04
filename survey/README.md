# Listening Survey

Local React/Vite + FastAPI research listening instruments. Audio remains in the shared research dataset and is served by the backend; WAV files are not copied into React.

## Implemented studies

- `pilot_quality`: samples from `data/manifests/pilot_v1.csv`, randomized per session and subject to the study configuration's trial limit. Records the first obvious issue, a 1-5 quality rating, an optional comment and playback starts.
- `c1_descriptors`: a randomized 20-sample internal prototype drawn from the shared pilot manifest. Records four 1-7 bipolar ratings (dark/bright, smooth/rough, thin/warm and short/sustained), an optional comment and playback starts.
- `c4_triplets`: ten frozen development triplets from `c4_metric/development_triplets.csv`, randomized per session. Each trial displays a reference plus Candidates A and B and records an A/B choice, 1-5 confidence, an optional comment and separate playback starts for all three sounds.

As of 26 September 2026, the shared `pilot_v1` manifest contains 1,024 directly generated Sobol pilot sounds (`sampling_seed: 20260803`). The earlier 128-sound documentation is obsolete. The intended formal listening subset and balanced assignments still need to be frozen before collection.

The proposed C1 study is specified in [C1_RESEARCH_DESIGN.md](../c1_timbre/C1_RESEARCH_DESIGN.md). The existing four-scale questionnaire has not been converted to that design. Preserve its historical response meanings and introduce any revised scales under a new study version; changing the JSON alone is insufficient because answer validation and the frontend also encode the current scales.

All studies are for internal development testing only until supervisor and ethics requirements permit broader participant recruitment.

## Run locally

From the repository root, activate or recreate the root virtual environment and install the backend requirements:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r survey/backend/requirements.txt
python -m uvicorn main:app --app-dir survey/backend --reload --port 8000
```

In a second terminal:

```powershell
cd survey/frontend
npm install
npm run dev
```

Open <http://localhost:5173>.

The SQLite database is created at `survey/backend/survey.db` and is ignored by Git. New responses use the flexible `study_responses` table; the original `responses` table is retained only to preserve existing local development data.

## Exports

While the service is strictly local, CSV exports are available at:

- All studies: <http://localhost:8000/api/admin/export>
- Pilot quality: <http://localhost:8000/api/admin/export/pilot_quality>
- C1 descriptors: <http://localhost:8000/api/admin/export/c1_descriptors>
- C4 triplets: <http://localhost:8000/api/admin/export/c4_triplets>

These routes are not authenticated. Protect or disable them before hosting the service on a network.

## Tests

```powershell
python -m pytest survey/backend/tests
cd survey/frontend
npm run build
```

The API regression suite verifies WAV delivery, stable trial-ID session snapshots, strict study-specific validation, C1 response/export flow, and C4's three audio sources, response metadata and separate playback counts.
