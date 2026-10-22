# C3 human study (H3) — local rehearsal

## 1. What is ready, and what is not

This is a working, isolated **rehearsal** of the proposed C3 human study. It has eligibility
and consent, volume setup, six headphone checks, one practice case, eight scored cases, a
halfway break, feedback, same-browser resume, withdrawal and researcher exports.
**Every response is marked as rehearsal and excluded from research.** Research collection is
disabled in code; there is no flag to turn it on. Do not expose this server publicly or recruit
participants with it.

**Version 2** (`c3-human-v2`) uses the operating point selected on validation data in Phase 7
(D-018): mfcc26, shortlist N = 100, k = 5, **λ = 0.5**. It must equal the values in
`docs/PREREGISTRATION.md`; if the preregistration changes them, build a new study version.
Version 1 (provisional λ = 0.8) is kept on disk unchanged and is no longer served.

Nothing in `survey/`, C1, C2, C4, their databases or deployments is changed. C3 uses port
**8767** and its own SQLite file. The headphone-check audio is a hash-verified copy of the
existing setup assets.

## 2. Start it

From the repository root in PowerShell (the venv needs FastAPI, Uvicorn and httpx — see
section 9):

```powershell
.\venv\Scripts\Activate.ps1
# Already built once; build a NEW folder name if you ever rebuild.
python -B -m c3_recommendation.human_study.build
# Start the loopback-only server; leave this terminal open.
python -B -m c3_recommendation.human_study.server
```

Open <http://127.0.0.1:8767/>. Stop the server with Ctrl+C in its terminal.

The rehearsal database is created at
`data/processed/c3_v4/human_study_rehearsal_v2/responses.sqlite3`. The study source and bundle
hashes are bound to that database: after changing the study, use a fresh database, e.g.

```powershell
python -B -m c3_recommendation.human_study.server --database data/processed/c3_v4/human_study_rehearsal_v2b/responses.sqlite3
```

A browser keeps a random secret resume key and unfinished answers. Submitted answers stay on
the server. Resume needs the same browser and device. Closing the tab pauses; it does not withdraw.

### Demo mode for presentations

```powershell
python -B -m c3_recommendation.human_study.server --demo
```

Opens on <http://127.0.0.1:8768/> with its own database
(`data/processed/c3_v4/human_study_demo_v2/`). A **Skip the setup check (demo only)** button
appears on the setup pages and a DEMO banner is shown. Demo sessions are coded `C3-D-…`, marked
`screen_skipped` when skipped, and excluded from any rehearsal or research analysis. The normal
study (without `--demo`) has no skip option. A demo database cannot be reopened in normal mode.

## 3. What participants compare, and how cases are chosen

H3 asks whether producers find C3's sets more useful than the plain "top 5 closest" list.

Each case shows a **target sound** and two blinded sets of five suggested patches, **Set A** and
**Set B**, built from the same 100-sound audio shortlist of the 104,858-sound bank:

- the plain top 5 by audio closeness, and
- the C3 set (MMR: close in sound, varied in knob settings).

Participants hear every sound and see each suggestion's 13 knob settings as bars. They never
see the target's own knob settings, which are unknown in real use.

Selection (`build.py`, seed **20261022**): a seeded sample of 40 **validation** targets is
screened in order. A target is skipped only if both sets are identical (nothing to compare) or
an audio file fails a technical check (non-finite, clipped, below −60 dBFS). The first 8
eligible targets are scored; the 9th is the practice case. No human response, set metric or
listening judgement is used to select cases. Bundle v1 (λ = 0.8) skipped 1 target with identical
sets; bundle v2 (λ = 0.5) skipped none, so its cases are screened ranks 0–8 and differ from v1's
from case 2 onwards. Each v2 case has 6–9 distinct sounds to rate (8 on average).

Playback files are mono 44.1 kHz, three-second 16-bit copies of the processed corpus audio
(10 Hz DC policy applied once, no loudness normalisation).

The private bundle `data/processed/c3_v4/human_study_bundle_v2/` holds `bundle.json`
(sample IDs, which set is which, set metrics, headphone answer keys) and `manifest.json`
(SHA-256 of every file). **Never serve that folder with a generic static server.** The server
verifies every hash at start-up and only sends the current step's allowlisted fields.

**This is a formative study on validation cases**, conditional on eight targets and the
Phase 7 operating point. No test-split sound is used.

## 4. Participants and counterbalancing

Planned: **12 completed eligible participants; at most 16 enrolments.** This is a small
formative sample, not a power calculation. Count people, not cases or sounds.

Eligibility: 18+, understands English, practical experience adjusting synthesizer controls.
Headphones, a quiet place, comfortable volume. No health or hearing information is asked; the
setup check is not a hearing test.

`design.assignment(slot)` gives complementary slot pairs (0/1, 2/3, …):

- same case order within a pair, opposite Set A/B labels;
- every participant sees the C3 set as **Set A in 4 of 8 cases**;
- over 12 completions each case shows C3 as Set A six times and as Set B six times;
- case order rotates between pairs; exact position balance is not claimed.

