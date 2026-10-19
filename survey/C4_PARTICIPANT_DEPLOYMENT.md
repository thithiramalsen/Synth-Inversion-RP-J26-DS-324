# C4 participant collection

This version opens a separate C4 participant study. It uses the same frozen
200-triplet real-audio CLAP bank and 100 balanced assignments: 20 unique
comparisons, two hidden repeats and two practices per listener. Completed
groups of ten assignments cover every triplet once; the 50–100 target gives
5–10 primary judgments per triplet when the corresponding groups complete.

## Deploy

Commit the participant changes and merge/push to `c1-pilot-deployment`, the branch
used by the Render service. The Docker image includes the new participant
bundle and both historical review bundles. The existing PostgreSQL database
and researcher account can remain in use; this update does not reset records.

Set these Render environment values (also recorded in `render.yaml`):

| Setting | Value |
| --- | --- |
| `SURVEY_C4_BUNDLE` | `/app/survey/deploy/study/c4_participant_bundle_v1.json` |
| `SURVEY_C4_CONFIG` | `/app/survey/config/c4_participants_v1.json` |
| `SURVEY_C4_OPEN` | `1` |

If the service has old C4 environment overrides, update them explicitly; pushing
a new image alone does not necessarily change an existing service's environment.
Set `SURVEY_C4_OPEN=0` to stop new participant entry without interrupting saved
sessions or deleting responses.

After deployment, `/api/c4-pilot/status` should report `ready: true`,
`rehearsal: false`, `rated_presentations: 22`, `total_presentations: 24`, and
study ID `c4_clap_participants_v1`. `/c4/admin` should say **Participant
collection is open** and list 100 assignments with IDs `c4_participant_001`
through `c4_participant_100`.

Create fresh participant invitations there. Old `c4_review_*` and `c4_clap_*`
codes belong to review versions and cannot enroll someone in this study.
Distribute assignments in order, one invitation per independent person.

A browser that completed an older review still restores that review's saved
session. Select **Open the participant study** beneath its completion screen,
then use a new participant invitation. The previous review records stay separate.

## Participant information

The contact is Malsen N.G.T., `it23203280@my.sliit.lk`. Information explains
the task, voluntary participation, comfortable listening level, saved fields,
and withdrawal. Confidence asks how sure the listener is that their chosen
sound is closer, with anchors **Not sure** and **Very sure**. It is not a
similarity magnitude score. Existing reviews keep their original wording.

The researcher has not supplied a retention duration. The information therefore
states that responses are stored for project analysis/assessment and no automatic
deletion date is set. Withdrawal excludes responses without immediately erasing
the audit. Contact-based requests use the listener code. No approval reference
or supervisor contact has been invented; the configuration records the review
status as `not_recorded`.

## Exports and audits

The participant study uses its own immutable bundle hash, study ID, assignment
IDs and frozen entry protocol. Reviews are not converted into participant data.
The source-review provenance hash uses Git's LF representation so Windows
checkout line endings do not change the generated participant bundle.

`analysis_include=True` requires the participant study and entry version, a
completed session with a completion timestamp, no withdrawal, and a primary
or repeat comparison. Practices, incomplete sessions, closed/replaced sessions
and both historical reviews remain excluded. The admin response viewer uses
the same rule as the response CSV. Hidden repeats support within-listener
consistency checks; use primary rows for independent triplet judgments.

Completed, retained participant assignments cannot be replaced. Partial and
withdrawn sessions retain their audit records. CSV exports carry study ID,
bundle/protocol hashes and collection mode so versions can be separated.

The count of included responses is an initial analysis filter, not an automatic
quality decision. Preserve uncertain and low-confidence choices for the agreed
analysis. Revisions retain original answers and correction history.

## Local verification

Materialize unchanged audio from the tracked source clips and verify packaging:

```powershell
python -B -m survey.deploy.build_c4_participants
python -B -m survey.deploy.build_c4_participants --check
python -B -m unittest discover -s survey/backend/tests -v
```

Run `npm test` and `npm run build` in `survey/frontend`. Participant tests cover
completed-only inclusion, practice/repeat distinction, withdrawal, completed-slot
protection, the close switch, and historical review isolation. Hosting startup
verifies audio hashes for all retained versions. Do not alter an existing frozen
bundle after collection starts; make a new version for later design changes.
