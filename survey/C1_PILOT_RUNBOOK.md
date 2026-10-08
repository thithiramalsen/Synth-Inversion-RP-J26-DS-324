# C1 pilot: rehearse now, recruit after preparation

Updated 7 October 2026. The researcher lifted the render hold; 1,024 candidates and the 64+3 selection are complete. See [generation report](C1_CANDIDATE_GENERATION_REPORT.md).

**8 October update:** use [C1_PILOT_NEXT_STEPS.md](C1_PILOT_NEXT_STEPS.md) for the
current checklist and full 39-presentation rehearsal at localhost:8772. Section 1
below documents the older short diagnostic rehearsal. The C1 owner receives the
[handoff](../c1_timbre/C1_TEAMMATE_HANDOFF.md); feature redesign is not a requirement
for collecting ratings on the frozen sounds.

Protocol v3 now includes sustainedness alongside brightness, roughness and
percussiveness. New sessions have four descriptors; existing sessions retain
their original three-descriptor snapshot. No audio was regenerated. Do not pool
protocol versions in analysis. New exports include descriptor IDs and blank
sustainedness fields for older sessions that were never asked that question.

Follow-up code review and current local link: [C1_REVIEW_STATUS.md](C1_REVIEW_STATUS.md).

## 1. Try the local rehearsal

The prepared bundle is `data/processed/c1_rehearsal_v1/bundle.json`. It copies and
conditions existing combined-architecture diagnostics; it does not render Vital.
It has six unique study sounds, one hidden repeat and three practice sounds.
All rehearsal responses are excluded from research exports' inclusion flag.

From the repository root, if the service is not already running:

```powershell
.\venv\Scripts\python.exe -B -m survey.run_rehearsal
```

Open <http://127.0.0.1:8770/pilot>. Find the participant `invitation` value in
`data/processed/c1_rehearsal_v1/rehearsal_private_access.json`. The `admin_token`
in that same private file is for <http://127.0.0.1:8770/pilot/admin>, not participants.
Do not share the whole file. The server binds only to this computer.

Invitation codes are generated with Python's `secrets.token_urlsafe(18)` (18
random bytes, encoded as 24 URL-safe characters). One code is issued for each
assignment; starting a session consumes it. The database stores its hash. A
separate private bearer token saved in the browser enables resuming the session.
Closing the tab is fine: return to the same study URL in the same browser profile
on the same device while the study is available. Incognito mode or clearing site
data can remove that access. The invitation alone does not recover a session on
another device/browser. Cross-device recovery is not currently implemented.

Friendly labels such as `Listener 001` are persistent display aliases, not access
codes. The original random participant IDs remain unchanged in stored responses
and exports. The completion page confirms the saved response count and feedback.

