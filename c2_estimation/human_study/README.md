# C2 human validation study — local rehearsal

## 1. What is ready, and what is not

This is a working, isolated rehearsal of the proposed C2 study. It has eligibility
and consent, volume setup, six headphone checks, one practice case, eight scored
cases, a halfway break, feedback, same-browser resume, withdrawal and researcher
exports. **Every response is marked as rehearsal and excluded from research.**
Research collection is disabled in code; there is no command-line flag to turn it
on. Do not expose this local server publicly or recruit participants with it.
An approved research release needs the checks in section 10.

Nothing in `survey/`, C1, C4, their databases, Render configuration or existing
study deployment has been changed. The saved-results demonstration on port 8765
is separate. C2 uses port 8766 and its own SQLite file.

Repository: `D:\VSCode\GitHub\Synth-Inversion-RP`

## 2. Start it

Run these commands from the repository root in PowerShell. The existing `venv`
contains FastAPI, Uvicorn, pandas, NumPy and the frozen Vita rendering runtime.
Do not use the GPU training environment to regenerate the stimuli.

```powershell
Set-Location D:\VSCode\GitHub\Synth-Inversion-RP
# Build once. Already built for this implementation; do not rerun into the same folder.
.\venv\Scripts\python.exe -B -m c2_estimation.human_study.build
# Start the separate loopback-only server. Leave this terminal open.
.\venv\Scripts\python.exe -B -m c2_estimation.human_study.server
```

Open <http://127.0.0.1:8766/>. Stop only this server with Ctrl+C in its terminal.
Do not stop or replace any C1/C4 process. No npm build or dependency installation
is needed. The frontend is ordinary HTML/CSS/JavaScript; the backend is FastAPI
with SQLite. The C2 bundle builder reuses the established Vital/Vita renderer.

The local database is created at:

`D:\VSCode\GitHub\Synth-Inversion-RP\data\processed\c2_v4\human_study_rehearsal_v1\responses.sqlite3`

A browser stores a random secret resume key and unfinished answers. Submitted
answers persist on the server. Resume requires the same origin, browser and device.
Do not share the browser profile. A code is an identifier, not a login secret.
Closing the tab pauses; it does not withdraw. There is no automatic progress while
the server is stopped, and no model training runs in this application.

Study source and audio hashes are bound to a database. After changing the study,
start a new rehearsal database instead of overwriting previous responses:

```powershell
.\venv\Scripts\python.exe -B -m c2_estimation.human_study.server --database data/processed/c2_v4/human_study_rehearsal_v2/responses.sqlite3 --port 8766
```

## 3. How clips are selected

Use the **131,072-clip, 13-control v4 corpus**, not the historical eight-control
`pilot_v1`. The source is the existing frozen reliability-validation diagnostics:

`D:\VSCode\GitHub\Synth-Inversion-RP\data\processed\c2_v4\development_uncertainty_v1\diagnostics_reliability-validation`

The original C2 protocol assigned diagnostic ranks with seed **20261013**, before
model/error/uncertainty inspection. The study takes ranks **0–7** for scored tasks
and rank **8** for practice. No MAE, reconstruction quality, reliability score,
researcher preference or participant result is used to select these clips.

| Study case | Diagnostic rank | Corpus sample ID |
|---|---:|---|
| case_01 | 0 | restricted_bend_sustain_v4_63764 |
| case_02 | 1 | restricted_bend_sustain_v4_68474 |
| case_03 | 2 | restricted_bend_sustain_v4_49083 |
| case_04 | 3 | restricted_bend_sustain_v4_67496 |
| case_05 | 4 | restricted_bend_sustain_v4_47749 |
| case_06 | 5 | restricted_bend_sustain_v4_107418 |
| case_07 | 6 | restricted_bend_sustain_v4_118035 |
| case_08 | 7 | restricted_bend_sustain_v4_82801 |
| practice | 8 | restricted_bend_sustain_v4_29514 |

