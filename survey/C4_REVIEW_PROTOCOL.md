# C4 CLAP survey preparation

This document describes the retained review instrument. The new participant
release is documented in [C4 participant deployment](C4_PARTICIPANT_DEPLOYMENT.md);
it has a separate study ID, bundle and invitation set.

The retained C4 review is prepared around the user's stated C4 design: a frozen
bank of 200 CLAP-selected triplets, 20 different triplets per listener, two
hidden repeats and two practice comparisons. The target is 50–100 independent
listeners, with capacity for 100 assignments. This is a technical preparation
and review release (`c4_clap_review_v1`), not evidence of approval to recruit.
Its responses remain excluded from research analysis (`analysis_include=False`).
An approved formal launch needs its own frozen information and study version;
review records must not be relabelled as research data.

## Stimulus provenance

The bank comes from `c4_metric/synthetic_data/clap_triplets.csv`, last changed in
commit `db4ce9b` on 14 October 2026. It preserves the existing 200 reference/A/B
triplets rather than selecting a new bank. Each triplet contains three distinct
sound IDs, and its 600 sound IDs are globally distinct across the bank.

The source generator's CLAP bands are rank ranges among the candidates still
unused when each triplet is created: the nearer candidate uses the 5–20% band
and the other candidate uses the 20–40% band. The candidate pool shrinks from
1,023 to 426. These are neither cosine-score percentages nor fixed ranks in
the complete 1,024-sound pool. The displayed A/B side is counterbalanced by the
survey assignments, so it must not be interpreted as a CLAP preference label.
There is no researcher-supplied correct human similarity answer.

The packaged bank contains 600 mono, 44.1 kHz, three-second PCM16 playback
files. Their bytes were reconstructed and verified against the saved source
hashes using the current raw masters, saved gains and original DC-removal and
encoding policy. CLAP feature preparation resamples to 48 kHz; the survey uses
the frozen playback files. The original source-manifest hash differs from the
current manifest; six selected bank raw-path strings also differ, while all
selected audio hashes match. The audit does not identify every historical
manifest difference. Bundle provenance records the original source-manifest hash
and frozen bank/asset hashes. Default builds do not depend on a local copy of the
full corpus; a current manifest can be recorded explicitly for a separate build. This update does
not rerender the synthesizer or change the source triplet selection.

## Assignments and coverage

The 100 assignments are ordered in ten groups of ten listeners. In each group,
the 200 bank triplets are shuffled and divided into ten sets of 20. Each set
has 20 distinct primary triplets; groups vary the mixture, order and displayed
candidate sides. Two separated, swapped-side repeats are added to each set.
They appear as ordinary comparisons and do not add independent judgments.
Two separate practice comparisons precede the 22 review comparisons, giving
24 presentations per completed session.

Complete groups of ten listeners provide one primary judgment per bank triplet.
Completing the first five groups gives five judgments per triplet; completing
all ten gives ten. The 50–100 target therefore plans 5–10 judgments per triplet
when groups are completed. At least two different completed listeners per
triplet is a coverage floor, not a claim of statistical precision or approval
of the sample size. Missing, failed, withdrawn or replaced sessions can leave
uneven coverage even when many invitations have been issued.

The admin panel separates the assignment plan from completed coverage. It shows
completed listeners, triplets with any completed judgment, triplets reaching
two completed listeners, the minimum/maximum completed judgments, and each
triplet's planned and completed counts. Only primary comparisons from completed,
nonwithdrawn and nonreplaced sessions count. Practice, hidden repeats and
correction revisions do not increase replication. Give each independent person
one invitation; separate browser sessions alone cannot establish that two
responses came from different people.

## Listener flow and answers

1. Read the information and consent, confirm the adult/headphone/quiet-place
   requirements, describe practical music or sound experience, and enter a C4
   invitation. Entry uses the shared `experience_tags_v1` catalogue with optional
   details; an alternative typed example needs at least 20 characters.
2. Set a comfortable listening level and complete six headphone questions
   (five correct answers are required to continue).
3. Complete two practice comparisons, then 22 review comparisons. A break follows
   review comparison 11. Pause/resume is available throughout.
4. Give feedback about instruction clarity and session length.

Each comparison presents Reference, Sound A and Sound B. The listener chooses
the candidate with the more similar overall timbre, considering tone and its
change over time without choosing solely by loudness. A/B choices require
confidence from 1 (not confident) to 5 (very confident). “I cannot decide”
records uncertainty, not equality, and has no confidence score. Comments are
optional. The survey does not identify repeats or show CLAP scores to listeners.

One audio element prevents overlapping clips. Native playback controls and
completion indicators require all three clips to play fully before an initial
answer can be saved. Seeking over unheard ranges does not satisfy that gate.
These browser interaction checks do not establish attention. Page pause/resume
keeps answers and completed-clip counts; refreshing can lose an unfinished draft
and require listening to the current comparison again.

The immediately previous response can be corrected before any clip from the
next comparison is requested, including at the break and final-feedback step.
Replay is optional during a correction. Original answers remain immutable;
exports include the latest answer, first answer and complete correction audit.
Consistency analysis must distinguish first answers from later corrections.

## Invitations, hosting and older sessions

Use `/c4` for listeners and `/c4/admin` for researchers. The admin panel uses
the existing researcher login and loads assignments automatically. **Create
participant invitations** creates missing codes; save the private CSV when it
is shown because plaintext codes cannot be retrieved later. Give each listener
one code and the C4 link. Assignment order identifies the coverage groups.

**Replace lost code** replaces an unused code. **Replace unused codes and
download all** replaces unused codes and creates missing ones, skipping every
assignment with a started session. Previously distributed unused codes then
stop working. Replacing a started review assignment closes its session but
keeps its audit. Downloaded tracking CSV names/dates/notes are local only and
are not uploaded. Researcher-account invitations and C1 participant codes are
separate from C4 invitations.

C4 shares the Render service and persistent Neon database with C1 but uses
separate `c4_*` tables, invitations and browser token storage. The new
`c4_clap_bundle.json` is versioned separately from the unchanged historical
`c4_bundle.json`. Sessions retain their saved bundle hash, protocol snapshot,
assignment and trial order. Historical sessions resolve their original bundle
and audio so they can resume; they are not converted into the new design.
New entry and invitation management use the active version. Full CSV exports
retain study and bundle identifiers for separating versions.

The historical review had ten unique triplets, two repeats and two practices,
16 assignment slots and a break after six review comparisons. Sessions retain
their original navigation policy, including forward-only behavior where it
was originally saved. Withdrawal excludes responses without immediately
erasing the audit. The older `/api/studies` prototype remains blocked remotely.
C1's instrument and invitations are unaffected.

## Verification and formal launch

Run backend tests, then `npm test` and `npm run build` in `survey/frontend`.
Checks cover the frozen source bank, assignment uniqueness/mixing, candidate
balance, hidden-repeat spacing, full session flow, historical resume and audio,
coverage accounting, invitation isolation, correction audits and review-only
exports. Frontend checks cover the 22-comparison workload, 11-of-22 break,
planned versus completed coverage and legacy rendering.

Before a formal study, confirm the collection's training/evaluation purpose,
participant target and independence, uncertainty and repeat handling, grouped
held-out splits, final duration, contacts, retention, withdrawal, institutional
clearance and backup/restore arrangements with the C4 owner and supervisor.
The 50–100 target and CLAP-selected bank do not by themselves establish metric
validity or represent the full synthesizer space.
