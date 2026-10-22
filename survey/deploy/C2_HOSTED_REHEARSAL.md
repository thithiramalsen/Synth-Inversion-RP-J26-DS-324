# C2 on the existing study services

**V2 update:** the default C2 entry/admin now uses the separate
[listening-first v2 rehearsal](C2_HOSTED_REHEARSAL_V2.md). The flow, tables,
codes and exports described below are **preserved v1**, not migrated into v2.
Old `/c2-flow/` tabs deliberately remain v1. New sessions should use v2 after
the deployment update; research collection remains disabled in both versions.

## Two deployments, not two new websites

| Service | C2 entry | Access and saved data |
| --- | --- | --- |
| [Participant service](https://synth-listening-pilot.onrender.com/c2) | `/c2`, `/c2/admin` | Public landing and read-only practice example. Starting a saved **rehearsal preview** needs a C2 invitation. Uses this service's existing `c1_review` database. |
| [Researcher service](https://synth-c1-researcher-rehearsal.onrender.com/c2/admin) | `/c2/admin` | Existing shared researcher login; start/resume self-review. Uses the existing, separate `c1_researcher_rehearsal` database. |

Research collection for **C2 remains disabled on both**. C1/C4 participant collection is unchanged. C2 self-review is developer testing, not an independent human validation study. Repeated runs do not increase the participant count.

The existing root `render.yaml` and `survey/deploy/render.researcher-rehearsal.yaml` remain in use. Both watch `c1-pilot-deployment`. No new Render service, database, login system, paid plan or account reset is needed. Do not change existing database URLs, encryption secrets, researcher passwords or invitation codes.

## Use

1. On either host, open `/researcher`, then **Manage C2**. The same account/session used for that host's C1/C4 admin panels works here.
2. On the participant host, **Create missing C2 preview codes** creates up to 12 stable rehearsal-only codes. Copy a code together with `/c2`. A code can start one saved session; resume on the same browser. C1/C4 codes cannot start C2.
3. On the researcher host, **Start or resume self-review** needs researcher authentication, not a participant code. Only its owning researcher can resume a self-review. It cannot use up participant-host assignments.
4. The read-only practice example at `/c2-flow/walkthrough` creates no session or response. It is public on the participant service and researcher-gated on the researcher service.
5. The full rehearsal retains comfortable-volume setup, six headphone checks, one unscored practice, eight cases, a halfway break, feedback, pause/resume and withdrawal. C1/C4 protocols are not changed.
6. Refresh the C2 admin summary to see saved runs. Its JSON download includes completed rehearsal runs only, with `analysis_include=false`, `excluded_from_research=true`, and `independent_participants=0`. Tokens, invitation codes, original parameter values and headphone answer keys are not exported.

No genuine participants should be recruited using this C2 release. Opening approved C2 research collection requires a separately reviewed, versioned release; it is not a switch exposed in this UI.

## Isolation and reproducibility

- New additive tables: `c2_v1_metadata`, `c2_v1_sessions`, `c2_v1_invites`. The existing encrypted invitation vault stores C2 entries under component `c2`; no C1/C4 rows are updated.
- Researcher-host startup still rejects the participant database and preserves the dedicated rehearsal cookie. It explicitly sets C2 researcher-only mode. Participant-host C2 rejects self-review starts; researcher-host C2 rejects participant-preview starts/invitation issuance.
- The frozen bundle is copied byte-for-byte from `data/processed/c2_v4/human_study_bundle_v1` to `survey/deploy/study/c2_rehearsal_v1`. Startup verifies every manifest hash, fixed selection, counterbalancing and reserved-test flag. No clips were reselected based on errors.
- The adaptation in `survey/backend/c2_flow.py` preserves the local study's questions, assignment and validation sequence. The original `c2_estimation/human_study` and `c2_estimation/self_review` implementations/databases are not modified or imported by deployment.
- The hosted protocol/bundle fingerprint prevents silent reuse after a bundle change. Substantive task/selection changes require a new protocol identity and versioned tables, retaining prior records.
- No PyTorch weights, synthesizer engine, participant database or private credentials are copied into the image. The bundle is server-private; only allowlisted current-step audio/display fields reach a session. The public example reveals the practice case only.

## Verification commands (repository root, PowerShell)

```powershell
.\venv\Scripts\python.exe -B -m unittest survey.backend.tests.test_c2_hosted -v
.\venv\Scripts\python.exe -B -m unittest survey.backend.tests.test_researcher_rehearsal survey.backend.tests.test_c4_researcher_rehearsal -q
Push-Location survey/frontend
npm test
npm run build
Pop-Location
```

Tests use disposable databases, never the hosted research databases. PostgreSQL persistence uses the existing shared database adapter. Deployment acceptance: both health checks pass; participant C1/C4 statuses retain their original protocols; researcher C1/C4 remain signed-out protected; C2 status reports research disabled; private endpoints reject signed-out requests; the C2 landing, example audio and researcher sign-in load on the appropriate hosts.

Render free instances may cold-start. An active deployment is not a guarantee of always-on uptime; the existing free plan is unchanged.
