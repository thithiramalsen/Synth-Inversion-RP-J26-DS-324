# C2 human-study rehearsal verification

Date: 2026-10-18. Scope: local rehearsal only; no participant collection.

## Frozen stimuli

The bundle builder completed for all eight scored cases and the separate practice
case. Every original/reconstruction pair matched its saved canonical float32
diagnostic hashes, and reconstruction distances matched. PCM16 files passed the
playback checks. The bundle has 18 case WAVs plus six setup trials and one volume
reference. The reserved test audio was not loaded; no fitting was performed.

The exact selection and source paths are in [README.md](README.md), section 3.

## Automated checks

`python -B -m unittest c2_estimation.human_study.test_study -v`

Result: **5 tests passed**, including complete eight-task API flow, restart/resume,
blinding, duplicate/stale request prevention, consent and listen gates, withdrawal,
cap/replacement behavior, failed setup, counterbalancing and tamper rejection.
Fixtures used temporary directories under `data/processed`; no existing study
database was used. `node --check c2_estimation/human_study/web/app.js` also passed.

The initial sandbox attempt stalled because local socket access was restricted.
The isolated tests passed outside that restriction in 2.089 seconds. Only identified
C2 test/preview processes created by this task were cleaned up.

## Browser check

The in-app browser successfully exercised:

- Eligibility/consent and experience choice using synthetic QA inputs.
- Volume-reference playback and all six headphone-trial submissions.
- Original and reconstructed audio playback on the practice case.
- All 13 control choices, three rating dropdowns, the open meaning question and
  both closed comprehension questions.
- Pause/resume restoring unfinished answers, followed by practice submission.
- The standard explanation and entry to the first scored case.
- Responsive layout in the narrow browser panel, including audio and q/control rows.

The browser check did **not** collect a human judgment or validate sound quality,
session duration or statistical efficacy. The full eight-task/completion/withdrawal
workflow was exercised through API tests, not an eight-case human browser session.

Browser QA used its own database:

`D:\VSCode\GitHub\Synth-Inversion-RP\data\processed\c2_v4\human_study_browser_qa_v1\responses.sqlite3`

Its saved screenshot is:

`D:\VSCode\GitHub\Synth-Inversion-RP\data\processed\c2_v4\human_study_browser_qa_v1\study-preview.png`

This synthetic QA session is incomplete and excluded from research. The production
research collection path is deliberately not implemented/enabled. The runbook
lists ethics, contacts, recruitment, hosting and data-management work still required.

## Isolation

Source additions are confined to
`D:\VSCode\GitHub\Synth-Inversion-RP\c2_estimation\human_study\`.
Generated C2 outputs are under ignored `data/processed/c2_v4/` folders. No C1/C4 or
`survey/` source, routes, databases, deployment settings or participant data were
modified. The existing `.gitignore` modification predates this work and was preserved.