Use headphones, start quietly and follow the volume and headphone checks. The
screen uses six three-interval trials; choose the quietest interval, with five
correct required to proceed. It follows the phase-cancellation geometry in
[Woods et al. (2017)](https://doi.org/10.3758/s13414-017-1361-2): 200 Hz, 1-second
tones, 100 ms ramps, 500 ms gaps and a -6 dB quiet interval. Our generated files
and volume-reference tone are an implementation adaptation, not a validated
replication of every original procedure. Keep screening audio stereo; never
normalize its deliberately different intervals. It does not calibrate sound
pressure, certify hearing, or prove that every passing listener wears headphones.

Check these things during the rehearsal:

- The final level-controlled synth clips are comfortable and audible; note any
  sudden level changes, clicks or distracting tails. RMS matching does not imply
  equal perceived loudness. The earlier DC audition did not test this gain rule.
- Brightness, roughness, percussiveness and sustainedness are understandable without coaching.
  Use the separate “cannot judge” choice for a confusing term.
- Refresh restores the saved step. Pause unmounts the player; resume requires
  replaying the current clip. Unsaved ratings are intentionally not retained.
- After saving a rating, “Correct previous sound” is available until the next
  presentation is explicitly started with “Start this sound”. It changes only the immediately previous response;
  the original answer remains in the correction audit trail.
- Complete the session, inspect the two CSV exports, and verify a withdrawal
  removes it from analysis. Rehearsal rows are always excluded regardless.

To repeat, use the researcher page to replace assignment `rehearsal`, give a reason
and download its new code. The previous responses remain in the audit log. On the
participant page, choose “Use another rehearsal invitation.” For independent
testers use separate named rehearsals/ports, e.g. `--name tester_two --port 8772`.
The short rehearsal cannot establish the full 39-presentation session duration.

To rebuild frontend changes: run `npm run build` from `survey/frontend`, then
reload the browser. To prepare a missing rehearsal bundle from scratch:

```powershell
.\venv\Scripts\python.exe -B -m survey.prepare_c1_pilot --rehearsal-from-diagnostics
```

Existing bundles are refused to protect reproducibility. Use a new `--output`
directory when intentionally preparing a new version; never overwrite a bundle
that already has responses. Private files, audio and local databases under
`data/processed` are ignored by Git; they need a separate backup.

## 2. Finish the short protocol

Edit `survey/config/c1_pilot_v1.json` before production recruitment:

- Real researcher name/email and supervisor contact.
- The agreed retention/deletion and withdrawal arrangements, including any cutoff
  for withdrawal after reporting. The implemented withdrawal marks data excluded;
  it does not erase it. Replace draft participant-information wording accordingly.
- Supervisor-confirmed eligibility and acceptable evidence. Current questions
  record self-report only. Review eligibility before issuing invitations; do not
  label the sample “experts” on the strength of a tools list alone.
- Record the actual institutional review outcome. Accepted launch values are
  `approved` or `reviewed_clearance_not_required`; neither is an exemption created
  by the software. See the readiness document for SLIIT's preliminary-review route.
- Mark the level audition and full rehearsal complete only when actually done.

Freeze the information and protocol version before recruitment. Every session
saves the exact protocol snapshot and hash; mixed versions are rejected by the
analysis helper. These launch checks prevent accidental opening; they are not
an institutional review mechanism.

## 3. Prepared production audio

The selected generator now preserves unconditioned FLOAT WAVs and writes separate
10 Hz DC-conditioned FLOAT candidates under `restricted_bend_sustain_v4`. The
new code passed 21 generation tests and generated the authorized 1,024 candidates.
All 1,024 passed technical selection checks; the 64+3 bundle is now prepared.
Historical audio and models have not been converted.

The completed preparation used this command (do not rerun into the existing bundle):

```powershell
.\venv\Scripts\python.exe -B -m survey.prepare_c1_pilot --manifest data/manifests/restricted_bend_sustain_v4.csv
```

Preparation requires at least 67 eligible unique candidates. It verifies source
hashes and format, rejects clipping, silence, residual DC warnings, nonquiet tails
and exact duplicates, and selects 64 study plus three separate practice sounds.
Selection is greedy maximin over equally weighted parameter and acoustic blocks;
acoustic dimensions are scaled by their 5th–95th percentiles. This is a documented
diversity heuristic, not proof of perceptual independence or complete coverage.
Inspect exclusions, parameter marginal ranges and important joint projections
before freezing the bundle; exclusions can narrow the effective domain.

DC filtering occurs exactly once. A second policy applies constant gain per clip
to match note-on RMS over 0–1.5 seconds. The common nominal target is -27 dBFS,
lowered for every selected clip if needed to keep all peaks at or below 0.89.
Those engineering constants are provisional operating choices requiring audition,
not universal psychoacoustic standards. There is no limiter, fade or compression.
The bundle retains gains, policy/code/source hashes and pre/post metrics. FLOAT
feature WAVs and PCM16 playback WAVs represent the same processed signal at
different precision; do not reapply filtering or normalization.

The 16 connected overlapping assignments contain 32 unique sounds and four
separated repeats each, plus three practice clips. Each sound has eight primary
listeners if all 16 assignments complete. This is not a full balanced incomplete
block design. Counts are a feasibility budget, not a power calculation.

## 4. Deploy and run a full rehearsal before recruitment

No public deployment has been made. Choose hosting with HTTPS, a persistent
writable volume for SQLite, and backups. Install the backend requirements, build
the frontend, copy the immutable bundle and set environment variables from
`survey/.env.example` using the host's secret settings. Do not upload the repo's
raw datasets, private-access files or development databases to a public file host.
FastAPI serves the built `/pilot` and `/pilot/admin` routes from the same origin.

`SURVEY_REMOTE_MODE=1` disables historical APIs and API docs; researcher endpoints
require the secret admin token. Participant media requires each session's bearer
token. Do not put tokens in URL queries. Keep the backend behind HTTPS; use one
application instance for this small SQLite pilot. Do not use ephemeral storage.
The `.env.example` file documents settings; Python does not auto-load that file.

Use an explicitly labelled rehearsal copy of the full production bundle
(`rehearsal: true`, a distinct study ID and a separate database) for 2–3 usability
testers under the applicable institutional conditions. That checks full duration,
the mid-session break, devices, network recovery, comprehension and exports on
the deployed site. Keep production closed until that check and final audition.
Do not pool those rehearsal responses with the pilot.

When ready, set `SURVEY_C1_OPEN=1`. Create missing invitations from `/pilot/admin`,
save the one-time download privately and give one code to each eligible listener.
Replacement codes close the previous incomplete session while retaining it; use
the same assignment to fill missing coverage. A completed production assignment
cannot be replaced unless withdrawn. Separate contact/recruitment records from
the rating database and follow the agreed retention plan.

## 5. Export and inspect

Download both response and session-audit CSVs. The latter includes people who
failed the headphone screen or stopped before rating anything. Keep those counts
when describing attrition. `analysis_include=True` applies to completed production
sessions' primary/repeat rows only, never practice, withdrawal, replacement or
rehearsal. It does not certify eligibility or attention. Apply and report any
additional exclusions according to the frozen protocol, not desirable results.

```powershell
.\venv\Scripts\python.exe -B -m survey.analyze_c1_pilot --responses data/processed/c1-responses.csv --output data/processed/c1-summary.json
.\venv\Scripts\python.exe -B -m c1_timbre.extract_pilot_features --bundle data/processed/c1_pilot_v1/bundle.json --output data/processed/c1-features.csv
```

The summary reports coverage, unclear counts, distributions, sound medians and
repeat differences. Repeats do not become independent listeners. It deliberately
does not calculate an inappropriate complete-crossed ICC on the incomplete matrix.
Later agreement/uncertainty modeling must account for listeners and sounds.
Feature extraction verifies hashes and reads the already processed FLOAT signal.
Its current centroid/MFCC implementation is a development baseline with a known
[encoding-sensitivity issue](../generation/characterization/pcm_precision_v1/REPORT.md).
The extraction command is useful for diagnostics, but its outputs must not be
treated as validated perceptual features without the C1 owner's follow-up.
No pilot result validates automatic human labels across 135k sounds by itself.

## Verification commands

```powershell
.\venv\Scripts\python.exe -B -m pytest survey/backend/tests survey/tests generation/tests -q -p no:cacheprovider
```

The audio-preparation test uses synthetic signals to exercise the complete
64+3 selection, playback/feature equivalence, headphone phase/level structure and
tamper checks. API tests exercise all 39 presentations, hidden repeats, duplicate
submissions, authentication, exports and withdrawal. These are software checks,
not a replacement for the human rehearsal or auditory validation.
