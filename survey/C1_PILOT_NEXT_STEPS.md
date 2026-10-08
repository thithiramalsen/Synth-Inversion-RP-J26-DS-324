# C1 pilot: current status and remaining steps

Updated 8 October 2026. This is the current launch checklist; older planning
documents retain background explanations. The C1 model is owned by the C1
teammate. Its feature work is documented in
[C1_TEAMMATE_HANDOFF.md](../c1_timbre/C1_TEAMMATE_HANDOFF.md).

## Ready

- Selected 13-control Vital configuration and 1,024 generated candidates.
- Fixed 64 study sounds + 3 practice sounds with source IDs, gains and hashes.
- Sixteen connected assignments, each 3 practice + 32 unique + 4 repeats.
- Survey entry, volume/headphone setup, ratings, break, correction, resume,
  completion, withdrawal and authenticated exports.
- The 23 existing survey backend/preparation tests passed again on 8 October.
- A **full-length local rehearsal using the actual study sounds**, with its own
  study ID, copied audio and separate database. All 141 copied audio assets are
  hash-identical to their source assets; production audio/bundle is unchanged.
- Feature-precision evidence and teammate responsibilities are documented.
  No descriptor model needs to be trained before collecting this pilot.

## Do the full rehearsal now

Local address: **http://127.0.0.1:8772/pilot**.

The first participant-only invitation is in
`data/processed/c1_full_rehearsal_v1/REHEARSAL_ACCESS.md`.
This note contains no admin token. The separate private-access JSON does contain
the researcher secret and must not be shared wholesale.

This address works on the researcher's computer while its server is running;
it is not the public recruitment URL. The old 8771 diagnostic rehearsal remains
a separate instrument. The new full rehearsal has 39 presentations and keeps all
responses excluded from research analysis. Production recruitment remains closed.

Check comfortable playback, understandable descriptor wording, actual session
duration, refresh/resume, previous-answer correction before the next sound starts,
the break and final saved confirmation. Do not bypass the headphone screen or
fill automated answers and call that a human usability check.

After completion, inspect the response/session exports and verify saving and
withdrawal with a separate clearly labelled test session. The deployed rehearsal
must also check persistence across a service restart and a backup/restore.

Restart command, if needed:

```powershell
.\venv\Scripts\python.exe -B -m survey.run_rehearsal --bundle data/processed/c1_full_rehearsal_v1/bundle.json --name full_flow --port 8772
```

Do not regenerate or overwrite a bundle that has responses. The preparation
command `python -B -m survey.prepare_full_rehearsal` creates a new copy only when
its destination does not already exist. Existing rehearsal databases and original
responses are preserved.

## Remaining before participant recruitment

| Task | Who / what is needed | Current evidence |
|---|---|---|
| Agree the pilot questions | C1 owner and survey preparer confirm brightness, roughness, percussiveness and the current instructions | Wording implemented; owner sign-off not recorded |
| Complete participant information | Research contact name/email, supervisor contact and actual retention/deletion/withdrawal arrangements | Four required config fields are blank |
| Record applicable permission | Researcher/supervisor provides the actual institutional outcome; do not infer it from receipt of a blank form | `pending_supervisor_confirmation` |
| Agree eligible participants | Supervisor confirms practical-experience requirement and acceptable evidence | `supervisor_confirmed: false`; current form records self-report |
| Finish audio/usability review | Record final-selection level audition and a human full-flow rehearsal; resolve material confusion | Both completion flags remain false; limited listening feedback and note-off checks are recorded separately |
| Make the site remotely available | HTTPS hosting with persistent response storage, backup and restart/recovery tests | Local SQLite only; no public deployment |
| Freeze and open | Save final protocol/bundle version, pass deployment rehearsal, then deliberately enable recruitment | `SURVEY_C1_OPEN=0` for the local helper; no production invitations issued here |

Free hosting remains the requested preference. The backend currently uses a
local SQLite file. A free deployment must provide genuinely persistent storage,
or the backend must be adapted and checked against an external persistent
database. Do not deploy this SQLite file onto an ephemeral filesystem. No hosting
account, database service or paid resource was created in this step.

After those steps, invite toward **16 eligible completed assignments**, preserving
assignment coverage when replacing dropouts. The resulting eight primary
listeners per sound are conditional on all assignments completing; issued codes
alone do not supply replication. Export and hand off responses, audit information,
frozen stimulus/protocol records and the known-feature-issue report to the C1 owner.

## What is not holding up the C1 pilot

- The full 131,072-sound corpus is unnecessary for this pilot and is not running.
- C1 feature redesign/model fitting belongs to the analysis work; retain the
  original audio so it can be recomputed later.
- The 16-bit versus FLOAT master-format decision has not changed participant audio.
- C4's MFCC-dependent comparison selection needs separate review before its own
  study, rather than being silently treated as a C1 launch prerequisite.

No participant-facing details, eligibility confirmation, permission outcome or
human-check completion have been invented or marked complete by automation.
