# C3 on the existing study services

C3 (diversity-aware patch recommendation, owner: D.A.V.P. Waidyarathne) is added to the
existing participant and researcher services as a **rehearsal-only** study, the same way C2 was. No new Render
service, database, secret or login is needed, and C1/C2/C4 behaviour is unchanged.

| Address | What it is |
|---|---|
| `/c3/` | Participant preview. Needs a C3 invitation code (C1/C2/C4 codes do not work). |
| `/c3/admin` | C3 researcher area — the site's shared researcher account. Create codes, see runs, export. |
| `/c3/?view=researcher` | Researcher self-review (signed in). Only here can the headphone check be skipped (for presentations); skipped runs are marked and excluded from analysis. |

On the separate researcher service, `/c3/` requires researcher sign-in and selects
self-review. `/c3/admin` uses that service's existing researcher account, lists saved
runs and offers self-review/export without preview invitations. C3 uses the existing
rehearsal database, separate from the participant service. See the
[researcher deployment guide](RESEARCHER_REHEARSAL.md#c3-researcher-self-review).

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

Shared integration:
- `survey/backend/main.py`: 3 lines (import, initialise tables at start-up, `app.mount("/c3", ...)`)
- `survey/deploy/Dockerfile`: 1 line (`COPY survey/backend/c3_web/ ...`)

- Shared study/researcher navigation includes C3; its static pages link back to the other panels.
- `c1_researcher_rehearsal.py` enables researcher-only C3 access using the dedicated rehearsal cookie.
- `.dockerignore` includes C3 pages and the frozen bundle; `.gitattributes` pins its original
  CRLF JSON bytes on Linux so hash verification and existing session fingerprints stay valid.

## Data separation

C3 uses its own tables in the shared database: `c3_v2_metadata`, `c3_v2_sessions`,
`c3_v2_invites`. Invitation codes are stored encrypted in the shared `invitation_code_vault` under
component `c3`. A test checks that a C3 session changes no other table. The stored fingerprint
covers the bundle and the study protocol; changing stimuli, questions, counterbalancing or the
operating point requires new versioned tables (`c3_v3_*`), keeping previous records.

## Verify before deploying (repository root, PowerShell)

```powershell
.\venv\Scripts\python.exe -B -m unittest discover -s survey/backend/tests -p "test_c3_hosted.py" -v
.\venv\Scripts\python.exe -B -m unittest discover -s survey/backend/tests -p "test_c3_researcher_rehearsal.py" -v
.\venv\Scripts\python.exe -B -m unittest discover -s survey/backend/tests -p "test_*.py"
npm test --prefix survey/frontend
npm run build --prefix survey/frontend
```

Both Render services deploy `c1-pilot-deployment` (see `render.yaml` and
`survey/deploy/render.researcher-rehearsal.yaml`). Merge through the team's usual
pull request and redeploy the existing services with their existing secrets and database URLs.
After deployment, both `/api/health` checks pass. On the participant service, `/c3/` loads,
`/c3/api/info` reports `researcher_only=false` and research disabled, and C1/C2/C4 retain
their current modes. On the researcher service, verify the signed-out gates, shared login,
self-review, resume and export described in the researcher guide.
