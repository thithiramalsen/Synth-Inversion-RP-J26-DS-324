# C3 v4 decision log

Each entry: what was decided, why, and whether the user has confirmed it.

## D-001 — Data paths and source (2026-10-14, Phase 0)

- Parameter reference: `reference/` (teammate's verified copy, all 7 hashes match).
- Audio corpus: `data/raw/corpus_v4/` (own generation, still running).
- `data.source: reference` until the Phase 5 audio gate passes.
- New v4 code lives beside the legacy `pipeline.py`, which is not modified.

Status: confirmed by user (use the friend's parquet files until the corpus is finished).

## D-002 — Unit-scale normalisation rule (2026-10-14, Phase 0)

Conflict with the build guide: `parameters_normalized.parquet` holds Vital normalized
values inside each control's `[min, max]` sub-range, not values on [0, 1].

Rule: `unit = (normalized − min) / (max − min)` using the config ranges, computed
from the `_normalized` columns (the values actually rendered). It agrees with the float64
Sobol design points `_sample_01` to ≤ 4.8e-7, which makes no practical difference to
distances. This rule works for both the reference source and the corpus chunks, which carry
the same `_normalized` column.

Distances are computed on these unit-scaled slider positions, not on the non-linear
physical units of the `_raw` columns (seconds, dB, semitones).

Status: confirmed by user 2026-10-14 (rule and slider-position distance space).

## D-003 — No grouping column (2026-10-14, Phase 0)

No family/anchor/perturbation structure exists; samples are independent Sobol points.
Splits will be random at sample level (`group_column: null`), with the exact-duplicate
guard from Phase 1 (0 duplicated rows found in Phase 0).

Status: confirmed by user 2026-10-14.

## D-004 — Sample count and split fractions (2026-10-14, Phase 0)

The dataset config's `sample_count: 1024` is a stale pilot field; the real count is
131,072 (tables, `reference_summary.json`, `corpus_verification.json`). Default fractions
are kept: 10% validation, 10% test, ~80% bank.

Status: confirmed by user 2026-10-14.

## D-005 — Making `src/c3` importable (2026-10-14, Phase 1)

`c3_recommendation/pyproject.toml` declares the `c3` package (`where = ["src"]`).
For scripts and `python -m c3.cli`, install once in editable mode:
`python -m pip install -e c3_recommendation`. The same file sets pytest's
`pythonpath = ["src"]`, so `python -m pytest c3_recommendation/tests_v4` works without
installing.

Status: chosen by Claude Code (guide lets the implementer pick); documented in RUNBOOK later.

## D-006 — Meaning of `.run.lock` (2026-10-14, Phase 5)

Conflict with the build guide (rule R2 / Phase 5 gate condition "`.run.lock` does not exist"):
`generation/generate_corpus.py:exclusive_run` never deletes `.run.lock`; it holds a 1-byte OS
lock on it (msvcrt / fcntl) only while writing. The file is permanent after the first run.

Rule used instead: generation counts as running only while that OS lock is held.
`c3.audio_io.generation_running()` probes the lock read-only (open `rb`, non-blocking lock,
immediate unlock; nothing is written). Completion additionally requires `summary.json`
count = 131,072 (gate check 2).

Status: confirmed by user 2026-10-14.

## D-007 — Phase order changed: audio gate before Phases 2–4 (2026-10-14)

The user's corpus finished before Phase 2. Phase 5 (audio gate) runs now; Phases 2–4 then run
with `data.source: corpus_v4`. Parameters are identical (gate check 5), so splits are the same
under either source.

Status: confirmed by user 2026-10-14.

## D-008 — Gate evidence and audio reading (2026-10-14, Phase 5)

- Primary equality proof is the team's own full comparison,
  `generation.generate_corpus --count 131072 --verify-reference reference/full_waveform_reference.json`,
  which re-verifies every row (Vital control values, raw file hashes, derived processed audio)
  and compares all raw + processed sample hashes. Its saved log is gate check 8.
- `c3.audio_io` re-implements DC-on-read independently from `recipe.json` (SOS coefficients,
  one pass, float64, then float32 with signed-zero subnormals) instead of importing
  `generation/`. Gate check 7 proves it bit-exact against the generator's
  `processed_samples_sha256` on 50 seeded random samples.
- External queries (`load_external_audio`): channel-mean downmix → `scipy.signal.resample_poly`
  to 44.1 kHz → trim or zero-pad at the end to 132,300 samples → the same DC policy. No peak or
  loudness normalisation (the corpus has none). librosa is not needed for this step.

Status: proposed by Claude Code; user agreed to the gate design 2026-10-14.

## D-009 — Data source switched to corpus_v4 (2026-10-14, Phase 5)

The audio gate passed all 8 checks (`outputs/v4/audio_gate/gate_report.json`), including the
official `--verify-reference` comparison (log line "PASS: every raw and processed waveform
matches the shared reference."). `data.source` is now `corpus_v4`: parameters come from
`data/raw/corpus_v4/manifest.parquet` (identical to the reference tables) and audio from the
raw masters with DC-on-read. `ReferenceSource` stays available for parameter-only work.

Status: confirmed by user 2026-10-14 (agreed to switch once the gate passes).

## D-010 — Frozen bank / val / test split (2026-10-14, Phase 2)

- Source `corpus_v4`, 131,072 samples, seed 20261014, sample-level random permutation
  (no grouping column, D-003). Counts: bank 104,858 / val 13,107 / test 13,107.
- Exact-duplicate guard (max-abs ≤ 1e-9 on the unit scale): 0 duplicate groups, 0 moves.
- SHA-256 of sorted IDs per split:
  - bank `55f9b68ef8c3cfe76d173e961130f175c9b7116717074c22edb9ed4a6ae86867`
  - val  `a4bab1020958aa12fb59a9e944198070881ac7e7db33fd40fe783c87d8b62af2`
  - test `fc6cee6de99ba5eb2fdd3f5dfb1251d2e1460a47a6c4a9bade7bee7586ea636b`
- Re-running `scripts/02_make_splits.py` reproduces these hashes; a differing split is refused
  without `--overwrite`.
- Balance (`outputs/v4/splits/split_balance.csv`): no parameter has a split-mean gap > 0.02.
  Largest gap is `filter_cutoff` 0.0125 (val 0.5077 vs test 0.4952), ~3.5 standard errors of a
  difference between two uniform samples of 13,107 — the largest of 39 comparisons, unusual but
  plausible by chance; std and 5–95% quantiles agree. The seed is **kept** (re-rolling for a
  nicer-looking split would be seed-shopping).

Status: confirmed by user 2026-10-14.

## D-011 — Parameter-space structure and proposed epsilon grid (2026-10-14, Phase 3)

Measured on 2,000 seeded bank samples against the 104,858-sample bank
(`euclid_sqrt_d`, unit scale; `outputs/v4/analysis/param_structure.json`):

| Distribution | min | p1 | p5 | p25 | median | p95 |
|---|---|---|---|---|---|---|
| 1-NN | 0.0813 | 0.0970 | 0.1074 | 0.1203 | 0.1286 | 0.1502 |
| 5-NN | — | 0.1285 | 0.1332 | 0.1415 | 0.1489 | 0.1694 |
| random pair | 0.2038 | 0.2476 | 0.2878 | 0.3581 | 0.4034 | 0.5140 |

Observations:
- The Sobol bank has **no natural near-duplicates**: no sampled point has a neighbour closer
  than 0.081, and 1-NN distances are tightly concentrated (std 0.013). Random pairs are
  ~3× further apart than nearest neighbours.
- Leave-one-parameter-out: dropping any single control lowers the median 1-NN distance by a
  similar amount (−0.0077 amp_attack … −0.0123 filter_env_amount). No control dominates the
  distance under equal weighting.

Proposed grid written to `near_duplicate.epsilon_grid`:
`[0.05, 0.097, 0.1, 0.1074, 0.1121, 0.1203, 0.15]`

| ε | Source | share of 1-NN below |
|---|---|---|
| 0.05 | round value — "practically identical recipe"; below every observed 1-NN distance | 0.000 |
| 0.097 | p1 of 1-NN | 0.011 |
| 0.1 | round value | 0.014 |
| 0.1074 | p5 of 1-NN | 0.051 |
| 0.1121 | p10 of 1-NN | 0.100 |
| 0.1203 | p25 of 1-NN | 0.252 |
| 0.15 | round value — roughly the 5-NN median | 0.949 |

Interpretation: a pair with distance < ε is "as close as (or closer than) the closest patches
the bank offers". Because the percentile values are crowded between 0.097 and 0.12,
conclusions are expected to be similar among them; 0.05 and 0.15 bracket the range. The primary
ε is **not** chosen here: it is finalised on validation data in Phase 7 with a sensitivity
table, using a rule written before looking at test data.

Status: confirmed by user 2026-10-14.

## D-012 — Evaluation pipeline design and smoke test (2026-10-14, Phase 4)

Implementation choices in `evaluate.py` / `stats.py` that later phases reuse:

- The bank is scored once per target (`RelevanceFunction.score_bank`); the largest pool is built
  once and smaller pools are its prefixes (same total ranking), so all N share one ranking.
- One pairwise parameter-distance matrix per pool is reused by top-k, every MMR lambda, the
  random baseline and the metrics (`PoolArrays`, `mmr_indices`, `metrics_from_indices`).
- Random-from-pool: 200 draws per (target, N, k) with RNG seed `[seed, target sample position, N, k]`;
  `per_target` stores the mean over draws. Individual random draws are not written to
  `recommendations.parquet` (top-k and MMR sets are).
- `rel_loss_vs_topk` = (top-k mean_rel − policy mean_rel) / top-k mean_rel, per target;
  `delta_*_pair_dist_vs_topk` = policy − top-k. Summary CIs: percentile bootstrap of the mean,
  10,000 resamples, seeded, targets ordered by ID within each group.
- Label: tables carry `relevance_function = SMOKE_TEST_PROXY` (the column `relevance` already holds
  scores in `recommendations`); `run_config.json` carries `"relevance": "SMOKE_TEST_PROXY"`.

Smoke test (`scripts/04_smoke_test.py`, 200 val targets, N ∈ {50, 100}, k ∈ {5, 3}, 11 lambdas):
λ = 1 equals top-k for every set (0 mismatches); 0 self-matches; 0 candidates outside the bank;
in-process re-run identical; a second process run produced byte-identical artefacts.
≈148 ms per target, ≈75 s total. **Proxy numbers are a pipeline check only and are never reported.**

Status: implementation choices by Claude Code; smoke test result recorded 2026-10-14.

## D-013 — Audio features and representation diagnostic (2026-10-14, Phase 6)

Features (`c3.features`, cache in `outputs/v4/features/`, one streaming pass, 13.6 min, 8 workers):
- `mfcc26`: the legacy pilot_v1 MFCC exactly (n_fft 2048, hop 512, symmetric Hann, reflect pad,
  40 HTK-mel bands 20 Hz–20 kHz, natural log, orthonormal DCT-II, 13 MFCCs, mean + std). Equality
  with `pipeline.py:extract_mfcc_summary` is tested (max difference 0.0). librosa is not used.
- `logmel_stats`: same power spectrum, 64 HTK-mel bands, natural log, mean + std (128 dims).
- CLAP: not computed now (user agreed to decide after MFCC/log-mel).
- Relevance: z-score with bank mean/std only, L2-normalise, cosine (`FeatureCosineRelevance`).

Sanity (500 val targets; 200 for self-relevance): self-relevance = 1 within 4.4e-16; 20 cached
rows recomputed from audio match exactly; no zero-variance dimensions.

Representation diagnostic (val targets; parameter distance from target to audio top-k):

| | mfcc26 | logmel_stats |
|---|---|---|
| top-1 param distance, mean [95% CI] | 0.3083 [0.3024, 0.3141] | 0.3059 [0.2998, 0.3118] |
| top-5 mean param distance | 0.3130 [0.3094, 0.3165] | 0.3123 [0.3087, 0.3158] |
| top-5 min param distance | 0.2380 [0.2335, 0.2425] | 0.2381 [0.2336, 0.2426] |
| relevance at rank 1 / 5 / 50 / 100 (median) | 0.986 / 0.974 / 0.945 / 0.930 | 0.992 / 0.987 / 0.972 / 0.966 |

References: random bank patch 0.401; true parameter 1-NN median 0.129 (Phase 3).

Observations (diagnostic, not hypothesis results):
- The two representations are practically indistinguishable on this diagnostic (overlapping CIs).
- Audio-nearest patches sit far from the target in parameter space (≈0.31, between the parameter
  1-NN 0.13 and a random patch 0.40): consistent with the many-to-one premise of C3.
- Scale mismatch (guide §8.3) is confirmed: within a 100-candidate pool relevance spans only
  ≈0.06 (mfcc26) / ≈0.03 (logmel) at the median, while parameter similarity spans ≈0–1. With
  `relevance_scaling: none`, even λ ≈ 0.9 may let the diversity term dominate. Whether to add
  λ values between 0.95 and 1.0 to the grid is an open question for the user before Phase 7.

Status: features and checks recorded; primary representation and λ grid are the user's decisions.

## D-014 — Offline demo viewer for Progress Presentation 1 (2026-10-22)

`scripts/demo_build_viewer.py` builds two offline pages in `outputs/v4/demo/` (git-ignored):
`demo_mfcc26.html` and `demo_logmel_stats.html`. Both show the same 8 seeded validation targets,
a 100-candidate audio shortlist, plain top 5 and MMR picks side by side with playable audio
(16-bit PCM copies of the processed corpus audio, 174 clips, 46 MB) and knob-setting bars.

- Selections come from the tested `pool_from_scores`, `mmr_indices` and `metrics_from_indices`
  (`c3.demo.build_demo_data`); λ = 1 is asserted to equal the plain top 5.
- The demo λ list `1.0, 0.99, 0.98, 0.97, 0.96, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.6, 0.5` is for
  illustration only. It does not set the Phase 7 grid, and the demo numbers (8 targets) are not
  results. Every page is labelled "Illustration · validation sounds · λ not tuned yet".

Status: built at the user's request for the presentation.

## D-015 — C3 human study (H3) design, rehearsal bundle v1 (2026-10-22)

User decisions (2026-10-22): blinded A/B set comparison; participants see knob bars and hear
audio; validation targets now with a provisional operating point, rebuilt after Phase 7;
standalone local rehearsal first (`c3_recommendation/human_study/`, like the C2 study), to be
integrated into the shared survey service later.

Design (`human_study/design.py`, version `c3-human-v1`, seed 20261022):
- Each case: a target sound and two sets of k = 5 (plain top 5 and C3/MMR) from the same
  100-sound shortlist. Participants rate how close each distinct sound is (1–5 or Cannot judge),
  then answer three A/B/No difference/Cannot judge questions: more useful, different starting
  points; closer overall; more different by ear. Plus confidence and an optional reason.
- The target's own knob settings are never shown (unknown in real use).
- Sounds are numbered by a fixed per-case shuffle and each set is listed in number order, so
  rank order cannot reveal the method. A sound in both sets keeps one number and one rating.
- 8 scored cases + 1 practice; 12 completions planned, 16 enrolments maximum. Complementary
  slot pairs: every participant sees C3 as Set A in 4 of 8 cases; each case shows C3 as A in
  6 of 12 completions; case order rotates between pairs.
- Stimuli: seeded sample of 40 validation targets screened in order; skip only identical sets
  or technical audio failure (non-finite, clipped, below −60 dBFS). Bundle v1: 1 skipped
  (identical sets), 8 scored + practice built. Test split untouched.
- **Provisional** operating point: mfcc26, N = 100, k = 5, λ = 0.8, relevance scaling none.
  It must be replaced by the Phase 7 preregistered values in a new bundle version before any
  real participant. Bundle v1 is for rehearsal only.

Status: design confirmed by the user; provisional values chosen by Claude Code.

## D-016 — Evaluation decisions fixed before Phase 7 (2026-10-22)

Made by the user before any tuning result was computed:

- **H2 tolerance τ = 0.02**: the largest accepted relative loss in mean relevance of the C3 set
  versus the plain top-k (per target, upper 95% bootstrap CI). Stored as `tuning.tau`.
- **Primary representation: `mfcc26`** (identical to the pilot_v1 MFCC). `logmel_stats` and
  `clap` are secondary sensitivity checks, reported but not used for the hypothesis decision.
- **λ grid extended** with 0.99, 0.98, 0.97, 0.96 because relevance spans a narrow band (D-013).
  Grid: 1.00, 0.99, 0.98, 0.97, 0.96, 0.95, 0.90, 0.85, 0.80, 0.75, 0.70, 0.65, 0.60, 0.50, 0.40.
- **CLAP features added**: `laion/clap-htsat-unfused` through the Hugging Face Transformers CLAP
  API, revision `8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a`, 48 kHz input — the same checkpoint and
  revision C4 uses, so C3 and C4 CLAP results are comparable.
- Primary k = 5 (k = 3 is a sensitivity check).

Status: confirmed by user 2026-10-22.

## D-017 — Phase 7 selection rules, written before running tuning (2026-10-22)

Implemented in `c3.tuning`; logged before `scripts/07_tune.py` was first run.

1. **Targets:** `splits.n_val_targets_eval` = 500 validation targets (seeded); the test split is
   not read. Primary representation mfcc26; k = 5 primary, k = 3 sensitivity.
2. **λ and N rule:** among MMR configurations for k = 5, (N, λ) is eligible when the upper
   bound of the 95% bootstrap CI (10,000 resamples, seeded) of the per-target relative relevance
   loss versus top-k is ≤ τ = 0.02. Choose the eligible configuration with the highest mean
   pairwise parameter distance; ties → smaller N, then larger λ. If only λ = 1 is eligible, the
   outcome is reported as "no diversity gain within tolerance" (a valid negative result).
3. **ε rule:** at the chosen (N*, λ*, k = 5), the primary near-duplicate threshold ε* is the
   smallest grid value at which at least 10% of validation targets have a near-duplicate pair in
   their plain top-k set. This depends on top-k only, never on the MMR effect. If no ε
   qualifies, the largest grid value is used and dup_rate is flagged as uninformative for H1.
   The full ε sensitivity table is reported either way.
4. Secondary representations (logmel_stats, clap) are tuned with the same rules and reported as
   sensitivity analyses only.

Status: rules proposed by Claude Code, consistent with the build guide §7 and the user's
D-016 decisions; recorded before results.

## D-018 — Phase 7 validation tuning result (2026-10-22)

`scripts/07_tune.py`, 500 validation targets, rules D-017, outputs `outputs/v4/val/<rep>/`.
λ = 1 equalled top-k in every set. Re-running reproduced identical numbers.

Primary (mfcc26), k = 5 — top-k vs chosen MMR, means over targets:

| | mean relevance | rel. loss vs top-k (95% CI upper) | mean pair dist | min pair dist |
|---|---|---|---|---|
| top-k (N = 100) | 0.9725 | — | 0.3250 | 0.2258 |
| **MMR, N* = 100, λ* = 0.5** | 0.9550 | 1.81% (1.90%) | **0.4161** | **0.3619** |
| random from shortlist (N = 100) | 0.9360 | 3.80% (4.00%) | 0.3395 | 0.2382 |

- Outcome: **diversity gain within tolerance** (τ = 0.02). k = 3 gives the same point (N 100, λ 0.5).
- For N = 50 the best eligible λ is 0.4, the lowest grid value; N = 100, λ = 0.5 still has the
  higher diversity, so the grid edge does not change the choice.
- **ε* = 0.15, flagged uninformative:** top-k sets contained a near-duplicate pair for at most
  4.8% of targets (ε = 0.15) and 0% for ε ≤ 0.1121. On this evenly spread Sobol bank, the C3
  benefit shows as larger pairwise spread, not as removal of near-copies. Following D-017 rule 3,
  the preregistration template makes H1 a two-metric family (mean and minimum pairwise distance)
  and reports dup_rate descriptively.
- Secondary (logmel_stats): N = 100, λ = 0.4, loss 1.38% (CI upper 1.48%), mean pair dist 0.422.
  λ = 0.4 is the grid edge, so log-mel's optimum may lie lower; reported as a limitation.
- `docs/PREREGISTRATION_TEMPLATE.md` generated from the primary run. PREREGISTRATION.md is written
  and committed by the user.

Status: computed; awaiting the user's preregistration.

## D-019 — Human study rebuilt as version 2 with the Phase 7 operating point (2026-10-22)

At the user's request the study was rebuilt before the CLAP work:
- `human_study/design.py`: `VERSION = "c3-human-v2"`; `OPERATING_POINT` = mfcc26, N = 100, k = 5,
  λ = 0.5 (D-018), replacing the provisional λ = 0.8 of version 1.
- New bundle `data/processed/c3_v4/human_study_bundle_v2/` and database
  `human_study_rehearsal_v2/`. Version 1 bundle and database are kept on disk unchanged.
- Same seeded validation screening (seed 20261022): v2 skipped no target (every target's sets
  differ at λ = 0.5), so v2 uses screened ranks 0–8. 6–9 distinct sounds per case (8 on average,
  v1: 6.6); the participant time estimate was raised to 30–35 minutes.
- The values must match PREREGISTRATION.md; if the preregistration changes them, build a new
  study version.

Status: built at the user's request.

## D-020 — Human study perceptual closeness analysis plan, frozen before any response (2026-10-22)

User decisions: build the perceptual closeness evaluation; equivalence margin 0.5 rating points;
keep the headphone check. Implemented in `human_study/analysis.py`, run with
`manage analyze`. No real or rehearsal responses existed when this plan was written.

- **Primary outcome:** for each participant, the mean closeness rating (1–5; Cannot judge
  excluded) of sounds only in the C3 set minus sounds only in the top-k set. Across participants:
  mean, median and 95% percentile bootstrap CI (10,000 draws, seed 20261022). **C3's picks are
  "heard as close as the top-k" if the CI lower bound is above −0.5.** Otherwise "not shown to be
  within the margin"; with fewer than 2 eligible participants, "insufficient data". An exploratory
  Wilcoxon signed-rank test against 0 is reported (n ≥ 6).
- **Secondary (descriptive):** mean rating and share rated 4–5 for top-k-only, C3-only and
  shared sounds (are the suggestions close at all?); within-participant Spearman correlation of
  model relevance and of shortlist rank with ratings; participant-level C3 share of decisive
  answers for the three set questions (0.5 = no preference); per-case tables.
- Unit of analysis: the participant. Outputs: REPORT.md, analysis.json, CSV tables, two figures.
- Only simulated or rehearsal data can be analysed while research collection is disabled.
- The simulator (`simulate_sessions`) assumes ratings track MFCC relevance steeply; its output
  is a software check, never a prediction or result.

Status: confirmed by the user (margin, scope); plan details by Claude Code.
