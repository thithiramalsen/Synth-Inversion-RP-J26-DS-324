# C1 participant collection

The active C1 release uses the existing 64 study sounds and three practices.
Each person rates 20 distinct study sounds on four descriptors, with a break
after ten. No audio is rendered or changed. Twenty-six assignments remain
available; the first 16 completed assignments cover each study sound five times.
This is the planned allocation, not a promise that incomplete sessions provide
that coverage or that 16 is a validated final modelling sample size.

## Deploy

Commit/push to `c1-pilot-deployment`. Update any old Render environment overrides:

| Setting | Value |
| --- | --- |
| `SURVEY_C1_BUNDLE` | `/app/survey/deploy/study/c1_participant_bundle_v1.json` |
| `SURVEY_C1_CONFIG` | `/app/survey/config/c1_participants_v1.json` |
| `SURVEY_C1_OPEN` | `1` |

The existing PostgreSQL database and researcher login remain in use. No records
are reset. Startup verifies both the current participant bundle and the retained
`study/bundle.json` review assets. `/api/c1-pilot/status` should show `ready: true`,
`rehearsal: false`, 20 rated presentations and 23 total presentations. The study
ID is `c1_20_participants_v1`. Set `SURVEY_C1_OPEN=0` to close new entry while
allowing already-started sessions to resume.

Open `/pilot/admin`, create fresh participant invitations and save the CSV.
Use `c1_participant_01` through `c1_participant_16` first, one independent person
per assignment. Extra assignments do not automatically replace a missing block
in the first 16; check which sounds lack completed ratings. Historical review
codes cannot start participant sessions. Existing review sessions resume using
their saved protocol and audio; finished reviews offer **Open the participant
study**. Review responses remain excluded and are never relabelled.

## Participant information and exports

Contact and retention/withdrawal wording match the existing C4 participant
release: Malsen N.G.T., `it23203280@my.sliit.lk`; research/assessment storage,
restricted team access and no automatic deletion date specified. No supervisor
contact or institutional approval has been invented; the configuration records
the outcome as `not_recorded`. Participant mode is a collection/software setting,
not a statement that an institution approved the project.

The new protocol is `c1_participants_2026-10-19_v1`. Saved snapshots retain the
experience tags, descriptor definitions, scale and limited correction policy.
Exports and the admin viewer use the same eligibility rule: the participant
study/protocol/collection identity, a completed session with completion time,
no withdrawal, and a study trial. Practice, incomplete, replaced and review rows
remain excluded. Original answers and correction histories remain available.
Historical `c1_pilot_v1` export behavior is retained for its separate instrument.

The CSV includes the planned `target_ratings_per_sound=5`. The descriptive
analysis reads that value instead of assuming the older eight-ratings design;
`coverage_complete` means at least the declared target for every one of 64 sounds.
Analyze different bundle/protocol versions separately. Inclusion is an initial
filter, not automatic evidence of attention, quality or model validity.

## Verify

```powershell
.\venv\Scripts\python.exe -B -m survey.deploy.build_c1_participants --check
.\venv\Scripts\python.exe -B -m unittest discover -s survey/backend/tests -v
```

Run `npm test` and `npm run build` from `survey/frontend`. The bundle builder
verifies all existing WAV hashes and refuses to overwrite a different frozen
participant bundle. Its source provenance uses LF bytes for portability across
Windows and Git/Render. Future design changes require a new version.
