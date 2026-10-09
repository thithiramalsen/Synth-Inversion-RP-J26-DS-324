# Persistent C1 review deployment

Prepared on 9 October 2026. **Not yet deployed:** hosting account setup, a real
PostgreSQL integration run and the remote restart check remain outstanding.
The current Cloudflare Quick Tunnel is still a separate, temporary preview.

Use Render's free Docker web service for a stable HTTPS address and Neon's free
PostgreSQL database for responses, invitations and researcher accounts. This
continues running independently of the researcher's PC. Render builds the site
again when a commit is pushed to `c1-pilot-deployment`.

## Set up once

1. Create free [Render](https://dashboard.render.com/) and
   [Neon](https://console.neon.tech/) accounts. Connect Render to GitHub with
   access to `thithiramalsen/Synth-Inversion-RP-J26-DS-324`.
2. In Neon, create a **review** project/database. Prefer a region near Render's
   Singapore region. Copy its PostgreSQL connection string with TLS enabled
   directly into the host's secret settings; never put it in Git or chat.
3. Test the PostgreSQL adapter against a **dedicated test database**, as described
   below. The tests create and remove randomly named schemas, not public tables.
4. Commit the survey changes, `render.yaml`, `.dockerignore` and
   `survey/deploy/study/` on `c1-pilot-deployment`, then push that branch. Include
   the runtime source changes, not just the newly added deployment files.
5. In Render, select **New > Blueprint**, choose the connected GitHub repository
   and `c1-pilot-deployment`, and use the root `render.yaml`. Check that the web
   service plan is **Free**. The blueprint does not create a paid database.
6. Supply `SURVEY_DATABASE_URL` from Neon and `SURVEY_RESEARCHER_PASSWORD_HASH`.
   Generate the latter locally by running:

   ```powershell
   .\venv\Scripts\python.exe -B survey/deploy/make_password_hash.py
   ```

   The password prompts are hidden. Paste only the resulting hash into Render.
   The username defaults to `researcher`. Render generates `SURVEY_ADMIN_TOKEN`.
   Keep these values in backend environment settings, never frontend variables.
7. Deploy and open Render's assigned HTTPS address at `/pilot`. Researcher login
   is at `/pilot/admin`. Issue fresh **review** participant invitations there.
   Existing local invitation codes and browser sessions belong to the local
   database/origin; they are not transferred automatically.

The hosted version deliberately uses `c1_review_20_v1.json`, rehearsal study ID
`c1_20_review_v1`, and `SURVEY_C1_OPEN=0`. Review sessions work in rehearsal mode
and stay excluded from research analysis. Supervisor approval is still pending.

## Check before sharing the persistent link

- Confirm the review notice, login, invitation issuance and all audio playback.
- Complete a clearly labelled review session and download response/session
  exports. Check the 20 unique study sounds, 3 practice sounds and break after 10.
- Restart/redeploy the service. Check the same session, answers and invitation
  records still exist, and that browser resume works at the same HTTPS origin.
- Store a database backup privately and verify restoring it into an isolated
  test database. CSV exports support analysis; they do not recreate login,
  invitation and session state. Do not rely solely on provider recovery windows.

This remote restart/backup check has **not** been completed by local unit tests.

## Future updates

Make and test changes, then commit and push to `c1-pilot-deployment`. Render's
`autoDeployTrigger: commit` rebuilds that branch; merely saving local files does
not update the public website. Keep the same Neon connection string to retain
responses. Startup creates missing tables; it does not reset existing tables.

UI fixes can be redeployed normally. Changes to sounds, assignments, descriptor
definitions or protocol require a new version; existing sessions retain their
protocol snapshot. Do not overwrite a bundle that already has responses.

For formal collection, finalize the production configuration, record the actual
approval outcome and use a separate production database and invitation set.
Package the production bundle in a **new** versioned directory, update both
Docker asset-copy rules and the bundle/config environment paths, verify it, then
deliberately open collection. Do not relabel review responses as research data.

## What is uploaded

`study/` contains the byte-identical review `bundle.json` and 74 playback WAVs:
64 study sounds, 3 practice sounds, 6 headphone-screen files and 1 volume reference.
Total size is about 22.4 MB. These files are intentionally included in Git.

The deployment excludes original candidate datasets, FLOAT feature masters,
local databases and private access files. Feature-path metadata remains in the
original bundle for provenance; feature analysis uses the original local bundle,
not this playback-only deployment package. `.dockerignore` limits build contents.

To package another approved bundle without overwriting this one:

```powershell
python -B survey/deploy/pack_study.py --source PATH_TO_NEW_BUNDLE --output NEW_DIRECTORY
```

Both packaging and host startup verify every playback hash. The production
entrypoint refuses to start without PostgreSQL and researcher credentials.
Local `survey.run_rehearsal` continues to use SQLite when no database URL is set.

## Storage verification

SQLite/API regression tests:

```powershell
.\venv\Scripts\python.exe -B -m unittest discover -s survey/backend/tests -v
.\venv\Scripts\python.exe -B -m pytest survey/tests/test_deployment.py -q
```

For PostgreSQL, set `SURVEY_TEST_POSTGRES_URL` privately in the local environment
to a **direct connection to a dedicated test database**, then run:

```powershell
.\venv\Scripts\python.exe -B -m unittest discover -s survey/backend/tests -p test_postgres.py -v
```

Without that variable these tests explicitly skip. They run the existing C1
workflow on PostgreSQL, including correction, exports, registration, expiry and
idempotent initialization, plus concurrent duplicate submissions, concurrent
invitation claims and expiry timestamp precision. Each test has its own schema.
Do not set the test URL to a real participant database.

To validate the actual image where Docker is working:

```powershell
docker build -f survey/deploy/Dockerfile -t c1-pilot-review .
```

Docker Desktop's engine returned HTTP 500 locally during preparation, so the
container build still needs verification on Render or a working Docker engine.

## Free-plan limits

This gives a stable deployment, not a promise of free hosting forever. Render
free services sleep after 15 idle minutes, so the first visit after inactivity
can take around a minute. The disk is ephemeral; the Neon database is what
preserves responses. Render's own free PostgreSQL expires after 30 days, which
is why it is not used here. Stay within both providers' current free allowances.

Sources: [Render free services](https://render.com/docs/free),
[Render deployment and branch settings](https://render.com/docs/blueprint-spec),
[Neon free plan update](https://neon.com/blog/neon-free-plan-1-gb-per-project).
