# C1 remote pilot: shortest path to launch

Repository audit: 7 October 2026. The researcher confirmed **remote online** delivery.
The researcher reports that the panel requires evidence of relevant music-making
or sound-design experience among participants.
This is a preparation checklist and proposed protocol, not a launched study or
an instruction to generate the held 1,024-sound pool.

## What this pilot will decide

Whether the descriptor instructions are understandable, whether selected sounds
produce useful rating variation, whether different listeners and repeat judgments
are sufficiently consistent to support further development, and whether the remote
procedure works in a manageable session. The results guide revisions and the design
of the later validation/effect studies. They do not establish full 13-dimensional
coverage or validate predictions for a 135k corpus.

Pilot objectives and progression decisions should be explicit. The general
feasibility principle is supported by [Thabane et al. (2010)](https://doi.org/10.1186/1471-2288-10-1);
that article is about clinical research and does not prescribe participant counts
for this audio experiment. Its warning about uncertain pilot-based sample-size
estimates also applies when planning later work: use sensitivity ranges, not one
precise-looking estimate from a small pilot.

## Actual repository status

| Item | Status | Evidence / consequence |
|---|---|---|
| Synth architecture | Selected | `restricted_bend_sustain_v4`: 13 controls, one oscillator, Bend and variable ENV2 sustain. Freeze the current provisional bounds for the pilot; do not reopen architecture solely to reach a round parameter count. |
| DC filter | Integrated for v4; historically auditioned | V4 now retains raw FLOAT WAVs and writes separate filtered FLOAT candidates. Historical datasets/models are unchanged. |
| New study stimuli | Not generated/selected | The 376 historical A/B settings describe other architectures; the 18 combined settings are sparse diagnostics. Neither set is a ready, representative pilot pool. |
| Survey audio source | Separate bundle implemented | `/pilot` reads an immutable C1 bundle. The local rehearsal uses existing diagnostics; production still needs the new candidate pool and selection. The old eight-control instruments are separate. |
| Assignment | Implemented and tested | 16 connected overlapping blocks, 32 unique + four repeats, eight primary listeners per sound. Replacement invitations retain the same block. |
| Questions | Implemented; human wording check pending | `c1_pilot_v1.json` defines brightness, roughness and percussiveness, 1–7 plus a separate unclear response. |
| Repeat presentations | Implemented and tested | Distinct presentation IDs point to the same sound; repeats are excluded from independent listener counts. |
| Remote entry flow | Implemented; human rehearsal pending | Consent, experience questions, volume setup, six headphone checks, practice, ratings, break, feedback, resume and withdrawal. |
| Hosting | Local rehearsal; public deployment pending | Admin exports require authentication; remote mode disables historical APIs. HTTPS, persistent storage and a full deployed rehearsal remain. |
| Institutional process | Preliminary review route identified; project status unconfirmed | SLIIT's published process calls for preliminary supervisor review, with detailed review conditional on the supervisor's recommendation. The external-organization permission-letter form supplied by the researcher is a different process. Confirm the current cohort's preliminary-review requirement/status. Technical preparation can proceed. |

## Six tasks before recruitment

### 1. Freeze the pilot instrument

For the shortest pilot, use **brightness, roughness and percussiveness** as the
three candidate primary traits. Use seven discrete points, 1 = not at all and
7 = very, with no preselected answer. Four is the middle degree of the trait,
not an uncertainty or “neutral” response. Offer a separate “cannot judge / unclear”
response so confusion is observable rather than coded as 4.

Working definitions to check during the rehearsal:

- Brightness: how much high-frequency or treble character the sound has.
- Roughness: how much rapid fluttering, beating or grating texture it has.
- Percussiveness: how strongly it resembles a struck/plucked event with a distinct
  onset followed by a fall in sound level.

These are candidate instructions, not validated wording. Ask rehearsal listeners
to explain them in their own words and revise before the pilot version is frozen.
Keep the survey language consistent and recruit listeners who can understand it.
If translations are needed, version and check them too.

Warmth and sustainedness can be explicitly exploratory additions if desired, but
they add 72 judgments per participant with the proposed repeat trials. Do not
silently retain the old thin/warm pairing or promise all five traits will work.
Timbre-semantic research supports studying verbal dimensions, while their mapping
to perception and acoustics must be checked for this domain; it does not validate
our exact questionnaire. See [Zacharakis et al. (2014)](https://doi.org/10.1525/mp.2014.31.4.339).

### 2. Finish and version audio preparation

Integrate the selected 10 Hz filter exactly once; retain unconditioned FLOAT
renders, processed-audio hashes and the policy ID. Check finiteness, duration,
silence, clipping, DC, peak and ending behavior before/after processing. The current
generator now implements this for v4. Tests cover extension without changing saved
WAVs and refusal of modified raw evidence.

**Level handling has been implemented for audition.** In the saved DC experiment,
post-10-Hz full-clip RMS spans approximately 19.31 dB across the 18 combined settings
(−41.09 to −21.78 dBFS), and 29.33 dB across the earlier 376 A/B settings. These are
electrical level differences, not measurements of perceived loudness.

For this descriptor pilot, the recommendation is to evaluate one fixed per-clip
gain rule after DC filtering: RMS matching over the common 0–1.5 s note-on window,
with a single target chosen low enough to retain peak headroom across the pool.
Use a constant gain within each clip, preserving its envelope shape; no compressor,
limiter or per-clip peak normalization. Review gain extremes and low-energy clips
before freezing the rule. Equal RMS is only an operational level control, not
proof of equal perceived loudness. Record the gains and apply the same definition
to the audio used for this study's features and later measurement comparisons.

`held_rms_gain_v1` implements this separately from the DC-only policy: nominal
-27 dBFS, lowered globally when necessary for a 0.89 peak ceiling. Those values
are engineering starting points, not psychoacoustic guarantees. Its rehearsal
gain range is about -7.72 to +10.80 dB. Audition the final level-controlled clips
before marking the rule checked; the earlier DC-only listening is insufficient.

### 3. Create a fixed 64-sound stimulus manifest

After audio preparation is finalized and the render hold is lifted, generate a
versioned candidate pool from the selected 13-control domain. The planned 1,024
is a computational candidate count; only the selected pilot subset is human-rated.
The full scaled corpus is unnecessary for this pilot.

Select **64 unique patches**, each a complete combination of all 13 controls.
Use a reproducible selection based on parameter spread plus complementary acoustic
features after the declared processing, retain varied temporal/spectral examples,
and remove only documented technical failures or duplicates. Do not select solely
on a predicted descriptor score that the pilot is meant to assess. Save seed,
candidate IDs, gains, exclusions and audio hashes. Check marginal ranges and key
joint projections, and report them as coverage diagnostics rather than complete
coverage. Low/mid/high observed ratings are an outcome, not labels to manufacture.

Choose practice examples separately and exclude their responses from analysis.

### 4. Implement balanced assignments and the remote flow

Retain the earlier **planning budget**:

| Quantity | Proposed value | Purpose |
|---|---:|---|
| Unique study sounds | 64 | A varied development set with equal replication, not one sample for every part of the domain. |
| Analyzable completed participants | 16 | Supplies the planned replication at the stated per-person workload. This is not a power-derived minimum. |
| Unique sounds per person | 32 | Half the set, keeping workload manageable while creating overlap among listeners. |
| Independent listeners per sound | 8 | `16 × 32 / 64 = 8`; enables preliminary disagreement/uncertainty estimates. No guarantee of sufficient reliability. |
| Hidden repeats per person | 4 | A small preliminary within-listener consistency check; four is a pragmatic burden allocation. |
| Rated presentations per person | 36 | 32 unique + 4 repeats; practice and headphone checks are additional. |
| Primary trait judgments per person | 108 | 36 × 3. With all five traits this becomes 180. |

There are 512 unique participant–sound evaluations and 1,536 primary trait ratings,
plus 64 repeat evaluations / 192 repeat ratings. Repeated presentations do not
increase the count of independent listeners per sound. These judgments also do
not turn 16 people into 1,536 independent experimental units.

Create connected, overlapping assignments with 32 distinct sounds per person and
eight different listeners per sound. Balance actual completed assignments, not
just issued invitations. Randomize order, separate a repeated sound from its
first occurrence, retain order/assignment IDs, and plan how incomplete blocks are
replaced. Keep partial/failed sessions in the audit log with explicit inclusion flags.

Remote flow: participant information/consent → quiet-environment and headphone
instructions → comfortable volume setup → headphone screening → brief background
questions → practice → 36 rating presentations with a break → wording/length feedback.
The implemented form collects the background questions with consent, before audio
setup, so headphone failures are still represented in the session audit.
Apply the panel's reported experience requirement through a short eligibility
screen: relevant activity (music production, synthesis, sound design), duration
and recent frequency, tools used, and one brief example of work. The exact inclusion
criterion and what counts as proof must be agreed with the supervisor; no arbitrary
years-of-experience cutoff has been adopted here. A short self-report is not
independent verification. If corroboration is required, agree acceptable evidence
and how to keep identifying links/material separate from rating exports. Do not
silently require a public portfolio or equate familiarity with a DAW to expertise.
The target population and later claims would then be experienced listeners, rather
than all listeners. Do not pool general-listener recruitment under that label.

A published
headphone screen such as [Woods et al. (2017)](https://web.mit.edu/maxs/www/papers/app_2017.pdf)
is preferable to relying only on “please use headphones”; it does not calibrate
absolute listening level or certify normal hearing. Preserve stereo for the
headphone-screen stimuli even though the study's synth files are mono.

### 5. Make remote data collection dependable

Use a stable HTTPS deployment with persistent storage/backups. Protect researcher
exports and admin access; avoid exposed local development endpoints. Check playback,
resume after refresh, failed requests, duplicate submission handling, missing
responses and exports. Each response must retain study version, presentation ID,
sound ID, participant/session ID, assignment/order, answers or uncertainty flags,
playback information and timestamps. Link the study version to its immutable
audio/processing manifest. Keep previous engineering-study responses separate.

Follow the institution's applicable review and participant-information process.
The researcher supplied an external-institution data-access/visit letter workflow.
It names an organization, recipient and collaborating representative; on its face
it does not establish the requirement for a remotely recruited individual volunteer
survey. Organization-mediated recruitment may still need that organization's permission.

The separate [SLIIT Ethics Review Process](https://elibrary.sliit.lk/Ethics%20Review%20Process%20%281%29.pdf)
says BSc/MSc students submit a preliminary ethics form to their supervisor and upload
the signed form to the RP CourseWeb submission. Detailed review follows if the
supervisor recommends it. Confirm current-cohort instructions and whether preliminary
review is already covered. Do not presume a full application is mandatory or that
the panel's participant-experience comment settles this process.

Suggested message for the researcher to send (not sent by this task):

> We plan a remote listening pilot with 16 participants who have music-production
> or sound-design experience. They will rate short generated synth clips after
> participant information and consent. Does our project need the Preliminary
> Ethics Review Form, or has this already been covered for our cohort? The form
> currently visible to us is for obtaining data from an external institution.
> Please also confirm the eligibility criterion and acceptable evidence of experience.

### 6. Rehearse with 2–3 testers, then collect the pilot

Use 2–3 test sessions through the actual remote deployment, under the applicable
institutional conditions. Check comprehension, comfort, timing, playback, refresh,
submission and CSV/database agreement. These sessions are a usability rehearsal,
not additional independent evidence for descriptor reliability. Retain a separate
test-data designation. Aim for roughly 15–20 minutes, then use measured completion
times to revise the burden before recruiting; that duration is a target, not a
measured result.

Write the analysis/progression plan before collecting the 16 completed sessions:

- Workflow failures or unreliable exports: fix and rehearse again before recruitment.
- Confusing instructions: revise before freezing the pilot version; collect end-of-session wording feedback.
- Inspect per-trait missing/unclear responses, rating distributions and floor/ceiling
  patterns. Do not require every integer 1–7 to occur or force a uniform histogram.
- Summarize hidden-repeat differences and between-listener agreement with uncertainty;
  account for the incomplete assignment design and dependence within listeners/sounds.
  Do not run a complete-crossed ICC formula on the incomplete matrix without justification.
- Clear instructions but little trait variation: extend stimulus diversity or restrict
  the claimed domain. Do not stretch labels to fill the scale.
- Persistent disagreement/confusion: revise or drop the trait; do not promise a
  human-valid predictor regardless of pilot results.
- Any exploratory prediction comparison uses sound-disjoint folds and keeps near-
  duplicate families together. Development results are not untouched validation.

The later main-study size must be based on its declared precision/validation goals,
using plausible ranges informed by this pilot. Neither the 64-sound budget nor a
single favorable reliability/model score certifies adequacy for the entire project.

## Start here

Try the implemented local rehearsal using [C1_PILOT_RUNBOOK.md](C1_PILOT_RUNBOOK.md).
Audio preparation and the new versioned survey are implemented and software-tested;
human audition, final protocol details, production selection and public deployment
remain. Finalize the remote recruitment conditions alongside that work.
Do not spend time generating 135k sounds, training a large model or testing all
parameter interactions before this pilot. The existing 1,024-render hold remains
in force until explicitly superseded.
