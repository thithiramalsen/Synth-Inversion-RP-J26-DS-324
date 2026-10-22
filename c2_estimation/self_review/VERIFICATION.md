# C2 researcher rehearsal and participant-preview checks

Verified 22 October 2026. This record describes software checks, not a completed
researcher walkthrough, user feedback, ethics approval or participant findings.

## Accessible views

- Researcher self-review: http://127.0.0.1:8767/
- Participant study preview: http://127.0.0.1:8768/
- Read-only example: http://127.0.0.1:8768/walkthrough

The two servers were launched together using:

```powershell
.\venv\Scripts\python.exe -B -m c2_estimation.self_review.panel
```

Both `/api/info` endpoints returned the correct distinct purpose with
`research_collection_enabled=false`. They share the original frozen study bundle
and questionnaire implementation, with separate databases and browser-storage keys.
The original study on 8766, the live application on 8770, other components and
their data were not changed or stopped.

## Tests

```powershell
.\venv\Scripts\python.exe -B -m unittest c2_estimation.self_review.test_self_review.SelfReviewTests -v
```

Three tests passed. They verify separate database identity, unchanged synthetic
original-study storage, restart/resume, front-end labels, disabled research
collection, refusal to export another study's database, and exports that count
multiple researcher runs as zero independent participants. The read-only example
exposes only practice-case display fields, rejects unlisted audio paths and creates
zero sessions. Fixtures use temporary, synthetic storage, not participant responses.

Initial tests found unclosed SQLite read connections during Windows temporary-file
cleanup. The new wrapper/exporter now explicitly close those connections; the
repeated tests passed with normal cleanup. Existing study source was not edited.
The new walkthrough JavaScript passed Node syntax checking. `git diff --check`
passed.

## Browser checks

Both frontends displayed their distinct banners, navigation and unticked
consent-style controls. The participant page's preview link opened the separate
practice-case walkthrough. Both three-second audio players loaded and played
without a media error. Starting reconstruction paused the original. Toggling
reliability hid/showed the probability column, explanation and associated
comprehension questions, while keeping the audio and predicted controls fixed.
All 13 control rows and disabled example rating fields displayed. The browser
reported no errors or warnings for the walkthrough.

Screenshots:

- `data/processed/c2_v4/self_review_verification_v1/self-review.jpg`
- `data/processed/c2_v4/self_review_verification_v1/walkthrough.jpg`

No consent form was submitted in the real preview databases during this browser
check, and no human judgments were generated. A full personal walkthrough remains
for the researcher to perform. The unchanged shared study already has its own
full-flow fixture verification in `c2_estimation/human_study/VERIFICATION.md`.

## Limits

The URLs are loopback addresses for use on the presenting computer, not remotely
accessible public study links. The read-only walkthrough illustrates the practice
case and questionnaire layout; it does not replace completing the real procedure.
The normal previews can save only excluded rehearsal answers. Future participant
research requires the institutional determination/approval, finalized materials,
approved deployment and a separate research release/database. Nothing here grants
an exemption or enables collection as participant evidence.