Each case has the original audio and the frozen ensemble reconstruction. The
builder rerenders the saved predicted parameters and checks exact float32 audio
hashes against the measured diagnostics. It also checks the saved reconstruction
distance. Playback uses mono 44.1 kHz, three-second PCM16 copies, with the existing
10 Hz DC policy applied once and **no per-clip loudness normalization**. Predictions,
calibrators and controls are not refitted or improved for this study.

Technical checks reject missing/mismatched files, nonfinite samples, wrong shape,
clipping or digital silence. A failure stops the build; it does not quietly select
a better example. A replacement would require a logged technical reason, a revised
selection rule/version and another bundle build before recruitment. Poor model
reconstruction alone is not a reason to exclude a clip.

The first six cases happen to overlap the existing demo because it used the same
fixed ranks. Avoid recruiting people who have closely studied their true settings;
document prior exposure and any eligibility amendment before recruitment. These
eight clips are not a claim of full timbral coverage. If a later study needs an
acoustically stratified sample, preregister that selection as a new study version.

**This is a formative study on development cases.** Reliability-validation also
helped choose calibration regularization. Human feedback here evaluates clarity,
comprehension and perceived usefulness, not unbiased generalization of the model.
No reserved-test audio is loaded or evaluated. Numerical final-test evaluation
remains a separate stage.

Selection code:
`D:\VSCode\GitHub\Synth-Inversion-RP\c2_estimation\human_study\design.py` → `select_cases`

Build/provenance checks:
`D:\VSCode\GitHub\Synth-Inversion-RP\c2_estimation\human_study\build.py` → `build`

Private frozen bundle and hashes:
`D:\VSCode\GitHub\Synth-Inversion-RP\data\processed\c2_v4\human_study_bundle_v1\bundle.json`
and `D:\VSCode\GitHub\Synth-Inversion-RP\data\processed\c2_v4\human_study_bundle_v1\manifest.json`

Never serve that directory with a generic static server: its JSON contains case
identities, all conditions' q scores and headphone answer keys.

## 4. Participants and counterbalancing

Proposed target: **12 completed eligible participants; maximum 16 enrolments**.
This is a small formative sample, not a statistical power claim or proof of
population-level effectiveness. Count people, not 96 tasks or 1,248 control choices,
as independent participants.

Participants should be 18+, understand English and have practical experience
adjusting synthesizer controls/software instruments. Use headphones, a quiet place
and a comfortable level. No health or hearing information is requested. The setup
check is not a hearing test. Professional credentials are not required.

Each person hears eight distinct cases exactly once: four with q and four without.
Both conditions have identical audio and predicted controls for a given case.
Only the reliability explanation/values and associated comprehension questions
differ. There is no patch editing and no actual-parameter/correctness feedback.

`design.assignment(slot)` uses study seed **20261018** for a fixed case permutation
and six complementary pairs of assignment slots. Within a pair, case order is the
same but conditions are swapped. Across the twelve planned completions:

- Each case appears six times with reliability and six times without.
- Six people start with reliability, six without; blocks contain four cases.
- The case order rotates between pairs. Exact position balance is **not** claimed
  for 12 people and eight positions.
- A failed/withdrawn session releases its slot; a replacement takes the lowest free
  slot, not an assignment selected from its outcomes. Consent still counts toward
  the 16-enrolment cap. An unfinished session keeps its slot until resolved.

If fewer than twelve slots complete, report the achieved allocation and imbalance.
Never recruit extra people just to obtain a favourable result. Future research
needs controlled invitations to prevent duplicate enrolment; the local rehearsal
has no identity registry. The proposed shared ethics pack also limits each person
to two separately consented component sessions on different days at least 24 hours
apart. Manage that centrally without copying contact details into this study DB.

## 5. Participant flow and exact questionnaire

1. Read the rehearsal information; actively confirm six unticked eligibility and
   consent statements. Give a broad synth-experience range. Decline saves no session.
