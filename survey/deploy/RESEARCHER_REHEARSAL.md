# C1 and C4 researcher surveys in one deployment

The existing `synth-c1-researcher-rehearsal` Render service now serves both
researcher surveys using the existing `c1_researcher_rehearsal` Neon database.
The service name and startup command stay the same so the deployed C1 instance
can be upgraded in place.

| Database | Contents |
| --- | --- |
| `c1_review` | Existing participant C1 and C4 surveys, unchanged |
| `c1_researcher_rehearsal` | Researcher-only C1 and C4 surveys |

One researcher login works across both admin panels. Invitations, assignments,
responses and exports remain separate for C1 and C4. All researcher responses
are labelled rehearsal, attributed to their researcher and excluded from
participant analysis.

## Update the existing researcher service

1. Commit/push the changes and merge them into `c1-pilot-deployment`.
2. Redeploy the **existing** `synth-c1-researcher-rehearsal` service. Keep its
   current Blueprint (`survey/deploy/render.researcher-rehearsal.yaml`),
   `SURVEY_REHEARSAL_DATABASE_URL`, admin token and researcher credentials.
   Keep using the connection to `c1_researcher_rehearsal`.
3. Open the same service URL at `/researcher`. Use `/pilot/admin` for C1 and
   `/c4/admin` for C4. Signing in once gives access to both.
4. Create fresh researcher survey invitations in each panel. C1 invitations
   start `/pilot`; C4 invitations start `/c4` on this same service URL.

There is no new database, service, or transfer of participant data. C4 uses its
own `c4_*` tables in the existing researcher database. Startup adds the C4
researcher ownership table and preserves existing C1 accounts, codes, names,
responses and ownership records. Keep the participant service on root
`render.yaml` with its existing database and configuration.

## No practice rounds in new researcher sessions

- C1: 20 rated sounds, with a break after sound 10.
- C4: 20 distinct comparisons plus 2 hidden repeats, with a break after 11.
- Volume setup remains; neither researcher survey has practice rounds.
- Existing C1 sessions keep their saved 23-step protocol and can still resume.
  The frozen v1 bundle stays packaged. New C1 invitations use the v2 bundle.
- The C1 admin session summary and response viewer include both registered
  researcher rehearsal versions, marked Current or Earlier. Earlier answers
  and completed sessions remain visible after upgrading. The shared assignment
  list and newly issued codes still belong to the current version; no old
  session, rating, protocol or invitation is migrated or rewritten.
- The main participant surveys retain their existing practice rounds.

## Reuse a researcher's background information

In **Your experience**, fill in music activities, months, frequency, tools and
examples, then choose **Save my experience**. On a later C1 or C4 researcher
session, choose **Load my saved experience**. The fields stay editable. Use
**Update saved experience** after changes or **Forget saved experience** to
delete the reusable profile without changing existing sessions.

The profile belongs to the signed-in researcher account and is stored in the
separate rehearsal database, so it works across devices and redeployments. Each
team member should use their own researcher account. Profiles never save or
prefill consent, listening setup, invitation codes or sound/comparison answers.
The main participant surveys have no profile controls or profile API.

## Verify after deployment

- `/api/health` succeeds; `/` opens `/researcher` with both study links.
- Signed-out `/pilot` redirects to `/pilot/admin`; `/c4` to `/c4/admin`.
- Both `/api/c1-pilot/status` and `/api/c4-pilot/status` return 401 signed out.
- After one login, both statuses are ready, `rehearsal=true`, with zero practice
  presentations. C1 has 20 total presentations; C4 has 22.
- Both study pages show **Researcher rehearsal only**.
- Codes remain visible after a refresh; each code works only for its own study.
- Exports identify the matching rehearsal study, `data_origin`, `entered_by`
  and `analysis_include=False`, even for completed sessions.

The runner rejects the participant database and unknown study data before
initialization. PostgreSQL is required on Render; its existing HTTPS cookie
configuration and dedicated researcher cookie remain unchanged.

For local use, run `python -B -m survey.run_researcher_rehearsal` and open
`http://127.0.0.1:8790/researcher`. The existing local database and private login
under `data/processed/c1_researcher_rehearsal_v1/` are reused.
