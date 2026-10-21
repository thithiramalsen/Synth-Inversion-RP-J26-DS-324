"""Phase 6 - extract audio feature summaries for every corpus sample in ONE streaming pass.

Writes to ``<outputs_dir>/features/``:
  mfcc26.npy, logmel_stats.npy   (float64, one row per sample, sample_index order)
  feature_index.parquet          (row -> sample_id, sample_index)
  features_meta.json             (all feature settings, audio policy, hashes, runtime)

An existing cache with the same settings and ID list is kept unless ``--force``.
``--limit N`` runs a timing trial on the first N samples and writes nothing.

Usage (repo root):
    python c3_recommendation/scripts/06_extract_features.py [--workers 8] [--limit 1024]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from c3.audio_io import AudioPolicy  # noqa: E402
from c3.config import load_config  # noqa: E402
from c3.data_sources import make_source  # noqa: E402
from c3.features import REPRESENTATIONS, FeatureSettings, extract_corpus  # noqa: E402
from c3.splits import ids_sha256  # noqa: E402

META = "features_meta.json"
INDEX = "feature_index.parquet"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None)
    parser.add_argument("--workers", type=int, default=max(1, min(8, (os.cpu_count() or 2) - 2)))
    parser.add_argument("--chunk", type=int, default=256)
    parser.add_argument("--limit", type=int, default=None, help="timing trial on the first N samples; writes nothing")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if cfg["data.source"] != "corpus_v4":
        raise SystemExit("features need audio: data.source must be corpus_v4 (Phase 5 gate)")
    out_dir = cfg.path("outputs_dir") / "features"
    out_dir.mkdir(parents=True, exist_ok=True)
    source = make_source(cfg)
    ids = list(source.sample_ids())
    settings = FeatureSettings()
    policy = AudioPolicy.from_corpus(cfg.path("corpus_dir"))
    if args.limit:
        ids = ids[: args.limit]

    meta_path = out_dir / META
    if not args.limit and meta_path.exists() and not args.force:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("settings") == settings.as_dict() and meta.get("sha256_ids") == ids_sha256(ids):
            print(f"Cache already complete for {len(ids)} samples with identical settings; use --force to rebuild.")
            return

    started = time.time()
    last = [0.0]

    def progress(done, total):
        now = time.time()
        if done == total or now - last[0] > 20:
            last[0] = now
            rate = done / max(now - started, 1e-9)
            eta = (total - done) / rate if rate else float("nan")
            print(f"  {done:,}/{total:,} ({100 * done / total:.1f}%)  {rate:.0f} clips/s  ETA {eta / 60:.1f} min", flush=True)

    print(f"Extracting {REPRESENTATIONS} for {len(ids):,} samples with {args.workers} workers ...", flush=True)
    features = extract_corpus(cfg.path("corpus_dir"), ids, settings, workers=args.workers, chunk=args.chunk,
                              progress=progress)
    elapsed = time.time() - started
    for rep, array in features.items():
        if not np.isfinite(array).all():
            raise SystemExit(f"{rep}: non-finite feature values")
    if args.limit:
        per_clip = elapsed / len(ids)
        print(f"TRIAL: {elapsed:.1f} s for {len(ids)} clips = {per_clip * 1000:.1f} ms/clip wall-clock; "
              f"full corpus estimate {per_clip * 131072 / 60:.1f} min. Nothing written.")
        return

    hashes = {}
    for rep, array in features.items():
        final = out_dir / f"{rep}.npy"
        temporary = out_dir / f"{rep}.tmp.npy"
        np.save(temporary, array)
        os.replace(temporary, final)
        hashes[rep] = file_sha256(final)
    index = pd.DataFrame({"sample_id": ids, "sample_index": source.params_normalized().index.get_indexer(ids)})
    index.to_parquet(out_dir / INDEX, index=False)
    meta = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "data_source": cfg["data.source"],
        "n_samples": len(ids),
        "sha256_ids": ids_sha256(ids),
        "representations": {rep: {"file": f"{rep}.npy", "dims": int(features[rep].shape[1]),
                                  "dtype": str(features[rep].dtype), "sha256": hashes[rep]}
                            for rep in REPRESENTATIONS},
        "settings": settings.as_dict(),
        "audio_policy": policy.describe(),
        "continuity": "mfcc26 equals c3_recommendation/pipeline.py:extract_mfcc_summary (pilot_v1) exactly",
        "workers": args.workers, "chunk": args.chunk,
        "runtime_seconds": round(elapsed, 1), "ms_per_clip_wall": round(1000 * elapsed / len(ids), 2),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Done in {elapsed / 60:.1f} min ({meta['ms_per_clip_wall']} ms/clip wall). Saved to {out_dir}")
    for rep in REPRESENTATIONS:
        print(f"  {rep}: {features[rep].shape}  sha256 {hashes[rep][:16]}...")


if __name__ == "__main__":
    main()