Within a case, sounds are numbered by a fixed per-case shuffle and each set is listed in number
order, so the rank order cannot reveal the method. A sound in both sets keeps one number and
is rated once. A withdrawn or failed session frees its slot for the next starter.

## 5. Participant flow and exact questions

1. Information, six unticked eligibility/consent statements, experience range.
2. Volume reference; confirm headphones, quiet place, comfortable level.
3. Six three-tone headphone checks; at least five correct. A failed check can be retried within
   the same session, at most 3 attempts in total (each attempt is recorded); after that the session ends.
4. One practice case (not scored), then an explanation of Set A/B and the knob bars.
5. Four cases, a break, four cases.
6. Feedback and completion code.

Each sound and the target must be played through once before saving (replays allowed).

For each case:

- **How close is each sound to the target?** 1 Not close … 5 Very close, or Cannot judge
  (every distinct sound).
- **Which set gives you more useful, different starting points to edit towards the target?**
- **Which set sounds closer to the target overall?**
- **In which set do the sounds sound more different from each other?**
  (each: Set A / Set B / No difference / Cannot judge)
- **Confidence:** 1 Not confident … 5 Very confident, or Cannot judge.
- Optional reason, at most 1,000 characters, no personal details.

End: usefulness of the knob bars (1–5 or Cannot judge), session length, optional comment.
Allow about 30–35 minutes (v2 has about 8 sounds per case); rehearse and time it, and shorten
the session if rehearsals run long.

## 6. Analysis plan — frozen before any response (D-020)

Unit of analysis: the participant. Run it with:

```powershell
python -B -m c3_recommendation.human_study.manage analyze --output data/processed/c3_v4/human_study_rehearsal_v2_analysis_v1
```

It writes `REPORT.md`, `analysis.json`, `ratings_long.csv`, `participant_closeness.csv`,
`per_case.csv`, `closeness_by_group.png` and `primary_outcome.png` to a fresh folder.

- **Primary outcome — are C3's picks heard as close as the top-k?** Per participant: mean
  closeness of C3-only sounds minus top-k-only sounds (Cannot judge excluded). 95% participant
  bootstrap CI (10,000 draws, seed 20261022). **Heard as close if the CI lower bound > −0.5.**
- **Are the suggestions close at all?** Mean rating and share rated 4–5 for top-k-only, C3-only
  and shared sounds.
- **Does the model agree with ears?** Within-participant Spearman correlation of model
  relevance (and shortlist rank) with ratings.
- **Set choices:** each participant's share of decisive Set A/B answers that chose the C3 set,
  for the three questions; 0.5 = no preference. "No difference" and "Cannot judge" are counted.

The "more different by ear" question checks whether variety in knob settings is audible; it is
not the C3 success criterion, which concerns closeness and editing usefulness.

**Software check without participants:** `--simulate 12 --effect 0` analyses fake sessions. The
simulator assumes people track MFCC relevance steeply, so its numbers are never a prediction.

## 7. Exports and withdrawal

```powershell
python -B -m c3_recommendation.human_study.manage export --output data/processed/c3_v4/human_study_rehearsal_v2_export_v1
python -B -m c3_recommendation.human_study.manage withdraw --code C3-R-EXACTCODE
```

Exports need a fresh folder: `completed_rehearsals.json`, `summary.json`,
`free_text_reasons.json`. No tokens, sample IDs or answer keys. Keep exports private: free text
can contain identifying details. Withdrawal removes linked answers from active storage and keeps
a minimal consent/withdrawal record; earlier exports or backups must be handled separately.

## 8. Code map

| File in `c3_recommendation/human_study/` | Purpose |
|---|---|
| `design.py` | Version, seed, sample size, operating point, eligibility, counterbalancing, sound numbering |
| `build.py` | Frozen private bundle from validation targets with the tested C3 code; audio QA; provenance |
| `server.py` | Loopback-only FastAPI + SQLite server: phases, listen gates, blinding, withdrawal |
| `web/index.html`, `web/style.css`, `web/app.js` | Participant page: playback, knob bars, drafts, resume |
| `manage.py` | Rehearsal exports and code-based withdrawal |

Tests (`c3_recommendation/tests_v4/`): `test_human_study_design.py` and
`test_human_study_server.py` (synthetic bundles in temporary folders only).

## 9. Verification

```powershell
python -m pip install fastapi==0.116.1 "uvicorn[standard]==0.35.0" httpx==0.28.1   # once
python -m pytest c3_recommendation/tests_v4 -q
```

## 10. Before a real study

- Phase 7 is done and bundle v2 uses its values. Confirm they match PREREGISTRATION.md; if the
  preregistration changes them, build a new study version and start a fresh database.
- Obtain written ethics approval and any required permissions; finalise information sheet,
  consent wording, contacts, retention and withdrawal policy in line with the shared ethics pack.
- Rehearse with 2–3 people to check timing, clarity of the three questions and the knob bars.
- Integrate into the approved hosted study service (as done for C2) with controlled invitations;
  this local server is not a production deployment.
- Coordinate cross-component enrolment limits centrally. Do not change C3 in response to study
  answers and then present those answers as independent validation.
