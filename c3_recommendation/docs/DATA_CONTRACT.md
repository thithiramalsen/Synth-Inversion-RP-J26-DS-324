# C3 v4 data contract

All facts below were read from the files by `scripts/00_inspect_data.py` on 2026-10-14
(full output: `outputs/v4/phase0_inspection.json`). Later code reads these values from
`configs/c3_v4.yaml` and the dataset config JSON, not from this document.

## 1. File locations (read-only)

| Item | Path (repo-relative) | Notes |
|---|---|---|
| Parameter reference folder | `reference/` | Teammate's verified copy, git-ignored |
| Dataset config | `reference/restricted_bend_sustain_v4_config.json` | Schema, ranges, fixed controls, audio policy |
| Full parameter table | `reference/parameters_full.parquet` | 131,072 × 54 |
| Normalized parameter table | `reference/parameters_normalized.parquet` | 131,072 × 15 |
| Audio corpus | `data/raw/corpus_v4/` | Complete 2026-10-14; own generation, git-ignored (section 5) |

The SHA-256 of all 7 hashed reference files matches `clone_integrity.json` /
`corpus_verification.json`.

## 2. Sample IDs

- `sample_id` = `restricted_bend_sustain_v4_<n>`, where `<n>` is zero-padded to **5 digits
  and grows to 6 digits from 100000**. String sorting is therefore **not** numeric order —
  always order by `sample_index`.
- `sample_index` = integer `0 … 131071`, equal to the numeric suffix, tables sorted by it.
- 131,072 = 2^17 samples, no duplicated IDs, no duplicated parameter rows.
- Both parquet files have identical row order, IDs and `sample_index`.

## 3. Parameters (13 controls, all continuous)

Sampling: scrambled Sobol sequence, seed 20260803. All controls use Vital's normalized
slider value (`mode: normalized`) restricted to the `[min, max]` interval below.

| # | Name | Vital control | min | max | Unit of `_raw` / display |
|---|---|---|---|---|---|
| 1 | wave_frame | osc_1_wave_frame | 0.0 | 1.0 | wavetable frame index (0–256) |
| 2 | bend_amount | osc_1_distortion_amount | 0.25 | 0.75 | % (raw = normalized) |
| 3 | filter_cutoff | filter_1_cutoff | 0.3 | 0.85 | semitones |
| 4 | filter_resonance | filter_1_resonance | 0.0 | 0.8 | % (raw = normalized) |
| 5 | filter_drive | filter_1_drive | 0.0 | 0.75 | dB |
| 6 | amp_attack | env_1_attack | 0.05 | 0.35 | seconds (non-linear) |
| 7 | amp_decay | env_1_decay | 0.15 | 0.4 | seconds (non-linear) |
| 8 | amp_sustain | env_1_sustain | 0.2 | 1.0 | level (raw = normalized) |
| 9 | amp_release | env_1_release | 0.1 | 0.45 | seconds (non-linear) |
| 10 | filter_env_amount | modulation_1_amount | 0.5 | 0.5625 | mod depth (raw 0–0.125) |
| 11 | filter_env_attack | env_2_attack | 0.05 | 0.35 | seconds (non-linear) |
| 12 | filter_env_decay | env_2_decay | 0.15 | 0.4 | seconds (non-linear) |
| 13 | filter_env_sustain | env_2_sustain | 0.0 | 1.0 | level (raw = normalized) |

One modulation is fixed: `env_2 → filter_1_cutoff` (slot 1). 51 other controls are fixed
(listed in the dataset config under `fixed_controls`). No duplicated oscillators or
interchangeable blocks (osc 2/3 off), so no permutation symmetry (guide §8.7).

### Column layout

`parameters_full.parquet`: `sample_id`, `sample_index`, then for each parameter in schema
order four columns:

| Suffix | Meaning | Verified |
|---|---|---|
| `_sample_01` | Sobol design point in [0, 1] (float64) | min ≈ 0, max ≈ 1 |
| `_normalized` | Vital normalized value actually sent to the synth, `min + sample_01·(max−min)`, stored as float32-exact values | within `[min, max]` for all 13 |
| `_raw` | Vital internal value (identity for 4 controls, monotonic non-linear for 9) | monotonic in `_normalized` for all 13 |
| `_display` | Human-readable string (e.g. `"0.0133 secs"`) | text only |

`parameters_normalized.parquet`: `sample_id`, `sample_index`, `<name>_normalized` × 13.
These values are bit-identical to the `_normalized` columns of the full table.

### Normalisation rule — differs from the build guide's assumption

