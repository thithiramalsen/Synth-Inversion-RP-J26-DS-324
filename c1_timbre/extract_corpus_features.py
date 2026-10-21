"""Extract c1_features_v2 and pilot-eligibility metrics for the v4 corpus.

Audio is read through generation.corpus_audio.load_audio (raw FLOAT master + the
declared DC policy, applied once). No level gain is applied: v2 features are
gain-invariant. Results are cached in chunks so an interrupted run resumes.

    .\\venv\\Scripts\\python.exe -B -m c1_timbre.extract_corpus_features --workers 8
"""
from __future__ import annotations

import argparse
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from c1_timbre.features_v2 import FEATURE_NAMES, FEATURE_VERSION, extract

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/raw/corpus_v4/manifest.parquet"
DEFAULT_OUT = ROOT / "data/processed/c1_features_v2/corpus_features.parquet"
CHUNK = 2048


def _metrics(audio):
    held = audio[: round(1.5 * 44100)]
    return dict(held_rms=float(np.sqrt(np.mean(held ** 2))), peak=float(np.max(np.abs(audio))),
                tail_peak=float(np.max(np.abs(audio[-round(0.05 * 44100):]))),
                rms=float(np.sqrt(np.mean(audio ** 2))), dc_offset=float(audio.mean()))


def _work(rows):
    from generation.corpus_audio import load_audio
    out = []
    for row in rows:
        audio, sr = load_audio(row)
        audio = np.asarray(audio, dtype=np.float64)
        rec = dict(sample_id=row["sample_id"], sample_index=int(row["sample_index"]), **_metrics(audio))
        try:
            rec.update(extract(audio, sr))
            rec["feature_error"] = ""
        except Exception as error:  # recorded, never silently dropped
            rec.update({k: np.nan for k in FEATURE_NAMES})
            rec["feature_error"] = repr(error)
        out.append(rec)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=DEFAULT_OUT)
    p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    p.add_argument("--limit", type=int, default=None, help="first N sample indices (a 2^m prefix keeps Sobol balance)")
    args = p.parse_args()
    cols = ["sample_id", "sample_index", "audio_policy_id", "raw_audio_path", "raw_clipped", "raw_silent",
            "is_silent", "is_clipped", "has_large_dc_offset", "processed_samples_sha256", "raw_samples_sha256"]
    manifest = pd.read_parquet(MANIFEST, columns=cols).sort_values("sample_index")
    if args.limit:
        manifest = manifest.iloc[: args.limit]
    chunk_dir = args.output.parent / (args.output.stem + "_chunks")
    chunk_dir.mkdir(parents=True, exist_ok=True)
    todo = []
    for start in range(0, len(manifest), CHUNK):
        path = chunk_dir / f"{start:06d}.parquet"
        if not path.exists():
            todo.append((path, manifest.iloc[start: start + CHUNK].to_dict("records")))
    print(f"{len(todo)} chunks to process with {args.workers} workers", flush=True)
    with ProcessPoolExecutor(args.workers) as pool:
        futures = {}
        for path, rows in todo:
            parts = [rows[i: i + 128] for i in range(0, len(rows), 128)]
            futures[path] = [pool.submit(_work, part) for part in parts]
        for n, (path, fs) in enumerate(futures.items(), 1):
            pd.DataFrame([r for f in fs for r in f.result()]).to_parquet(path, index=False)
            print(f"chunk {n}/{len(futures)} -> {path.name}", flush=True)
    feats = pd.concat([pd.read_parquet(p) for p in sorted(chunk_dir.glob("*.parquet"))], ignore_index=True)
    merged = manifest.merge(feats, on=["sample_id", "sample_index"], how="inner", validate="one_to_one")
    if len(merged) != len(manifest):
        raise RuntimeError("Feature rows do not match the manifest")
    merged["feature_version"] = FEATURE_VERSION
    merged.to_parquet(args.output, index=False)
    print(f"Wrote {args.output} ({len(merged)} rows, {merged.feature_error.ne('').sum()} feature errors)")


if __name__ == "__main__":
    main()
