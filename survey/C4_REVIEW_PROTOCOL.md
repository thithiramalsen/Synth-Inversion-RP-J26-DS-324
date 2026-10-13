# C4 hosted interface review

**14 October UI alignment:** C4 now uses C1's native audio controls and sticky
player styling, setup headings, listener badge, rating cards, pause, break,
feedback and completion presentation. Reference/A/B still share one audio
element, with explicit clip selection and full-listen indicators. Confidence
remains 1–5; uncertainty remains a separate answer. The study assets, assignments,
API answer schema and review-only status are unchanged.

This release adds `/c4` and `/c4/admin` to the existing Render service.
It is a supervisor/interface rehearsal. All C4 exports have
`analysis_include=False`. Main-study recruitment is deliberately not implemented
in this protocol; setting an environment flag cannot turn these records into
research responses.

## Listener task

1. Read the information and consent, give a brief music/sound-design experience
   example, and enter a C4 invitation.
2. Set comfortable device volume. Complete six headphone questions (5/6 pass).
3. Complete two practice comparisons.
4. Complete twelve review comparisons: ten unique triplets and two later repeats.
   Take a break after comparison six; pausing is available throughout.
5. Give feedback about clarity and session length. Saved steps resume in the same
   browser profile; a consumed invitation does not recover another browser's token.

## Researcher invitation workflow

Open `/c4/admin` and sign in with the same researcher account used for C1.
The updated panel loads invitation assignments and sessions automatically.
Each assignment is one listener's fixed set of comparisons. Invitation codes
for C1, C4 and researcher accounts are different.

- **Create participant invitations** issues codes only for assignments without
  an active invitation. Save `private-c4-invitations.json`; codes are displayed
  when created and cannot be retrieved again after leaving the page.
- An empty sessions table means nobody has started, not that no invitations were
  issued. The assignment table includes codes issued to unused assignments.
- If all assignments already have invitations and the download is lost, select
  **Replace lost code** on an assignment marked **Code issued · not started**.
  Enter a reason and generate the replacement. Its code is shown and downloaded.
- **Review replacement** on a started assignment requires acknowledging that
  its current session closes. Saved answers remain in the audit. Completion
  protection for any future formal study remains enforced by the backend.
- **Invite a researcher to the admin panel** grants teammate access; its code
  cannot start a participant survey.

On the earlier deployed panel, first click **Load sessions** to reveal the
participant invitation and replacement controls. All issued codes returning an
empty result from **Create missing invitations** is expected, not a survey outage.

Each comparison presents a reference, A and B. Choose the candidate with more
similar overall timbre, considering spectral and temporal character, without
choosing solely by loudness. A/B choices require confidence 1–5. “I cannot decide”
records uncertainty, not equality, and has no confidence score. Optional comments
are saved. There is no researcher-defined correct similarity answer.

One audio element prevents overlap; each clip selection restarts its audio.
Native play/pause, timeline and volume controls match C1. A clip only receives
completion credit if its native played ranges cover the duration; seeking past
unheard audio does not satisfy the gate. All three roles need completion before
submission. Pause/resume within the page preserves completed clip counts and
answers. An unfinished clip needs to be replayed after a pause. Refreshing the
page still requires listening again to the current comparison.

Play counts now follow native media play events, including resumes, as in C1.
Completion and play counts are browser-reported interaction checks, not proof of
human attention. The shared player stays visible while scrolling.
Answers may be changed before saving; previous-comparison correction is not in
this version. C1's existing correction policy is unchanged.

## Stimuli and assignments

`survey/deploy/build_c4_review.py` deterministically selects 30 distinct sounds
from the 64 current C1 primary playback assets (seed 41009) and groups them into
10 canonical triplets. Selection is independent of MFCC or other metric scores.
Two practice comparisons rotate the three separate practice sounds. No audio is
rendered or processed again; filenames and hashes point to the existing packaged
13-control playback assets. The C1 bundle remains unchanged.

There are 16 invitation assignments in eight pairs. Within each pair the order
and references match, and A/B are swapped. Different pairs have different seeded
orders. Repeats reverse the candidates from earlier comparisons and are separated
by at least six intervening positions in this design. Exports retain canonical
reference/candidate IDs, chosen sound ID, presentation order, repeat linkage,
confidence, uncertainty, timestamps, play counts and withdrawal state.

Sixteen slots are interface capacity, **not a statistically justified C4 sample
size**. Use consecutive assignment pairs when reviewing side balance. Missing or
unevenly completed pairs can unbalance realized A/B presentation.

Ten unique comparisons plus two repeats and two practice trials are a pragmatic
review workload. The provisional 10–15-minute estimate must be checked with real
reviewers. This convenient C1 subset is not representative evidence for the entire
131,072-sound space, and ten comparisons cannot validate or train the final metric.

## Hosting and access

- Same Render service, existing Neon database and researcher account; separate
  `c4_*` tables, invitations and browser token key. Startup adds tables only.
- Open `/c4/admin`, sign in, select **Load sessions**, then **Create missing
  invitations**. Save the downloaded codes privately. C1 codes do not start C4.
- To replace a lost/used review code, use an assignment such as `c4_review_01` and
  a reason. Earlier records remain audited and excluded.
- `c4_bundle.json` is packaged in Docker. Startup verifies its audio hashes.
  Config and stimulus hashes are saved with sessions; config text is frozen on
  entry. Changing the bundle blocks old sessions rather than silently changing
  their stimuli. Plan a new version if the sampling design changes.
- The older `/api/studies` prototype remains blocked in remote mode.
- Withdraw marks records excluded; it does not immediately erase audit records.

## Before a research pilot or main study

Confirm with the C4 owner/supervisor whether data are for feasibility, metric
training or independent evaluation. Freeze the triplet sampling frame and strategy,
independent participant target, judgments per triplet, uncertainty/repeat handling,
and sound-grouped held-out split. Decide if people join both C1 and C4 and how
order/burden will be managed. Complete institutional clearance, contacts, retention,
withdrawal arrangements and backup/restore validation. Use a new study version
and approved information rather than relabelling review records.

Triplet human judgments have precedent in [CDPAM (Manocha et al., 2021)](https://arxiv.org/abs/2102.05109).
That paper does not validate this synth-domain sample size. The headphone-screen
procedure follows [Woods et al. (2017)](https://pmc.ncbi.nlm.nih.gov/articles/PMC5693749/);
it does not standardize headphones or calibrate sound level at the ear.

## Verification

Run backend and frontend checks before pushing the deployment branch:

```powershell
.\venv\Scripts\python.exe -B -m unittest discover -s survey/backend/tests -v
cd survey/frontend
npm test
npm run build
```

C4 API tests cover authenticated invitations, one-use entry, setup/order gates,
all-three exposure checks, full completion, resume, duplicate submissions,
canonical A/B exports, CSV formula escaping, withdrawal, replacement, modified
audio and review-only gating. Design tests check deterministic selection,
distinct sounds, candidate counterbalancing and repeat spacing. They use an
isolated SQLite database unless the dedicated PostgreSQL suite is selected.

The UI alignment was checked in a separate local simulated-session database:
native volume playback, headphone setup, Reference/A/B playback, preservation
after pause, confidence selection, saving/advancing, and break/feedback/completion
screens. Frontend tests cover full native playback versus skipped ranges, C1-style
player rendering, retained completion checks and five-point confidence/uncertainty.
