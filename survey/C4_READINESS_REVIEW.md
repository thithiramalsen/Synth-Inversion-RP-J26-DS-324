# C4 survey review 7 October 2026

The C4 perceptual-similarity survey exists as an internal development prototype.
It is not yet a participant-ready counterpart to the newer C1 pilot. This review
does not change the questionnaire, generate audio, or enable public routes.

## Existing implementation

- `survey/config/c4_triplets.json`: ten trials, reference/A/B comparison, forced
  A/B choice, confidence from 1 to 5, optional comment.
- `survey/frontend/src/main.jsx`: survey interface and resume using the saved
  session ID. The separate `DemoApp.jsx` is a demonstration, not this instrument.
- `c4_metric/development_triplets.csv`: ten frozen triplets from the old
  `pilot_v1` sound set, not the selected 13-control configuration.
- `c4_metric/select_triplets.py`: candidates selected from two different MFCC
  rank bands; A/B placement randomized once when the manifest is generated.
  Trial order is randomized per session, but candidate placement is shared.
- `survey/backend/main.py`: saves choices, confidence, playback-start counts and
  MFCC metadata. Its remote-mode middleware blocks these historical routes.
- `c4_metric/mfcc_baseline.py`: simple pooled agreement with the supplied triplet
  manifest, without participant/triplet uncertainty or held-out model evaluation.

## Changes recommended before recruitment

1. State whether this collection pilots the task, supplies metric-training
   labels, or provides held-out evaluation. Ten development comparisons cannot
   establish adequacy for all three purposes. Define replication and precision
   goals before fixing the research sample size.
2. Bring C4 into a versioned authenticated study flow with consent, eligibility,
   comfortable-volume setup, headphone screening, practice, withdrawal, stable
   resume, immutable audio/protocol hashes, and protected exports. Do not simply
   disable the remote-mode restriction to expose the old endpoints.
3. Rebuild stimuli from the declared sound domain and processing policy. C1 and
   C4 can share the 13-control candidate pool, but C4 need not be restricted to
   C1's 64 selected sounds. Specify whether overall level is controlled or part
   of the intended similarity judgment. Keep feature inputs consistent with
   the audio presented to listeners.
4. Prevent overlapping playback and require a full listen to all three clips
   before the first answer. The current interface only counts playback starts;
   starting and immediately stopping each clip meets that gate.
5. Counterbalance A/B presentation across listeners, preserve its mapping to
   canonical sound IDs, include separated repeat trials, and report agreement
   using sound identities rather than raw display letters.
6. Broaden selection beyond MFCC near/far bands. This construction is useful
   development sampling, but evaluates a distribution selected by the same
   baseline. Include a predeclared broader sample, and optionally a separately
   reported subset where candidate metrics disagree. MFCC rank is not a human
   correct-answer label. Do not reject listeners for disagreeing with MFCC.
   The 8 October [precision audit](../generation/characterization/pcm_precision_v1/REPORT.md)
   found encoding sensitivity in the development C1 features. This selector
   defaults to `c1_timbre/outputs/c1_audio_features.csv`; review or replace that
   feature dependence before freezing C4's main-study comparisons. The finding
   does not by itself require regenerating the underlying synth sounds.
7. Decide whether to retain forced A/B plus confidence or allow an explicit
   indistinguishable/uncertain response; these are different instruments.
   Do not silently encode uncertainty as a preference or drop low confidence.
8. Separate development, training and evaluation data; keep shared source sounds
   and near-duplicate families together in splits. Freeze preprocessing using
   training/development data and quantify participant/triplet dependence.
   The baseline analysis should use frozen session metadata or verify manifest
   hashes, so later manifest edits cannot silently change reference predictions.

Triplet judgments have precedent in perceptual audio metric learning, including
[CDPAM](https://arxiv.org/abs/2102.05109). Its speech-focused results do not validate
this synthesizer domain or prescribe this study's participant/trial counts.

## Relationship to C1 and the ethics application

C1 asks how much a sound exhibits descriptors. C4 asks which candidate resembles
a reference more. Describe both procedures, recruitment, workload and analysis
in the application if both will be collected under the project; the supervisor
and ERC determine whether one application covers them. If the same people do
both tasks, account for combined burden and potential order/familiarity effects.

The supplied June 2026 SLIIT application explicitly names the supervisor as PI
for student research, requires permission before fieldwork/data collection,
requests storage/security and retention/destruction details, and lists participant
information, consent, questionnaire and recruitment materials as supporting
documents. It separately notes management approval for recruiting SLIIT students
or staff. Receipt of the blank form is not approval. Technical preparation and
synthetic audio rendering can continue; participant collection must follow the
applicable permission stated in the form.

## Free hosting direction

A possible zero-cost configuration is Render Free for the existing FastAPI app,
built frontend and immutable selected audio, with Supabase Free Postgres for
responses. It requires adapting and testing the SQLite database layer; it is not
a configuration-only deployment of today's application. Keep database credentials
server-side and preserve invitation/session checks and transactional writes.

Render Free sleeps after 15 minutes without traffic and can take about a minute
to wake. Its local filesystem is ephemeral, so do not store research responses
there. Supabase Free currently includes a 500 MB database, 1 GB object storage,
5 GB egress and pauses after a week of inactivity; automatic backups are not
included. Plan independent exports/backups and test resume after host restart.
This is a limited free-tier option, not an uptime guarantee.

Official sources checked 7 October 2026:
[Render Free](https://render.com/docs/free),
[Supabase pricing](https://supabase.com/pricing).

No hosting account or public deployment was created during this review.
