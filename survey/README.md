# Listening Survey

Local React/Vite + FastAPI research listening instruments. Audio remains in the shared research dataset and is served by the backend; WAV files are not copied into React.

## Implemented studies

- `pilot_quality`: all 128 samples in `data/manifests/pilot_v1.csv`, randomized per session. Records the first obvious issue, a 1-5 quality rating, an optional comment and playback starts.
- `c1_descriptors`: a randomized 20-sample internal prototype drawn from the same 128-sample pilot manifest. Records four 1-7 bipolar ratings (dark/bright, smooth/rough, thin/warm and short/sustained), an optional comment and playback starts.

The current 128-sample manifest is the directly generated `pilot_v1` Sobol pilot (`sampling_seed: 20260803`), not a subset selected from a validated 1,024-sample dataset. When the planned 1,024-sample development manifest is available, document and configure the intended listening subset before collecting formal ratings.

Both studies are for internal development testing only until supervisor and ethics requirements permit broader participant recruitment.

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

These routes are not authenticated. Protect or disable them before hosting the service on a network.

## Tests

```powershell
python -m pytest survey/backend/tests
cd survey/frontend
npm run build
```

The API regression suite verifies the nested audio URL, WAV delivery, stable sample-ID session snapshots, strict pilot validation and C1 response/export flow.
