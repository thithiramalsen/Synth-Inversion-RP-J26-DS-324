# C1 preparation verification — 7 October 2026

Implemented preparation and a local rehearsal; no production recruitment or
public deployment. The 1,024-candidate render hold was preserved.

## Checks completed

- 18 distinct survey tests passed across focused runs: eight preserved API tests,
  eight new pilot/design tests, and two preparation/analysis tests. The final
  eight pilot API tests were rerun after the server-timestamp change.
- 21 generation tests passed. The five affected audio/combined-profile tests
  were rerun after adding the two-to-four-sample resume and raw-tamper checks.
- Frontend production build passed after final changes.
- Browser check: entry/consent, actual volume-tone playback, disabled continuation
  until playback ends, headphone-screen rendering and refresh recovery. No browser
  console warnings/errors were reported in that check. The full rating/break/
  feedback/withdrawal journey is API-tested; a full human/browser rehearsal remains.
- Synthetic production-bundle test: 68 artificial candidates, 64 study + three
  separate practice clips; 16 assignments of 39 presentations; source hash
  preservation; equivalent FLOAT/PCM16 signals; verified headphone interval levels
  and phase; 64 feature rows; tampered audio refused. These fixtures are not
  research observations or Vital domain-coverage evidence.
- Response accounting: repeats do not increase independent listener counts;
  invalid ratings, duplicate submissions and mixed study/protocol versions are
  rejected; failed/partial sessions remain in the session audit; rehearsal data
  cannot use the production study ID.
- Protected historical file fingerprint unchanged: 1,457 files, SHA-256
  `618d6e37fe787b08cd08d8c741a4dd479fe21d91e0525b0f550ca41643f2d037`.
  It covers old manifests/audio, A/B raw WAVs, A/B presets and their configuration
  modules, using sorted repo-relative paths plus each file's SHA-256 bytes.

The local rehearsal bundle has six study clips, three practice clips and one
repeat, drawn from existing combined diagnostics. Its note-on RMS target is
-27 dBFS; constant gains range approximately -7.72 to +10.80 dB. It is explicitly
not representative pilot coverage. Its saved policy/code hashes are snapshots
of preparation time; later code/documentation changes do not rewrite the bundle.

## Still needed

Researcher audition of the new gain rule; wording/comprehension checks; real
contact and retention details; supervisor-confirmed eligibility and institutional
review status; authorization to render the candidate pool; production selection
and coverage review; HTTPS/persistent storage; and a full remote rehearsal.
No formal descriptor validity, agreement, prediction accuracy or 135k-corpus
generalization has been established by these software checks.
