# C2 researcher self-review

This is a separate launch of the existing C2 study frontend for the project
researcher's own software and procedure rehearsal. It is not an independent
participant study and does not establish an ethics exemption.

## Two stages

1. **Researcher rehearsal now:** check the instructions, audio, control display,
   questions, saving/resume, withdrawal and practical burden. Record observations
   as developer notes. Knowing the system and previously seeing its cases makes
   your own ratings unsuitable as independent comprehension/usefulness evidence.
2. **Approved participant study later:** use independently recruited eligible
   adults, the approved information/consent/protocol, a separately versioned release
   and a new research database. Do not migrate self-review answers into it.

Existing synthetic-corpus objective evaluation (parameter errors, calibration and
diagnostic checks) is a separate evidence stream. It does not require completing
your own questionnaire. Independent reserved-test evaluation must still follow
the final method lock and protected split protocol.

SLIIT's published process requires a preliminary review form and supervisor
recommendation, followed by the detailed/ERC route when required:
https://elibrary.sliit.lk/Ethics%20Review%20Process%20%281%29.pdf
Ask the supervisor/ERC to determine requirements before treating a self-experiment
or an informal pilot with other people as research evidence. This launcher
authorizes no recruitment and makes no approval claim.

## Start the separate frontend

To start **both views for a demonstration** with one command:

```powershell
Set-Location D:\VSCode\GitHub\Synth-Inversion-RP
.\venv\Scripts\python.exe -B -m c2_estimation.self_review.panel
```

- Researcher self-review: **http://127.0.0.1:8767/**
- Participant-facing study preview: **http://127.0.0.1:8768/**
- Read-only practice-case walkthrough: **http://127.0.0.1:8768/walkthrough**

Both full views share the verified study code and frozen stimuli, but use separate
databases and browser-storage keys. The participant preview stores only rehearsal
responses in `data/processed/c2_v4/participant_preview_v1/responses.sqlite3`.
The read-only walkthrough exposes only the practice case and saves no session or
answers. It lets the panel inspect the case display and hear both clips quickly.
These URLs work on the presenting laptop; no public deployment is created.
Keep the launcher terminal open. Ctrl+C stops only the two child servers it owns.
If a port is occupied, the launcher stops before starting anything and leaves the
existing process untouched. Cross-links assume these default ports.

To start just your self-review:

In PowerShell:

```powershell
Set-Location D:\VSCode\GitHub\Synth-Inversion-RP
.\venv\Scripts\python.exe -B -m c2_estimation.self_review.server
```

Open **http://127.0.0.1:8767/**. The top banner says **RESEARCHER SELF-REVIEW**.
Keep the terminal open; Ctrl+C stops only this app.

The existing study frontend and backend are reused. Their source, frozen audio,
questions, headphone check, one practice and eight scored-form cases are not
copied or edited. The scored-form wording describes questionnaire sections; these
are rehearsal responses, never scored participant evidence. No model training,
new inference or stimulus rendering occurs in this app.

The original study uses port 8766. The live audio-to-patch app uses 8770. This
version has a separate browser origin/resume-key namespace and SQLite database:

`D:\VSCode\GitHub\Synth-Inversion-RP\data\processed\c2_v4\researcher_self_review_v1\responses.sqlite3`

All responses remain `mode=rehearsal` and `excluded_from_research=true`.
Research collection stays disabled. The launcher rejects paths into existing
study databases. If source changes require another database version, preserve the
old one and use:

```powershell
.\venv\Scripts\python.exe -B -m c2_estimation.self_review.server --database data/processed/c2_v4/researcher_self_review_v2/responses.sqlite3 --port 8767
```

Starting another rehearsal from the completion page preserves the previous run.
Multiple runs by you are not multiple participants. The participant-style screens
are kept so you can rehearse the actual journey; the language does not make you
an independent participant or provide ethics authorization.

## What to check yourself

Use one normal run and then targeted technical checks where useful. Do not answer
the questionnaire merely to manufacture positive feedback.

| Check | Useful observation to record |
|---|---|
| Instructions | Which phrase or question is unclear or unnecessarily technical? |
| Playback | Do both clips load, play fully and replay at a comfortable level? |
| Controls | Are the research-range positions readable and distinguished from Vital knob values? |
| Reliability | Could the wording be mistaken for audio similarity or a guarantee? |
| Questions | Is Cannot judge available? Do required fields and free text behave correctly? |
| Burden | Approximate total time, interruptions, repetitive sections and fatigue |
| Persistence | Does closing/reopening preserve submitted and unfinished answers? |
| Withdrawal | Use a separate technical test run to check removal, preserving your normal run |

Document observations using `REVIEW_NOTES_TEMPLATE.md`, making a new dated copy.
Include issues found and resulting decisions. A single researcher cannot provide
independent usability, inter-rater agreement or a statistical with/without-q study.
Do not skip or repeatedly retry the headphone check to produce a claimed pass.
Record a technical failure if it prevents rehearsal.

The existing study's complete flow is approximately 20–25 minutes by design;
that is an estimate to check, not an established duration. Paused time is not
active decision time. The eight audio cases are fixed development examples,
not final test cases. See `c2_estimation/human_study/README.md` for selection and
the approved-study preparation checklist.

## Export your runs

```powershell
.\venv\Scripts\python.exe -B -m c2_estimation.self_review.export --output data/processed/c2_v4/researcher_self_review_export_v1
```

Use a new output folder. `self_review_runs.json` contains completed questionnaire
runs without secret resume tokens or practice answers. `self_review_summary.json`
counts rehearsal runs and explicitly records **zero independent participants**.
It computes no group means, participant bootstrap intervals or participant
effectiveness claims. Free text stays local and should contain no personal details.

For an existing test-run withdrawal, the shared local management command accepts
the separate database explicitly:

```powershell
.\venv\Scripts\python.exe -B -m c2_estimation.human_study.manage --database data/processed/c2_v4/researcher_self_review_v1/responses.sqlite3 withdraw --code C2-R-YOURCODE
```

The browser withdrawal button also works. Preserve any earlier exports separately;
withdrawing from active storage does not remove already exported copies.

## How to describe this in PP1

“The study interface is implemented. I carried out a researcher walkthrough to
check the procedure and record interface issues. These observations are excluded
from participant findings. Independent user evaluation is pending the required
approval and recruitment.”

Only say that you carried out the walkthrough after actually doing it. Developer
inspection and automated tests are not user feedback or proof of perceived sound
quality. This repository change only prepares the separate self-review environment.

## Verification

Three isolation/export/preview tests passed, and both frontends plus practice-case
playback and reliability switching were checked in the browser. See
[VERIFICATION.md](VERIFICATION.md). To rerun the tests with disposable fixtures:

```powershell
.\venv\Scripts\python.exe -B -m unittest c2_estimation.self_review.test_self_review.SelfReviewTests -v
```
