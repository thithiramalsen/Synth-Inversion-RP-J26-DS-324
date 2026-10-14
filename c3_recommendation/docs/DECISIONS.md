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
