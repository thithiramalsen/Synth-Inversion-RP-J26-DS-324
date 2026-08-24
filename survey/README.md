# Listening Survey

Local React/Vite + FastAPI pilot listening instrument. The backend reads `data/manifests/pilot_v1.csv` and serves WAV files from their existing pipeline location; no audio is copied into the frontend.

## Run locally

From the repository root, install backend packages with `python -m pip install -r survey/backend/requirements.txt`, then start the API:

```powershell
python -m uvicorn main:app --app-dir survey/backend --reload --port 8000
```

In a second terminal:

```powershell
cd survey/frontend
npm install
npm run dev
```

Open http://localhost:5173. The SQLite database is created at `survey/backend/survey.db` and is ignored by git. CSV export is available at http://localhost:8000/api/admin/export.