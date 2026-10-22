# C2 v2 — listening first, reliability display second

Protocol: `c2-hosted-rehearsal-v2`. Consent/schema: `c2-human-v2`.
This is a **formative rehearsal**, not an approved participant-research release.
Research collection remains disabled; independent participants remain zero.
The Vital-style live demo on port 8770 is outside this change.

## Why this version exists

V1 asked for 13 retain/check/cannot-judge decisions per case without allowing
patch editing or auditioning control changes. Those answers describe intentions,
not verified knob-level correctness or improved editing performance. V2 removes
all 104 scored control decisions and asks about sound similarity and display
usefulness separately. Comprehension is asked once, not on four separate cases.

This is a design choice for a small, lower-burden formative study, not a validated
psychometric instrument or a claim of compliance with MUSHRA. Understanding a
confidence display is distinct from improved task performance; see
[Zhang, Liao and Bellamy (2020)](https://arxiv.org/abs/2001.02114).

## Exact flow and questions

1. Unticked eligibility/consent, broad synthesizer-experience range.
2. Comfortable-volume setup and the unchanged six headphone checks. At least
   five correct; no answer hints or training retries. A failure ends the run.
3. One **audio-only practice**, excluded from summaries.
4. **Part 1:** all eight original/reconstruction pairs. No parameter values,
   reliability scores, truths, errors or display allocations are returned to
   this screen/API. Each case asks:
   - Overall sound similarity: 1 **Not at all similar** to 5 **Very similar**,
     or **Cannot judge**.
   - Optional comment, up to 1,000 characters; no personal details.
   Both clips must have browser-reported start/end events before saving. The
   unchanged C4 played-range helper is reused to avoid crediting seek-to-end
   as a full listen in the C2 browser; this still cannot prove attention.
   Rate similarity, not preference. Optional break after four pairs.
5. Only after **all eight** listening ratings have been saved and locked:
   Part 2 explanation. Then eight displays for the same cases, four with
   reliability and four without. Audio replay is optional. Each asks only:
   - How clear is this display? 1 **Not at all clear** to 5 **Very clear**.
   - How useful is this display for deciding how much to check the suggested
     settings? 1 **Not at all useful** to 5 **Very useful**.
   Both allow **Cannot judge**. No control-by-control actions or editing.
   Optional break after four displays, then the other condition.
6. Final questions, once:
   - In your own words, what does a control's reliability estimate mean?
     **I do not know** is acceptable.
   - Does high reliability guarantee perceptually identical audio?
     **Yes / No / Unsure**.
   - Does low reliability mean finding a matching patch is impossible?
     **Yes / No / Unsure**.
   - Preferred display: with / without reliability / no preference / cannot judge.
   - Length: about right / too long / could be longer; optional comment.

Allow roughly 15–20 minutes, **not yet validated by human timing**. Ask listeners
to stop by 30 minutes, without enforcing a timed completion. Same-origin/browser
pause/resume and withdrawal remain available. Closing a tab is not withdrawal.
Server playback logs do not prove attentive, uninterrupted listening. Timestamp
differences include pauses and must not be presented as active decision time.

## Selection and allocation

No new audio, model inference, calibration, perturbations or stimulus selection.
Reuse the byte-identical `survey/deploy/study/c2_rehearsal_v1` bundle: diagnostic
ranks 0–7 for the eight cases, rank 8 for practice, on reliability-validation
development data. No error/q-based cherry-picking and no reserved-test access.

The original 12-slot complementary 4-with/4-without display allocation is retained.
Each case appears six times in each display condition if all 12 slots complete.
Six slots start with each condition. Part 1 order is deterministically shuffled
with seed **20261022**, shared within complementary slot pairs. Every listener
hears all eight pairs without scores before any display. No exact ordinal-position
balance or unexposed/no-training control group is claimed. Display comprehension
is measured **after the common explanation**, not spontaneous understanding.

The same development cases and prior demo/rehearsal exposure limit generalization.
Record prior exposure before a future approved study. The researcher’s own review
and repeated reviews are developer observations, never independent participants.
Proposed future formative target stays 12 eligible completions / maximum 16
enrolments; it is not a power calculation. Actual participant recruitment requires
a separately reviewed release, versioned consent/information, controlled enrolment
and approval. The rehearsal code does not open research collection.

## Analysis contract — do not overclaim

- Audio outcome: ordinal rating distributions by case plus per-person/run summaries,
  retaining Cannot judge counts. One rating per listener per case; practice excluded.
  Eight observations are not eight independent participants. This study has no
  alternative inversion system/baseline condition: it cannot establish superiority,
  perceptual equivalence or coverage of all possible synthesizer sounds.
- Display outcomes: exploratory within-person clarity/usefulness summaries for four
  cases in each condition, with complementary allocation across listeners. A paired
  mean difference is eligible only with four numeric ratings in **both** conditions
  for that metric. Otherwise retain descriptive means/counts but no paired difference.
  Cannot judge is missing/uncertain, not numeric zero. Preserve ordinal distributions.
- Comprehension: one final meaning response, manually coded. Freeze rubric before
  recruitment: **2** = estimated probability of a close generating setting within
  the declared tolerance/range, with no audio-similarity/guarantee claim; **1** =
  uncertainty about the control, but tolerance/range omitted, no contradictory
  guarantee; **0** = I do not know / irrelevant / similarity percentage / guarantee.
  Prefer two independent coders; preserve both scores, agreement and reconciliation.
  Each closed question's intended answer is No; report Yes and Unsure separately.
  No invented validated composite scale, automatic open-answer scoring, or paired
  with/without comprehension-improvement claim.
- No claims about actual editing success, decision correctness, trust calibration,
  or numerical probability calibration from these ratings. Those need different
  measured outcomes. Parameter prediction/calibration metrics remain separate.
- Current exports are explicitly **rehearsal only**. No population inference,
  significance testing or confidence intervals from repeated researcher runs.

## What the low reliability scores mean

The frozen event is `abs(predicted_z - generating_z) <= 0.05`, shown as ±5 points
on a 0–100 restricted research-range scale. A low q estimates a low chance of
meeting that **exact-setting tolerance**, not low audio similarity. Calibration
quality and parameter-recovery quality are different: honest low probabilities
can be useful, while the underlying parameter estimates still need improvement.
Do not explain every failure as non-identifiability; model/feature limitations
also require investigation. No scores, tolerances or clips were changed for v2.

Saved development evidence: `data/processed/c2_v4/development_uncertainty_v1/`
`calibration_tau_0.05/parameter_metrics.csv` and `summary.json`.
On the 512 reliability-validation cases, the within-tolerance rates are:

| Control | Within ±5 points |
| --- | ---: |
| Wave shape | 50.2% |
| Wave bend | 11.5% |
| Filter cutoff | 72.1% |
| Filter resonance | 21.9% |
| Filter drive | 12.5% |
| Volume attack | 92.6% |
| Volume decay | 59.8% |
| Volume sustain | 82.4% |
| Volume release | 99.6% |
| Filter-envelope amount | 15.8% |
| Filter-envelope attack | 16.8% |
| Filter-envelope decay | 9.8% |
| Filter-envelope sustain | 17.2% |

Macro Brier loss: `g0 = 0.138242`, `g(U) = 0.116267`,
`g(U,S,R) = 0.115385` (lower is better). Full versus constant baseline is about
16.5% lower; the extra gain versus uncertainty alone is small (~0.000882).
Failure AUROC is only ~0.542 for filter-envelope decay and ~0.608 for filter drive,
so useful error ranking is not uniformly strong. Volume release has only two
failures here, making its failure-ranking metric unstable. These are development
results used in method selection, **not untouched final-test results** or proof
of calibrated per-case probabilities. Do not turn q into a sound-quality score.

## Files to open

Paths below are relative to `D:\VSCode\GitHub\Synth-Inversion-RP`.

| File | Responsibility |
| --- | --- |
| `survey/backend/c2_design_v2.py` | Protocol contract, seed/order, ratings |
| `survey/backend/c2_flow_v2.py` | Blinding, phases, authentication, v2 records |
| `survey/backend/c2_analysis_v2.py` | Rehearsal distributions and paired summaries |
| `survey/backend/c2_pilot.py` | Separate v1/v2 admin, invitations and exports |
| `survey/frontend/src/C2StudyV2.jsx` | New study screens, audio, drafts, pause |
| `survey/frontend/src/c2-study.css` | C2-only responsive layout |
| `survey/frontend/src/pilot.css`, `SiteNavigation.jsx` | **Unchanged** C1/C4 styles/header reused by C2 |
| `survey/frontend/src/C2App.jsx` | V2 entry/admin plus preserved v1 links |
| `survey/backend/tests/test_c2_hosted_v2.py` | Disposable-database integration tests |
| `survey/frontend/tests/c2-v2.test.mjs` | Blinding, shared UI and question checks |
| `survey/backend/tests/c2_v2_browser_fixture.py` | Temporary loopback UI fixtures, never shipped |

## Version isolation and deployment

- Additive `c2_v2_metadata`, `c2_v2_sessions`, `c2_v2_invites`; never migrate or
  overwrite `c2_v1_*`. V2 invitation vault entries use component `c2_v2`.
- API: `/c2-flow-v2/api/*`; SPA: `/c2/rehearsal-v2` and `?view=researcher`.
  V2 browser keys start `c2-hosted-v2-`; v1 keys stay untouched.
- V2 admin: `/api/c2-pilot/v2/admin/{summary,invitations,export}`.
  V1 endpoints/flow/assets still exist and resume/export their own records.
- Fingerprint binds the unchanged manifest to the v2 protocol contract. Later
  substantive changes need a new version; do not reset the fingerprint in place.
- Same two Render services and databases, same researcher login and isolated
  rehearsal cookie. No account, secret, database URL or existing code resets.
  Shared application changes only register/protect the additional C2 routes.
- V2 is the default C2 admin action after redeployment. The original v1 flow is
  linked separately for resume/export. Never mix exports across versions.
- Docker already copies `backend/*.py` and builds the React frontend, so no new
  service, package installation, stimulus copy or deployment-plan change is needed.
- The Vital demo, checkpoints, renderer, calibration, live results and C1/C4
  protocol/UI source files are not part of this update.

After deployment, use
`https://synth-c1-researcher-rehearsal.onrender.com/c2/admin`, sign in normally,
then **Start or resume v2 self-review**. The other host remains invitation-gated
participant-interface preview, not open research collection. Old browser tabs
at `/c2-flow/` intentionally continue v1; do not silently change an active study.

## Verification (PowerShell, repository root)

```powershell
.\venv\Scripts\python.exe -B -m unittest survey.backend.tests.test_c2_hosted_v2 survey.backend.tests.test_c2_hosted -v
.\venv\Scripts\python.exe -B -m unittest survey.backend.tests.test_researcher_rehearsal survey.backend.tests.test_c4_researcher_rehearsal -q
Push-Location survey/frontend
npm.cmd test
npm.cmd run build
Pop-Location
# Optional visual QA only: disposable DB and synthetic answers; never use for people.
.\venv\Scripts\python.exe -B -m survey.backend.tests.c2_v2_browser_fixture --port 8782
```

Tests never connect to hosted databases. They cover complete flow, score/parameter
blinding in practice and all listening cases, playback gates, condition allocation,
old/new invitation separation, v1/C1/C4 data isolation, strict ratings, stale
revisions, authenticated ownership, server recreation, screen failure, exports,
Cannot judge handling, withdrawal and fingerprint rejection. Browser QA checks
real playback/save, draft pause/resume, baseline/with-score screens and responsive
layout using clearly disposable fixture runs, not human-study results.
