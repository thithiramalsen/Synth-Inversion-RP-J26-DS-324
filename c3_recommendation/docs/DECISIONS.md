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