2. Play the volume reference; confirm headphones, quiet setting and comfort.
3. Complete six three-alternative headphone trials: at least five correct required.
   Assets are checksum-verified copies of the existing setup; C1/C4 are unchanged.
   No trial-level answers or pass-training feedback are shown; a failed screen ends
   the session. Do not increase the volume or repeatedly retry to pass.
4. Complete one practice case with reliability; receive the standard explanation.
   Practice answers are explicitly excluded from scored summaries.
5. Complete four cases, take a break, then complete four cases with the other display.
6. Give final feedback and save the completion code.

For each case:

- Listen fully to Original and Model reconstruction at least once. Replays allowed.
- Each of 13 controls: **Retain / Check or adjust / Cannot judge**.
- Usefulness for deciding what to check: **1 Not at all useful … 5 Very useful**,
  or **Cannot judge**.
- Clarity: **1 Not at all clear … 5 Very clear**, or **Cannot judge**.
- Decision confidence: **1 Not confident … 5 Very confident**, or **Cannot judge**.
- Optional reason, at most 1,000 characters; no personal details.

With reliability only:

- “In your own words, what does the reliability estimate mean?” **I do not know**
  is allowed; at most 1,000 characters.
- “Does high reliability guarantee perceptually identical audio?” **Yes / No / Unsure**.
- “Does low estimated reliability mean finding a matching patch is impossible?”
  **Yes / No / Unsure**.

End questions:

- Display preference: **Without reliability / With reliability / No preference /
  Cannot judge**.
- Length: **About right / Too long / Could be longer**.
- Optional useful/confusing feedback, at most 1,000 characters.

The estimate is frozen **g(U,S,R), tau_z = .05**: probability that a predicted
control is within ±.05 of its generating value in the restricted research range.
The UI shows controls on a 0–100 research-range scale and q as a percentage.
q is not a sound-similarity percentage or a guarantee of a unique correct patch.
No Accept/Approximate/Abstain categories or arbitrary q thresholds are implemented.
U/S/R plots, truth, raw correctness labels and method selectors are not exposed.

Allow approximately 20–25 minutes and plan for at most 30. The estimate is not
yet validated with people: rehearse and time it. There is no hard timer that forces
answers. Timestamp differences include pauses and should not be called active
decision time. Playback logs are browser-reported, not proof of attentive listening.

## 6. Comprehension rubric — freeze before recruitment

Primary formative outcome: comprehension **within the reliability condition**.
There is no baseline comprehension questionnaire, so do not claim a paired
with-versus-without comprehension improvement.

Open-ended meaning, per task:

- **2:** Clearly interprets q as an estimated chance/probability that the generating
  control is close within the declared tolerance/research range, with no claim that
  it measures audio similarity or guarantees a match.
- **1:** Recognizes uncertainty about the predicted control, but does not identify
  the declared tolerance/range; no contradictory guarantee claim.
- **0:** I do not know, irrelevant response, audio-similarity percentage, guarantee,
  or a conflicting explanation. Preserve the original response and coding reason.

Both closed questions are correct with **No**. Report Yes and Unsure separately.
Summarize each participant's four reliability tasks, then summarize participants.
Report the three comprehension elements separately; do not invent a validated
composite scale. These measures reflect understanding after the provided explanation,
not spontaneous understanding of an unexplained confidence display.

Ideally two reviewers independently code all short meaning responses without
seeing other ratings, then record agreement and resolve differences. Do not use
automatically generated correctness labels as a substitute for this human coding.

## 7. Analysis and exports

```powershell
.\venv\Scripts\python.exe -B -m c2_estimation.human_study.manage export --output data/processed/c2_v4/human_study_rehearsal_export_v1
```

Fresh output folders only. JSON avoids spreadsheet formula injection in comments.
`completed_rehearsals.json` contains completed scored sessions; no authentication
tokens or practice-response records. `summary.json` reports enrolments, statuses,
completed participants, paired participant-level ratings, preferences and closed
comprehension counts. `comprehension_coding.json` is the manual coding worksheet.
Keep these private: free text can accidentally contain identifying information.

