# C1–C4 researcher rehearsals in one deployment

The existing `synth-c1-researcher-rehearsal` Render service serves C1 and C4
researcher surveys plus C2 and C3 self-reviews using the existing
`c1_researcher_rehearsal` Neon database.
The service name and startup command stay the same so the deployed C1 instance
can be upgraded in place.

| Database | Contents |
| --- | --- |
| `c1_review` | Participant C1/C4 surveys and C2/C3 rehearsal previews |
| `c1_researcher_rehearsal` | Researcher-only C1/C2/C3/C4 rehearsals |

One researcher login works across all four admin panels. Invitations, assignments,
responses and exports remain separate for each component. All researcher responses
are labelled rehearsal, attributed to their researcher and excluded from
participant analysis.

## Update the existing researcher service

1. Commit/push the changes and merge them into `c1-pilot-deployment`.
2. Redeploy the **existing** `synth-c1-researcher-rehearsal` service. Keep its
   current Blueprint (`survey/deploy/render.researcher-rehearsal.yaml`),
   `SURVEY_REHEARSAL_DATABASE_URL`, admin token and researcher credentials.
   Keep using the connection to `c1_researcher_rehearsal`.
3. Open the same service URL at `/researcher`. Use `/pilot/admin`, `/c2/admin`,
   `/c3/admin` or `/c4/admin`. Signing in once gives access to all four.
4. Create fresh researcher survey invitations in each panel. C1 invitations
   start `/pilot`; C4 invitations start `/c4` on this same service URL.
   C2 and C3 use **Start or resume self-review**, without a preview code.

There is no new database, service, or transfer of participant data. C4 uses its
own `c4_*` tables in the existing researcher database. Startup adds the C4
researcher ownership table and preserves existing C1 accounts, codes, names,
responses and ownership records. Keep the participant service on root
`render.yaml` with its existing database and configuration.

## No practice rounds in new C1/C4 researcher sessions

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

## C3 researcher self-review

Open **Manage C3** from `/researcher`, then **Start or resume self-review**.
The runner automatically sets `SURVEY_C3_RESEARCHER_ONLY=1`. Signed-out C3
study pages redirect to `/c3/admin`; every C3 study API requires the existing
researcher login. The admin page and its login assets remain accessible.
On this service, `/c3/` selects the researcher view, preview starts are rejected,
and preview invitation creation is disabled. Saved runs require their original
researcher's account to resume, in addition to the browser's session key.

C3 retains its frozen study: volume setup, six headphone checks, one practice,
eight comparisons and feedback. Researchers may skip setup for a demonstration;
the export records that skip. Completed runs always have `analysis_include=false`
and `excluded_from_research=true`. C3 creates only its own `c3_v2_*` tables in
the existing rehearsal database; the participant service's accounts and data
remain separate. The existing participant-site C3 preview and self-review stay
available on that service.

Deploy `.dockerignore` and `.gitattributes` with this change: the former includes
C3 pages and audio in Docker's build context, and the latter preserves the
frozen JSON's original CRLF bytes on Linux. Do not regenerate the bundle or its
manifest to resolve line endings; saved runs are bound to that fingerprint.

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

- `/api/health` succeeds; `/` opens `/researcher` with all four study links.
- Signed-out `/pilot` redirects to `/pilot/admin`; `/c4` to `/c4/admin`.
- Both `/api/c1-pilot/status` and `/api/c4-pilot/status` return 401 signed out.
- After one login, both statuses are ready, `rehearsal=true`, with zero practice
  presentations. C1 has 20 total presentations; C4 has 22.
- Both study pages show **Researcher rehearsal only**.
- Signed-out `/c3/` redirects to `/c3/admin`; `/c3/api/info` returns 401.
  After login, info reports `researcher_only=true` and
  `research_collection_enabled=false`; preview invitation creation returns 409.
- C3 self-review can start, skip setup, save, resume and export under its owning
  researcher; its admin page shows no preview invitation controls.
- Codes remain visible after a refresh; each code works only for its own study.
- Exports identify the matching rehearsal study, `data_origin`, `entered_by`
  and `analysis_include=False`, even for completed sessions.

The runner rejects the participant database and unknown study data before
initialization. PostgreSQL is required on Render; its existing HTTPS cookie
configuration and dedicated researcher cookie remain unchanged.

For local use, run `python -B survey/backend/c1_researcher_rehearsal.py` and open
`http://127.0.0.1:8790/researcher`. The existing local database and private login
under `data/processed/c1_researcher_rehearsal_v1/` are reused.
