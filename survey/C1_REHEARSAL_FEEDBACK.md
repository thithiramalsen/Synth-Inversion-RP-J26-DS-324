# Rehearsal feedback and follow-up — 7 October 2026

The researcher's completed local rehearsal contains three practice responses,
six primary responses and one repeat (30 descriptor judgments total), all six
headphone questions and final feedback. Recorded duration from session start to
feedback submission: about 7 minutes 22 seconds. Final choices: “Clear” and
“About right.” These are rehearsal observations, excluded from research analysis;
they do not establish the burden of the full production session.

Implemented following that feedback:

- Persistent display labels (`Listener 001`, etc.), mapped to the unchanged
  participant and session IDs. Labels grant no access to the session.
- Explicit completion confirmation of saved sound responses and final feedback.
- Concrete experience prompt: one example of making music or shaping a sound,
  one short sentence naming the activity and tool, with personal practice allowed.
  This is self-report, not independent verification of expertise.
- Clear resume instructions: the tab can close; return to the same URL/browser
  profile/device while the study remains available. The start invitation does not
  function as a reusable login. Browser storage holds a separate private token.
- New sessions use protocol/information version v2. Existing session snapshots
  and all completed responses are preserved. A local SQLite backup was made
  before applying the display-label migration.

## Limited previous-sound correction

The suggested back button is a correction to the immediately previous response
only before the next sound is played, with original and revised answers retained
in an audit trail. The participant can open “Correct previous sound” after
saving a response and before selecting “Start this sound” for the next presentation.
The form restores the latest saved answers (initially the original response);
saving appends a revision while preserving
the original `c1_ratings` row. Refresh does not reopen a correction that has
already been locked. Merely loading the next page does not lock it; the explicit
Start action records exposure before releasing audio. Replaying during correction
is optional. Correction is also available at the break and before final feedback.

Unrestricted comparisons and earlier-answer review would change the response
process and could make a hidden repeat a consistency-with-visible-answers task.
This limited policy is versioned as `previous_before_next_play_v1`, supported
server-side, and deliberately avoids a browser-history button or silent
database overwrite.

## Scale references

Recommendation for this first descriptor pilot: retain clear verbal definitions,
verbal endpoints and varied practice clips, without prescribing that a particular
clip must receive 1 or 7. Familiarization still supplies context; keep its clips
and instructions fixed and report them. Wider stimulus coverage and explicit
endpoint training are separate decisions.

The researcher's six primary rehearsal clips received brightness ratings 4–7,
roughness 4–7 and percussiveness 1–5. That motivates checking variety in the
production selection, not correcting this listener or forcing use of every scale
point. These diagnostic clips are not a representative pilot pool.

References are not inherently invalid. The MUSHRA audio-quality standard uses
reference/anchor conditions and notes both scale stabilization and the influence
of anchors on results. Its audio-system quality task does not automatically
validate “maximum brightness” examples for our semantic study:
[ITU-R BS.1534-3](https://www.itu.int/dms_pubrec/itu-r/rec/bs/R-REC-BS.1534-3-201510-I!!PDF-E.pdf).

A more directly relevant example is
[Reymore et al. (2022)](https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2022.796422/full):
the authors sought broad likely semantic variation, refined their selection using
a preliminary pilot and familiarized listeners with sounds before collecting
semantic ratings. This supports separating stimulus familiarization and empirical
range checking from asserting absolute descriptor maxima. It does not establish
that our exact practice count, trait wording or subset is validated.

If later training anchors are needed, select candidate low/high examples using
independent ratings and inspect agreement/uncertainty, freeze them before the main
study, and describe scores as judgments under that reference-based protocol.
Avoid selecting anchors with the same predictor whose human validity is being
tested, or using main-study test labels to tune them. A synth control maximum or
largest spectral centroid alone is not an established maximum of human brightness.