Paired exploratory ratings use each participant's mean of four cases per condition.
The prespecified paired calculation requires four numeric ratings in both conditions
for that metric; Cannot judge is not a numeric zero. Valid counts and missing counts
remain visible. Participant bootstrap intervals use 2,000 draws and seed 20261018;
with fewer than two eligible participants the interval is omitted. Small-N intervals
are unstable and conditional on these eight cases, not general evidence of efficacy.
Also inspect ordinal distributions and qualitative themes; avoid relying only on
means. Do not interpret 13 actions as independently validated knob-level decisions.
Their descriptive pattern is useful, but auditory ambiguity prevents treating them
as a simple test of whether the participant chose the exact original controls.

No real participant results have been collected by this implementation. Rehearsal
exports are never final research findings. Do not mix them with a future research DB.

## 8. Withdrawal and privacy

The browser withdrawal button removes linked answers from active storage and keeps
a minimal consent/withdrawal audit. A researcher can do the same using a code:

```powershell
.\venv\Scripts\python.exe -B -m c2_estimation.human_study.manage withdraw --code C2-R-EXACTCODE
```

Use the actual code, not the example. Previous exports/backups must be handled
separately; do not promise instantaneous deletion of every copy. SQLite secure
deletion is enabled for active updates. This is not an encrypted institutional
database, and the local OS account can access it.

The draft research policy is code-based withdrawal within 14 days, active linked
response removal within 30 days, backups expiring within 90 days, and five-year
approved institutional retention after completion. Those durations are **proposed
policy, not an implemented remote retention service or an approval**. Finalize with
the PI/ERC and make participant-facing wording match the actual deployment.

## 9. Verification and code map

```powershell
.\venv\Scripts\python.exe -B -m unittest c2_estimation.human_study.test_study -v
node --check c2_estimation/human_study/web/app.js
```

Tests use generated fixtures in temporary directories under ignored `data/processed`,
not real participants or existing study databases. They cover condition/case balance,
test-partition rejection, consent/authentication, blinding, listen gates, completion,
idempotency, server recreation/resume, caps/replacements, withdrawal, screen failure
and checksum tampering.

| File under `D:\VSCode\GitHub\Synth-Inversion-RP\c2_estimation\human_study\` | Purpose |
|---|---|
| `design.py` | Selection, participant cap and deterministic assignment |
| `build.py` | Frozen audio/probability export and provenance |
| `server.py` | Isolated DB, phase validation, authorised audio and blinded responses |
| `web\index.html`, `web\style.css`, `web\app.js` | Participant interface, playback, drafts and resume |
| `manage.py` | Local code-based withdrawal and rehearsal-only analysis exports |
| `test_study.py` | Synthetic fixture tests |

## 10. Before a real study

- Obtain written ERC approval and any required SLIIT management permission before
  recruitment/collection; the existing external Word drafts were not edited here.
- Finalize project title, PI/researcher contacts, independent complaints contact,
  participant information, consent/version and retention/withdrawal wording.
- Update draft C2 documents to continuous q, not Accept/Approximate/Abstain; correct
  the primary comprehension claim and freeze the rubric/analysis before recruitment.
- Confirm headphones/eligibility, prior demo exposure, time burden and accessibility
  in an informal usability rehearsal. Review selection changes as versioned amendments.
- Implement and review the approved HTTPS hosting/storage/invitation system, access
  control, backup expiry and region/access arrangements. This server intentionally
  binds loopback only and is not production deployment infrastructure.
- Use a separate research DB/version and approved consent. Verify that researcher
  contact mapping is separate from coded answers; no public raw participant exports.
- Check centrally for cross-component enrolments and the 24-hour/two-session policy.
- Freeze study assets and model/calibration sources; record deviations and achieved
  assignment balance. Do not retrain or change the model in response to study answers
  and then describe those same responses as independent validation.
