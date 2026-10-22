# C1 main study design (draft, 14 October 2026)

> **Status: dry run.** No human pilot data exist yet. Every pilot-driven number
> below comes from the SIMULATED pilot (`c1_timbre/simulated/c1_pilot_sim_v1`).
> The procedure is final; its outputs are not. After the real pilot, rerun the
> planner on the real export (see "Rerunning with the real pilot") and treat that
> run as the candidate main-study stimulus set.

## 1. Fixed inputs

| Item | Value |
|---|---|
| Labelled sounds | 128 study sounds + 3 practice sounds (the pilot's practice sounds) |
| Participants | 30 completed sessions |
| Domain | v4 corpus: one Vital oscillator, 13 controls, MIDI 60, 1.5 s hold, 3 s render |
| Descriptors | brightness, roughness, percussiveness, sustainedness, 1–7 scale + "cannot judge" |
| Audio policy | `dc_highpass_10hz_v1` once, then `held_rms_gain_v1` with the pilot's exact RMS target and 0.89 peak ceiling |
| Features | `c1_features_v2` ([features_v2.py](../features_v2.py)) |

## 2. How the pilot result drives the design

[`plan_main_study.py`](../plan_main_study.py) reads a pilot export and applies
written rules. Each rule is a named constant, and each run records them in `decisions.json`.

| Decision | Rule | Dry-run outcome (simulated pilot) |
|---|---|---|
| Descriptor kept or revised | Flag a descriptor if unclear > 15%, ICC(1) < 0.15 or IQR of per-sound means < 1.0. Flag a pair as redundant if \|r\| > 0.85 | All four retained. Roughness is weakest (ICC 0.38, 8% unclear). Percussiveness and sustainedness r = −0.60, so not redundant |
| Wording review | More than 30% of feedback says "some terms unclear" or "difficult" | **Triggered (56%)**. Review the definitions with the supervisor before the main study |
| Sounds per person (S) | Largest minimum listeners per sound (k = ⌊30·S/128⌋ ≥ 5), with predicted median session ≤ 25 min; then the smallest such S. Capped at 20 if more than 30% say "too long" | **S = 22** → k = 5 (20 sounds get 6), predicted median 22.9 min. S = 26 (k = 6) would exceed 25 min |
| Hidden repeats | 2 per person. The pilot had none, so it could not estimate test–retest reliability | 27 presentations: 3 practice + 22 unique + 2 repeats |
| Spare blocks | ceil(pilot non-completion × 30 × 1.5), minimum 4 | 11% non-completion → 5 spares, capacity 35 |
| Expected reliability of sound means | Spearman–Brown applied to the pilot ICC(1) at k = 5 | brightness 0.84, roughness **0.75**, percussiveness 0.88, sustainedness 0.89. Roughness needs about 7 listeners to reach 0.80 |
| Stimulus emphasis | Pilot predictor (ridge) and pilot feature support; see section 3 | 19 of 128 selected sounds are outside the pilot's feature support |

The roughness shortfall is a real trade-off at 30 participants. Four options:
(a) accept 0.75 and report it; (b) recruit about 40 people (k ≈ 7); (c) revise the
roughness wording so agreement rises; (d) use fewer sounds. Decide after the real pilot.

The pilot predictor was fitted with ridge regression on 64 sounds, using 8-fold
cross-validation that holds out whole sounds. Its cross-validated R² was 0.67–0.80;
the same procedure on shuffled targets gave about 0. These scores only show that the
software recovers the rule that generated the simulated data. They say nothing about
how listeners judge timbre.

## 3. Stimulus selection

**Eligible pool.** All 131,072 corpus sounds were screened with the pilot's rules:
no clipping, not silent, no DC warning, final 50 ms below 0.001, no duplicate
audio, and v2 features extracted. One new rule was added: a clip must reach the
pilot's RMS target without exceeding the peak ceiling, so the level policy stays
identical. Result: 130,854 eligible, 151 level-incompatible, 67 pilot stimuli
set aside.

**Composition (128).**
- **16 anchors.** Pilot study sounds chosen by maximin over the pilot's per-sound
  means. They let you check drift between pilot and main study, and allow a
  linked comparison. Pilot and main ratings are still **not pooled**, because the
  protocols differ.
- **112 new sounds.** Picked by greedy maximin over three equally weighted blocks:
  - the 13 control values, scaled to unit range;
  - the 19 v2 features, scaled to the corpus 1–99% range;
  - the 4 descriptor scores predicted by the pilot model.
  The greedy step is quota-aware: a candidate's score is multiplied by
  1 + 0.5 × (number of under-filled quotas it helps).

**Quotas (all met in the dry run, no forced picks):**
- at least 18 sounds in every corpus quintile of each predicted descriptor;
- at least 24 in every quartile of each control's declared range;
- at least 6 with filter-envelope depth in the lowest 10% of its range (envelope controls
  effectively inactive);
- at least 6 with filter-envelope sustain ≥ 0.9 (filter-envelope decay inactive);
- at least 16 outside the pilot's feature support (nearest-pilot distance above
  the pilot's own 95th-percentile nearest-neighbour distance).

**Coverage, as reported.** The set is spread out on purpose: KS distance to the corpus is
0.04–0.26 per variable, with heavier tails than the corpus. See `distribution_comparison.csv`
and the two PNG plots. Any subset of a Sobol sequence loses the sequence's balance
guarantee, so claim only the observed ranges, not coverage of the whole 13D space.

## 4. Session protocol

Setup steps are unchanged from the pilot: consent, eligibility, volume check, a
six-trial headphone screen with a 5/6 pass mark, and the same three practice sounds. Then:

1. 22 unique study sounds + 2 hidden repeats, in an order randomized separately for
   each block.
2. A break after presentation 12.
3. Each repeat replays a sound from the first half, at least 6 trials after it
   was first played.
4. Feedback (clarity and length) at the end.

**Assignment.** 35 prefix-balanced blocks. Issue them in order and re-issue any
block that is not completed:
- After 30 completed blocks, 108 sounds have 5 listeners and 20 have 6.
- Exposure never differs by more than 1 between sounds at any prefix.
- Co-occurrence is used to break ties, which keeps listeners connected through
  shared sounds.

This is not a balanced incomplete block design (BIBD).

## 5. Planned analysis (fix before collection)

- **Primary target:** per-sound mean of valid ratings ("cannot judge" counts as
  missing). Keep the count and SD, and use the median or an ordinal mixed model
  (random effects for listener and sound) as a robustness check.
- **Reliability:** ICC(1) and ICC(1,k) per descriptor; test–retest from hidden
  repeats (median absolute difference, share within ±1).
- **Model:** ridge per descriptor on `c1_features_v2`, compared against a
  training-mean baseline. Use grouped cross-validation by source sound, with the
  hyperparameter search nested inside it and a held-out test split fixed before
  fitting. Report MAE, Spearman ρ, R², predictions outside 1–7 and results by
  acoustic region.
- **Negative controls:** shuffled targets and feature-ablated models.
- **Anchors:** compare the 16 sounds' pilot and main means descriptively. Do not
  pool them.

## 6. Outputs

| Path | Content |
|---|---|
| `c1_timbre/main_study/<version>/decisions.json` | All rules, the session options considered, reliability projections and coverage |
| `.../pilot_analysis.json` | Pilot descriptives, timing, feedback, predictor CV and shuffled controls |
| `.../selected_sounds.csv` | 128 sounds: source ID, anchor flag, predicted scores, support, 13 controls, features |
| `.../coverage_constraints.csv`, `distribution_comparison.csv`, `*.png` | Coverage evidence |
| `.../assignments.json` | 35 blocks |
| `.../c1_main_protocol_DRAFT.json` | Protocol config draft (pilot wording unchanged; numbers updated) |
| `data/processed/<version>/bundle.json` + `audio/` | Level-matched PCM16 playback, FLOAT feature copies and screens, in the pilot bundle format (Git-ignored) |
| `data/processed/c1_features_v2/corpus_features.parquet` | v2 features and eligibility metrics for all 131,072 sounds (Git-ignored) |

## 7. Rerunning with the real pilot

```powershell
.\venv\Scripts\python.exe -B -m c1_timbre.extract_corpus_features       # once; resumes if interrupted
.\venv\Scripts\python.exe -B -m c1_timbre.plan_main_study `
    --pilot-responses <real c1_pilot_responses.csv> --pilot-sessions <real c1_sessions.csv> `
    --version c1_main_v1
```

Then: review `decisions.json` with the supervisor, listen to every selected
sound, and freeze the bundle hash. Only after that, update the deployment.

## 7a. Demonstration website

[`build_main_website.py`](../build_main_website.py) packages any planner run into a
static site (template in [`website_template/`](website_template/)). It has two parts:

- **Participant view:** the full main-study flow: information and consent, setup,
  experience, volume, headphone screen, 3 practice sounds, 24 presentations with the
  break and hidden repeats, correction of the previous answer, pause, withdrawal and
  feedback.
- **Study design view:** the numbers above, plus a sound browser and a block viewer.

Answers stay in the visitor's browser and can be copied as CSV. The site is for
demonstration only; real collection uses the survey backend after approval.

```powershell
.\venv\Scripts\python.exe -B -m c1_timbre.build_main_website --version c1_main_v1_simpilot_dryrun
cd data\processed\c1_main_v1_simpilot_dryrun\website; ..\..\..\..\venv\Scripts\python.exe -m http.server 8765
# open http://localhost:8765
```

To switch to the real selection, run the planner with the real pilot export, then
rerun the build with the new `--version`.

**Hosting on Render (separate from the pilot).** Build with
`--publish-dir c1_timbre/main_study/site`, then commit and push that folder. In the
Render dashboard choose **New → Static Site**, select this repository and use these settings:

| Setting | Value |
|---|---|
| Name | `synth-listening-main` (gives `https://synth-listening-main.onrender.com`) |
| Branch | `c1-main` |
| Root directory | *(blank)* |
| Build command | *(blank)* |
| Publish directory | `c1_timbre/main_study/site` |

This creates a new service. The pilot (`synth-listening-pilot`, `render.yaml`,
branch `c1-pilot-deployment`) is untouched. Later rebuilds go live on the next push.

## 8. Deployment work outside C1 (for the survey preparer)

The bundle matches the pilot format. Hidden repeats use the existing
`kind="repeat"` / `repeat_of` fields. Before hosting, the survey code still needs these changes:

- `analysis_include` in `survey/backend/c1_pilot.py` currently requires
  `study_id == "c1_pilot_v1"`. It must recognize `c1_main_v1`, while still
  excluding review sessions.
- `survey/analyze_c1_pilot.py` assumes 64 sounds and 8 listeners per sound.
- The participant information text, time estimate and ethics documents need the
  27-presentation design.

## 9. Limitations

- The simulated pilot drives every number here. Timing, ICCs and predictor
  quality are assumptions, not measurements.
- Pilot features of 64 sounds support predicted scores only weakly; that is why
  part of the selection deliberately targets unsupported regions.
- Equal RMS does not mean equal loudness. Gains range from −14 to +19 dB; listen
  to the extremes before freezing.
- Control effects (changing one control at a time) are a separate validation
  study. They need new paired renders and are not part of this rating study.