The guide assumed `parameters_normalized.parquet` is already on a [0, 1] unit scale. **It is
not**: it holds Vital normalized values inside each control's sub-range (e.g.
`filter_env_amount` ∈ [0.5, 0.5625]). The unit scale used by C3 is:

```
unit = (normalized − min) / (max − min)
```

This matches `_sample_01` with max absolute error ≤ 4.8e-7 per column (the error comes
from float32 rounding of the rendered value; largest for the narrow `filter_env_amount`
range). See DECISIONS D-002 for which of the two is used.

### Leakage-relevant structure

No `group`, `family`, `anchor`, `parent`, `sibling`, `perturbation`, `sobol_index` or
`chunk_id` columns. Samples are independent Sobol points → `group_column: null`.

## 4. Fixed rendering conditions

| Field | Value |
|---|---|
| Sample rate | 44,100 Hz |
| Channels | 1 (mono) |
| MIDI note / velocity | 60 / 0.8 |
| Note duration / render duration | 1.5 s / 3.0 s (132,300 samples) |
| Stored audio | 32-bit FLOAT WAV, raw (unconditioned) render |
| Audio policy | `dc_highpass_10hz_v1`: 2nd-order Butterworth high-pass, 10 Hz, `scipy.signal.sosfilt`, float64, zero initial state per clip, applied once, no normalisation, no fade, gain 1.0 |
| Storage policy | `raw_float_dc_on_read_v1` — the DC-conditioned audio is **derived on read** by applying the policy filter to the raw file |
| Processed float32 policy | `float32_subnormal_signed_zero_v1` (definition in `generation/corpus_audio.py`, to be read in Phase 5) |
| Sample hash format | SHA-256 of mono 44.1 kHz, 132,300 little-endian float32 samples |
| QA flags (reference) | 0 silent, 0 clipped, 0 large DC offset over 131,072 rows |

The corpus is **not** peak-normalised (normalization: none).

## 5. Corpus layout — verified by the Phase 5 gate (2026-10-14)

Generation finished 2026-10-14 15:07 (`summary.json`: 131,072 rendered, 0 silent, 0 clipped,
0 large DC offset). Files in `data/raw/corpus_v4/`:

| File | Content |
|---|---|
| `.run.lock` | Permanent 1-byte file. The generator holds an OS lock on it only while running (D-006). |
| `recipe.json` | Synthesis settings (identical to the dataset config except `sample_count`/`created_utc`), `storage_policy: raw_float_dc_on_read_v1`, `processed_float32_policy: float32_subnormal_signed_zero_v1`, `sample_hash_format`. |
| `summary.json` | Completion count and QA flag totals. |
| `manifest.parquet` / `.csv` | 131,072 × 85. Same `sample_id`/`sample_index` order as the reference; all 52 parameter columns (`_sample_01`, `_normalized`, `_raw`, `_display`) identical to `parameters_full.parquet` (max diff 0.0). Plus rendering conditions, QA metrics for processed and raw audio, `raw_samples_sha256`, `processed_samples_sha256`, `raw_audio_path`, `raw_audio_sha256`. |
| `raw_float/<sample_id>.wav` | One raw 32-bit FLOAT mono 44.1 kHz WAV, 132,300 frames, per sample. Exactly 131,072 files. |
| `chunks/<start_index:06d>.json` | 1,024 checkpoint chunks of 128 rows (authoritative during generation; the manifest is rebuilt from them at completion). |

Reading audio (implemented in `c3.audio_io`): raw WAV → `dc_highpass_10hz_v1` SOS filter once
in float64 → float32 with subnormals zeroed keeping sign. This reproduces the generator's
`processed_samples_sha256` bit-exactly (gate check 7).

`reference/full_waveform_reference.json` maps each ID to
`[raw_samples_sha256, processed_samples_sha256]` (order confirmed in
`generation/generate_corpus.py:reference`). The manifest's hashes equal it for all 131,072 IDs.

QA note: 61,789 raw masters carry `raw_dc_warning`; this is the DC offset the 10 Hz policy
removes. After processing, 0 rows have `has_large_dc_offset`.

## 6. Questions

Resolved 2026-10-14 (see DECISIONS.md):

1. Unit scale = `(normalized − min)/(max − min)` from the rendered values (D-002).
2. Distance is computed on slider positions, not physical units (D-002).
3. `sample_count: 1024` in the dataset config is stale; the real count is 131,072, split
   ~104,858 bank / 13,107 val / 13,107 test (D-004).
4. Hash order in `full_waveform_reference.json` is `[raw, processed]` (section 5).

No open questions.
