"""Phase 5 - audio gate: is corpus_v4 complete and identical to the reference?

Read-only. Every condition must pass before ``data.source`` may switch to ``corpus_v4``:

 1. no generator holds the OS lock on ``.run.lock`` (the file itself is permanent);
 2. ``summary.json`` count == reference row count, no silent/clipped/DC-flagged rows;
 3. the corpus recipe's synthesis settings equal the reference dataset config;
 4. manifest IDs == reference IDs (same order) and exactly one raw WAV per ID, no extras;
 5. manifest parameter columns equal ``parameters_full.parquet`` within 1e-9;
 6. manifest raw/processed sample hashes equal ``full_waveform_reference.json``;
 7. C3's own reader reproduces raw + processed hashes bit-exactly on N random samples
    and the audio is finite, full length, non-silent, unclipped;
 8. the official full comparison (``generation.generate_corpus --verify-reference``) passed,
    proven by its saved log.

Usage (repo root):
    python c3_recommendation/scripts/05_audio_gate.py [--n-samples 50] [--official-log PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from c3.audio_io import CorpusAudioReader, generation_running, sample_digest  # noqa: E402
from c3.config import load_config  # noqa: E402

PARAM_SUFFIXES = ("sample_01", "normalized", "raw")
PARAM_TOLERANCE = 1e-9
OFFICIAL_PASS_LINE = "PASS: every raw and processed waveform matches the shared reference."
# Fields that legitimately differ between the pilot-era reference config and the corpus recipe.
RECIPE_IGNORED_KEYS = {"sample_count", "created_utc"}


def read_log(path: Path) -> str:
    """Read a log written by PowerShell (often UTF-16 with BOM) or by a UTF-8 shell."""
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    return data.decode("utf-8-sig", errors="replace")


def check(report: dict, name: str, passed: bool, **details) -> None:
    report["checks"][name] = {"passed": bool(passed), **details}
    print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f"  {details.get('summary', '')}" if details else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None)
    parser.add_argument("--n-samples", type=int, default=50, help="random samples to re-read and hash")
    parser.add_argument("--official-log", type=Path, default=None,
                        help="saved output of generation.generate_corpus --verify-reference")
    args = parser.parse_args()

    cfg = load_config(args.config)
    corpus_dir, reference_dir = cfg.path("corpus_dir"), cfg.path("reference_dir")
    out_dir = cfg.path("outputs_dir") / "audio_gate"
    out_dir.mkdir(parents=True, exist_ok=True)
    official_log = args.official_log or out_dir / "official_verify_reference.log"
    names = cfg.parameter_columns
    report: dict = {"generated_utc": datetime.now(timezone.utc).isoformat(),
                    "corpus_dir": str(corpus_dir), "reference_dir": str(reference_dir), "checks": {}}

    # 1. generator lock -----------------------------------------------------------------
    running = generation_running(corpus_dir)
    check(report, "1_generator_not_running", not running,
          summary="OS lock on .run.lock is free" if not running else "a generator holds the lock")
    if running:
        raise SystemExit("Generation is still running; stopping without reading corpus data.")

    # 2. completion summary --------------------------------------------------------------
    reference = pd.read_parquet(reference_dir / "parameters_full.parquet")
    summary = json.loads((corpus_dir / "summary.json").read_text(encoding="utf-8"))
    flags = {k: summary.get(k) for k in ("is_silent", "is_clipped", "has_large_dc_offset")}
    check(report, "2_completion_summary",
          summary.get("count") == len(reference) and all(v == 0 for v in flags.values()),
          summary=f"count={summary.get('count')} expected={len(reference)} flags={flags}", corpus_summary=summary)

    # 3. recipe equals the reference dataset config -----------------------------------------
    recipe = json.loads((corpus_dir / "recipe.json").read_text(encoding="utf-8"))
    dataset_config = json.loads(cfg.path("dataset_config_json").read_text(encoding="utf-8"))
    differing = sorted(
        key for key in (set(recipe["synthesis"]) | set(dataset_config)) - RECIPE_IGNORED_KEYS
        if recipe["synthesis"].get(key) != dataset_config.get(key)
    )
    check(report, "3_recipe_matches_dataset_config", not differing,
          summary=f"differing keys: {differing or 'none'}", differing_keys=differing,
          ignored_keys=sorted(RECIPE_IGNORED_KEYS))

    # 4. IDs and one WAV per ID ---------------------------------------------------------------
    manifest = pd.read_parquet(corpus_dir / "manifest.parquet")
    same_ids = manifest["sample_id"].tolist() == reference["sample_id"].tolist()
    same_index = np.array_equal(manifest["sample_index"].to_numpy(), reference["sample_index"].to_numpy())
    with os.scandir(corpus_dir / "raw_float") as entries:
        files = {e.name for e in entries if e.is_file()}
    expected_files = {f"{sid}.wav" for sid in manifest["sample_id"]}
    tmp_files = sorted(f for f in files if f.endswith(".tmp"))
    missing = sorted(expected_files - files)
    extra = sorted(files - expected_files - set(tmp_files))
    expected_paths = "data/raw/corpus_v4/raw_float/" + manifest["sample_id"] + ".wav"
    paths_ok = bool((manifest["raw_audio_path"] == expected_paths).all())
    check(report, "4_ids_and_audio_files",
          same_ids and same_index and not missing and not extra and paths_ok and not manifest["sample_id"].duplicated().any(),
          summary=f"ids_equal={same_ids} wavs={len(files & expected_files)}/{len(expected_files)} "
                  f"missing={len(missing)} extra={len(extra)} tmp={len(tmp_files)} manifest_paths_ok={paths_ok}",
          missing_first=missing[:20], extra_first=extra[:20], tmp_files=tmp_files[:20])

    # 5. parameters ----------------------------------------------------------------------------
    diffs, display_mismatch = {}, {}
    if same_ids:
        for name in names:
            for suffix in PARAM_SUFFIXES:
                col = f"{name}_{suffix}"
                diffs[col] = float(np.abs(manifest[col].to_numpy() - reference[col].to_numpy()).max())
            col = f"{name}_display"
            display_mismatch[col] = int((manifest[col].astype(str) != reference[col].astype(str)).sum())
    worst = max(diffs.values()) if diffs else float("nan")
    check(report, "5_parameters_match_reference",
          bool(diffs) and worst <= PARAM_TOLERANCE and not any(display_mismatch.values()),
          summary=f"max |diff| over {len(diffs)} columns = {worst:.3e} (tol {PARAM_TOLERANCE:g}); "
                  f"display mismatches={sum(display_mismatch.values())}",
          max_abs_diff_per_column=diffs, display_mismatches=display_mismatch)

    # 6. waveform hashes recorded in manifest vs reference ----------------------------------------
    waveform_ref = json.loads((reference_dir / "full_waveform_reference.json").read_text(encoding="utf-8"))
    recorded = dict(zip(manifest["sample_id"],
                        zip(manifest["raw_samples_sha256"], manifest["processed_samples_sha256"])))
    raw_bad = [s for s, (r, _) in recorded.items() if waveform_ref.get(s, [None, None])[0] != r]
    proc_bad = [s for s, (_, p) in recorded.items() if waveform_ref.get(s, [None, None])[1] != p]
    check(report, "6_manifest_hashes_match_reference",
          not raw_bad and not proc_bad and set(waveform_ref) == set(recorded),
          summary=f"raw mismatches={len(raw_bad)} processed mismatches={len(proc_bad)} "
                  f"reference ids={len(waveform_ref)}",
          raw_mismatch_first=raw_bad[:20], processed_mismatch_first=proc_bad[:20])

    # 7. C3 reader re-reads random samples ------------------------------------------------------
    reader = CorpusAudioReader(corpus_dir)
    rng = np.random.default_rng(cfg.seed)
    picks = sorted(rng.choice(len(manifest), size=min(args.n_samples, len(manifest)), replace=False))
    silence_db = float(dataset_config.get("silence_threshold_dbfs", -60.0))
    clip_level = float(dataset_config.get("clipping_threshold", 1.0))
    rows, problems = [], []
    for i in picks:
        row = manifest.iloc[i]
        raw = reader.read_raw(row["sample_id"])
        processed, sr = reader.load(row["sample_id"])
        peak = float(np.abs(processed).max())
        rms = float(np.sqrt(np.mean(processed.astype(np.float64) ** 2)))
        entry = {
            "sample_id": row["sample_id"],
            "raw_hash_ok": sample_digest(raw) == row["raw_samples_sha256"],
            "processed_hash_ok": sample_digest(processed) == row["processed_samples_sha256"],
            "length_ok": len(processed) == reader.policy.n_samples and sr == reader.policy.sample_rate,
            "finite": bool(np.isfinite(processed).all()),
            "peak": peak,
            "rms_dbfs": 20 * np.log10(max(rms, 1e-15)),
            "silent": 20 * np.log10(max(rms, 1e-15)) < silence_db or not np.any(processed),
            "clipped": peak >= clip_level,
        }
        rows.append(entry)
        if not (entry["raw_hash_ok"] and entry["processed_hash_ok"] and entry["length_ok"] and entry["finite"]) \
                or entry["silent"] or entry["clipped"]:
            problems.append(entry)
    peaks = [r["peak"] for r in rows]
    check(report, "7_c3_reader_reproduces_audio", not problems,
          summary=f"{len(rows) - len(problems)}/{len(rows)} samples bit-exact and sane; "
                  f"peak range [{min(peaks):.4f}, {max(peaks):.4f}]",
          samples=rows, problems=problems)

    # 8. official full comparison -----------------------------------------------------------------
    official_ok, official_note = False, f"log not found: {official_log}"
    if official_log.exists():
        text = read_log(official_log)
        official_ok = OFFICIAL_PASS_LINE in text
        official_note = "PASS line found" if official_ok else "PASS line not found in log"
    check(report, "8_official_full_comparison", official_ok, summary=official_note, log=str(official_log))

    report["gate_passed"] = all(c["passed"] for c in report["checks"].values())
    report["manifest_quality_flags"] = {
        col: int(manifest[col].sum()) for col in ("is_silent", "is_clipped", "has_large_dc_offset",
                                                  "raw_clipped", "raw_silent", "raw_dc_warning")
    }
    report["audio_policy"] = reader.policy.describe()
    out = out_dir / "gate_report.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nGATE {'PASSED' if report['gate_passed'] else 'NOT PASSED'} - report: {out}")
    print("Manifest quality flags:", report["manifest_quality_flags"])


if __name__ == "__main__":
    main()
