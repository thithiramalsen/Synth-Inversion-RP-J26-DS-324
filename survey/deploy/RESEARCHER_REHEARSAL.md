# Deploy the separate C1 researcher rehearsal

This service accepts fresh research-team rehearsal answers. Its study ID,
researcher attribution and analysis exclusion remain explicit in the interface
and exports. Its database starts empty and stays separate from participant data.

1. Commit and push the rehearsal files, then merge them into
   `c1-pilot-deployment`.
2. In the existing Neon project, create a new empty database named
   `c1_researcher_rehearsal`. Copy its connection string privately. Do not use
   `c1_review` or `c1_review_test`.
3. In Render, create a **new Blueprint** from the same repository and branch.
   Set **Blueprint Path** to `survey/deploy/render.researcher-rehearsal.yaml`.
   This Blueprint names a separate service, `synth-c1-researcher-rehearsal`.
4. Supply the two requested secrets:

   | Variable | Value |
   | --- | --- |
   | `SURVEY_REHEARSAL_DATABASE_URL` | The new rehearsal database connection string |
   | `SURVEY_RESEARCHER_PASSWORD_HASH` | A researcher login password hash |

   Use `survey/deploy/make_password_hash.py` to generate a hash locally, or copy
   the existing researcher password hash from the hosting dashboard if you want
   the same initial username/password. Never put passwords or database URLs in
   source files or chat. Render generates a separate persistent rehearsal admin
   token; preserve it so stored invitation codes remain recoverable.
5. Deploy and wait for **Live**. Open the new service URL at `/pilot/admin` and
   sign in as `researcher`. Create fresh rehearsal invitations and researcher
   account invitations for teammates. Accounts in the participant database are
   separate and are not copied.

Use the new Blueprint as a new deployment. Keep the existing participant service
on the root `render.yaml`. Its branch, database, invitations and configuration do
not need to change for this new service.

## Verify the deployed service

- `/api/health` returns success.
- Signed-out `/pilot` redirects to `/pilot/admin`.
- Signed-out `/api/c1-pilot/status` returns 401.
- After sign-in, the C1 page says **Researcher rehearsal only**.
- `/api/c4-pilot/status` returns 404 on this service.
- Create a test invitation; confirm its code remains visible after a refresh.
- Exports use the `c1_researcher_rehearsal_v1` identity, researcher attribution and
  `analysis_include=False`. Completed team sessions remain rehearsal data.

The runner rejects local SQLite storage on Render and rejects a database with
other study data before schema initialization. Proxy handling preserves secure
login cookies behind Render's HTTPS ingress.

## Hosting limits

The Blueprint selects Render's free web-service plan and uses persistent external
PostgreSQL. Free Render services lose local files on restart and may sleep after
15 minutes of inactivity. Both services share the workspace's 750 free instance
hours per month. See [Render's free-service limits](https://render.com/docs/free).

Render supports the separate Docker startup command and Blueprint path used here;
see the [Blueprint reference](https://render.com/docs/blueprint-spec).
