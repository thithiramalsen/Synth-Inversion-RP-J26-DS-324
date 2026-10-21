"""Parallel read-only verification of a completed v4 corpus; never render.

Optionally export a separate teammate handoff with parameter tables and waveform
references. The frozen generator, corpus audio, checkpoints and manifests are
never modified by this tool.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import time

import numpy as np
import pandas as pd
from generation import generate_corpus as runner
from generation.corpus_audio import load_audio, raw_path

_CONTROLS = None
_SAMPLES = None
_SYNTH = None


def initialize(count):
    global _CONTROLS, _SAMPLES, _SYNTH
    g = runner.generator()
    _SAMPLES = g.create_sobol_samples(count, len(g.PARAMS), g.SAMPLING_SEED)
    _SYNTH = g.create_synth()
    if not _SYNTH.load_preset(str(g.BASE_PRESET)):
        raise ValueError("Cannot load frozen validation preset")
    _CONTROLS = _SYNTH.get_controls()


def verify_chunk(rows):
    g = runner.generator()
    for row in rows:
        index = row["sample_index"]
        if row["sample_id"] != f"{runner.PROFILE}_{index:05d}":
            raise ValueError("Unexpected sample identity")
        path = raw_path(row, runner.ROOT)
        allowed = (g.PILOT_AUDIO_DIR / "raw_float" / f"{row['sample_id']}.wav",
                   runner.OUTPUT / "raw_float" / f"{row['sample_id']}.wav")
        if path not in tuple(p.resolve() for p in allowed):
            raise ValueError("Unexpected master path")
        if runner.sha(path) != row["raw_audio_sha256"]:
            raise ValueError(f"Master file changed: {row['sample_id']}")
        conditioned, _ = load_audio(row, runner.ROOT, verify=True)
        metrics = g.calculate_audio_metrics(np.stack([conditioned, conditioned]))
        for flag in ("is_silent", "is_clipped", "has_large_dc_offset"):
            if bool(metrics[flag]) != bool(row[flag]):
                raise ValueError(f"Recomputed QA flag mismatch: {row['sample_id']}/{flag}")
        for dimension, (name, spec) in enumerate(g.PARAMS.items()):
            expected = float(_SAMPLES[index, dimension])
            if not math.isclose(row[name + "_sample_01"], expected, abs_tol=1e-14, rel_tol=0):
                raise ValueError(f"Sobol coordinate mismatch: {row['sample_id']}/{name}")
            control = _CONTROLS[spec["control"]]
            control.set_normalized(spec["min"] + expected * (spec["max"] - spec["min"]))
            for suffix, actual in (("normalized", control.get_normalized()), ("raw", control.value())):
                if not math.isclose(actual, row[name + "_" + suffix], abs_tol=2e-6, rel_tol=0):
                    raise ValueError(f"Parameter mismatch: {row['sample_id']}/{name}_{suffix}")
            if _SYNTH.get_control_text(spec["control"]) != row[name + "_display"]:
                raise ValueError(f"Parameter display mismatch: {row['sample_id']}/{name}")
    return len(rows)


def audit(count=131072, workers=4, handoff=None, waveform_reference=None):
    start = time.perf_counter()
    if handoff is not None and handoff.exists():
        raise FileExistsError("Choose a new handoff directory; existing artifacts are preserved")
    signature = runner.recipe(count)
    saved_recipe = json.loads((runner.OUTPUT / "recipe.json").read_text(encoding="utf-8"))
    if signature != saved_recipe:
        raise ValueError("Corpus recipe/runtime/runner differs")
    rows, batches = [], []
    checkpoint_hashes = {}
    for path in sorted((runner.OUTPUT / "chunks").glob("*.json")):
        chunk = json.loads(path.read_text(encoding="utf-8"))
        if not chunk or path.stem != f"{len(rows):06d}":
            raise ValueError("Checkpoint continuity failure")
        for offset, row in enumerate(chunk):
            if row["sample_index"] != len(rows) + offset:
                raise ValueError("Checkpoint index continuity failure")
        batches.append(chunk)
        rows.extend(chunk)
        checkpoint_hashes[path.name] = runner.sha(path)
    if len(rows) != count:
        raise ValueError(f"Incomplete corpus: {len(rows):,}/{count:,}")
    new_parent = (runner.OUTPUT / "raw_float").relative_to(runner.ROOT).as_posix()
    expected_new = {Path(row["raw_audio_path"].replace("\\", "/")).name for row in rows
                    if Path(row["raw_audio_path"].replace("\\", "/")).parent.as_posix() == new_parent}
    if {p.name for p in (runner.OUTPUT / "raw_float").glob("*.wav")} != expected_new:
        raise ValueError("Missing or uncheckpointed new masters")
    print(f"Verifying {count:,} rows with {workers} processes: files, raw/processed samples and controls...", flush=True)
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    completed = 0
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn"),
                             initializer=initialize, initargs=(count,)) as pool:
        for size in pool.map(verify_chunk, batches):
            completed += size
            if completed % 4096 == 0 or completed == count:
                elapsed = time.perf_counter() - start
                print(f"Verified {completed:,}/{count:,} | elapsed {elapsed/60:.1f} min", flush=True)
    frame = pd.DataFrame(rows)
    parquet = pd.read_parquet(runner.OUTPUT / "manifest.parquet")
    pd.testing.assert_frame_equal(frame, parquet, check_dtype=False, check_exact=True)
    display_types = {name + "_display": str for name in runner.generator().PARAMS}
    csv = pd.read_csv(runner.OUTPUT / "manifest.csv", dtype=display_types, float_precision="round_trip")
    pd.testing.assert_frame_equal(parquet, csv, check_dtype=False, check_exact=True)
    summary = json.loads((runner.OUTPUT / "summary.json").read_text(encoding="utf-8"))
    if summary["count"] != count:
        raise ValueError("Summary count mismatch")
    for flag in ("is_silent", "is_clipped", "has_large_dc_offset"):
        if summary[flag] != sum(bool(row[flag]) for row in rows):
            raise ValueError("Summary QA totals mismatch")
    # Detect checkpoint changes while checking; do not certify a moving corpus.
    if any(runner.sha(runner.OUTPUT / "chunks" / name) != digest
           for name, digest in checkpoint_hashes.items()):
        raise ValueError("Checkpoint changed during audit")
    if waveform_reference is not None:
        expected = json.loads(waveform_reference.read_text(encoding="utf-8"))
        if expected != runner.reference(rows):
            raise ValueError("Full-corpus waveform reference differs")
        print("PASS: every raw and processed waveform matches the shared reference.", flush=True)
    names = list(runner.generator().PARAMS)
    result = dict(verified_rows=count, unique_raw_audio_paths=len({r['raw_audio_path'] for r in rows}),
                  uncheckpointed_wavs=0, raw_and_processed_hashes_verified=True,
                  recomputed_conditioned_qa_flags_verified=True,
                  manifest_csv_equals_parquet_equals_checkpoints=True, parameter_names=names,
                  quality_flags={k: summary[k] for k in ("is_silent", "is_clipped", "has_large_dc_offset")},
                  verification_seconds=time.perf_counter()-start)
    if waveform_reference is not None:
        result["shared_waveform_reference_matches"] = True
    if handoff is not None:
        handoff.mkdir(parents=True, exist_ok=False)
        with (handoff / "full_waveform_reference.json").open("x", encoding="utf-8") as handle:
            json.dump(runner.reference(rows), handle, sort_keys=True)
        identifiers = ["sample_id", "sample_index"]
        normalized = identifiers + [name + "_normalized" for name in names]
        all_params = identifiers + [name + "_" + suffix for name in names
                                    for suffix in ("sample_01", "normalized", "raw", "display")]
        parquet[normalized].to_parquet(handoff / "parameters_normalized.parquet", index=False, compression="zstd")
        parquet[all_params].to_parquet(handoff / "parameters_full.parquet", index=False, compression="zstd")
        for name, contents in (("reference_recipe.json", signature), ("reference_summary.json", summary)):
            (handoff / name).write_text(json.dumps(contents, indent=2), encoding="utf-8")
        result["artifacts"] = {p.name: dict(bytes=p.stat().st_size,
                              sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                              for p in handoff.iterdir() if p.is_file()}
        (handoff / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"Verified handoff created: {handoff.resolve()}", flush=True)
    print("PASS: completed corpus, waveform hashes, all control values/displays, both manifests and QA summary.", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=runner.count_value, default=131072)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--handoff", type=Path)
    parser.add_argument("--reference", type=Path, help="Shared full waveform JSON to compare after verification")
    args = parser.parse_args()
    if not 1 <= args.workers <= 32:
        parser.error("Workers must be between 1 and 32")
    audit(args.count, args.workers, args.handoff, args.reference)
