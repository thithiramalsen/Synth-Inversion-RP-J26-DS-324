# Listening Survey

React/Vite + FastAPI research listening instruments. Audio is served by the backend;
WAV files are not bundled into React.

## Current C1 pilot and local rehearsal

The new `/pilot` instrument uses a separate versioned audio bundle and database
tables. It implements consent/background questions, volume setup, a six-trial
headphone screen, three practice clips, brightness/roughness/percussiveness
ratings, hidden repeats, a break, feedback, resume and withdrawal. Researcher
exports and invitation management require a bearer access token.

**Start with [C1_PILOT_RUNBOOK.md](C1_PILOT_RUNBOOK.md).** The local rehearsal uses
existing diagnostics, six study sounds, three practice sounds and one repeat.
It is not the research stimulus set and its responses are excluded from analysis.
The production design is 64 study sounds, 16 completed listeners, 32 unique sounds
plus four repeats per listener, and eight primary listeners per sound.

The new 1,024-candidate pool remains on hold. The production bundle is not yet
built, the site is not publicly deployed, and participant contacts, retention,
eligibility and institutional review details need finalization. The rationale and
remaining checklist are in [C1_PILOT_READINESS.md](C1_PILOT_READINESS.md).

## Preserved development instruments

- `pilot_quality`: all 1024 samples in `data/manifests/pilot_v1.csv`, randomized per session. Records the first obvious issue, a 1-5 quality rating, an optional comment and playback starts.
- `c1_descriptors`: a randomized 20-sample internal prototype drawn from the same 1024-sample pilot manifest. Records four 1-7 bipolar ratings (dark/bright, smooth/rough, thin/warm and short/sustained), an optional comment and playback starts.
- `c4_triplets`: ten frozen development triplets from `c4_metric/development_triplets.csv`, randomized per session. Each trial displays a reference plus Candidates A and B and records an A/B choice, 1-5 confidence, an optional comment and separate playback starts for all three sounds.

The current 1024-sample `pilot_v1` manifest is the eight-control engineering test
(`sampling_seed: 20260803`). The selected thirteen-control `restricted_bend_sustain_v4` architecture
is documented in [generation/README.md](../generation/README.md). These historical
instruments still use the old dataset. The separate `/pilot` flow must not be
confused with `c1_descriptors` or its earlier bipolar scales.

All studies are for internal development testing only until supervisor and ethics requirements permit broader participant recruitment.

## Run the preserved development instruments locally

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

These routes now require `Authorization: Bearer <SURVEY_ADMIN_TOKEN>`; set an
unguessable environment token of at least 32 characters before starting the
backend. The `/admin` page accepts it without storing it. When `SURVEY_REMOTE_MODE=1`,
all historical API routes above are disabled; use the new `/pilot/admin` instead.

## Tests

```powershell
python -m pytest survey/backend/tests survey/tests -p no:cacheprovider
cd survey/frontend
npm run build
```

The API regression suite verifies WAV delivery, stable trial-ID session snapshots, strict study-specific validation, C1 response/export flow, and C4's three audio sources, response metadata and separate playback counts.
