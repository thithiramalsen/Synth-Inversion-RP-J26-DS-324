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
