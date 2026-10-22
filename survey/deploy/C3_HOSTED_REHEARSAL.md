# C3 on the existing participant service

C3 (diversity-aware patch recommendation, owner: D.A.V.P. Waidyarathne) is added to the
existing participant service as a **rehearsal-only** study, the same way C2 was. No new Render
service, database, secret or login is needed, and C1/C2/C4 behaviour is unchanged.

| Address | What it is |
|---|---|
| `/c3/` | Participant preview. Needs a C3 invitation code (C1/C2/C4 codes do not work). |
| `/c3/admin` | C3 researcher area — the site's shared researcher account. Create codes, see runs, export. |
| `/c3/?view=researcher` | Researcher self-review (signed in). Only here can the headphone check be skipped (for presentations); skipped runs are marked and excluded from analysis. |

Research collection is **disabled**. Every record is rehearsal data (`excluded_from_research`,
`analysis_include=false`). Do not recruit research participants with this release; that needs
ethics approval and a separately reviewed release.

## What was added

New, C3-owned files:
- `survey/backend/c3_design.py` — frozen study rules (copy of `c3_recommendation/human_study/design.py`; a test checks they match)
- `survey/backend/c3_flow.py` — the study server, mounted at `/c3`
- `survey/backend/c3_web/` — participant page and researcher area (plain HTML/JS, no React)
- `survey/deploy/study/c3_rehearsal_v2/` — frozen stimulus bundle (validation sounds, 89 files, ~25 MB; every file hash-checked at start-up)
- `survey/backend/tests/test_c3_hosted.py`

Shared files — additive lines only:
- `survey/backend/main.py`: 3 lines (import, initialise tables at start-up, `app.mount("/c3", ...)`)
- `survey/deploy/Dockerfile`: 1 line (`COPY survey/backend/c3_web/ ...`)

The React frontend and site navigation are **not** changed; C3 is reached directly at `/c3/`.
The researcher-only rehearsal service (`c1_researcher_rehearsal.py`) is not changed, so C3 is not
available there.

## Data separation

C3 uses its own tables in the shared database: `c3_v2_metadata`, `c3_v2_sessions`,
`c3_v2_invites`. Invitation codes are stored encrypted in the shared `invitation_code_vault` under
component `c3`. A test checks that a C3 session changes no other table. The stored fingerprint
covers the bundle and the study protocol; changing stimuli, questions, counterbalancing or the
operating point requires new versioned tables (`c3_v3_*`), keeping previous records.

## Verify before deploying (repository root, PowerShell)

```powershell
.\venv\Scripts\python.exe -B -m unittest discover -s survey/backend/tests -p "test_c3_hosted.py" -v
.\venv\Scripts\python.exe -B -m unittest discover -s survey/backend/tests -p "test_*.py"
```

Render deploys the `c1-pilot-deployment` branch (see `render.yaml`). Merge through the team's usual
pull request. After deployment: `/api/health` passes, `/c3/` loads, `/c3/api/info` reports
`research_collection_enabled: false`, and C1/C2/C4 pages behave as before.
