"""Resumable, checksummed float32 log-mel shards; never preprocess test audio."""
from __future__ import annotations

import os

# Avoid nested BLAS thread pools during concurrent file/FFT extraction.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import time

import numpy as np
import pandas as pd

from c2_estimation.pipeline import create_mel_filterbank, extract_log_mel, preprocessing_settings
from c2_estimation.v4.data import (DEFAULT_PREPARED, ROOT, digest_json, inverse_rows,
                                  load_prepared, sha, write_json)
from generation.corpus_audio import load_audio

SHARD_SIZE = 512


def build_cache(prepared: Path, cache: Path, scope: str, workers: int = 4) -> dict:
    if workers < 1:
        raise ValueError("Workers must be positive")
    protocol, frame = load_prepared(prepared)
    selected = inverse_rows(frame, scope)
    if selected.empty or (selected.split == "test").any():
        raise ValueError("Invalid inverse-model selection")
    settings = preprocessing_settings(protocol["recipe"]["synthesis"])
    signature_data = {
        "protocol_sha256": sha(prepared / "protocol.json"), "scope": scope,
        "sample_ids": selected.sample_id.tolist(), "settings": settings,
        "storage_dtype": "float32", "shard_size": SHARD_SIZE,
        "sources": {name: sha(ROOT / name) for name in (
            "c2_estimation/pipeline.py", "c2_estimation/v4/features.py",
            "generation/corpus_audio.py", "generation/audio_processing.py")},
    }
    signature = digest_json(signature_data)
    metadata_path = cache / "cache.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata["signature"] != signature:
            raise ValueError("Cache configuration changed; choose a NEW cache directory")
        if sha(cache / "rows.parquet") != metadata["rows_sha256"]:
            raise ValueError("Cached row identities changed")
    else:
        if cache.exists() and any(cache.iterdir()):
            raise ValueError("Refusing to overwrite nonempty cache without metadata")
        required = len(selected) * 64 * 259 * 4 + 256 * 1024**2
        if shutil.disk_usage(prepared).free < required:
            raise ValueError("Insufficient space for float32 feature cache plus safety margin")
        cache.mkdir(parents=True, exist_ok=True)
        selected.to_parquet(cache / "rows.parquet", index=False)
        metadata = {"signature": signature, **signature_data,
                    "rows_sha256": sha(cache / "rows.parquet"), "shards": [], "complete": False}
        write_json(metadata_path, metadata)
    window = np.hanning(settings["n_fft"]).astype(np.float32)
    bank = create_mel_filterbank(44100, settings["n_fft"], settings["n_mels"], 20., 20000.)

    def extract(row):
        audio, rate = load_audio(row, ROOT, verify=True)
        if rate != 44100:
            raise ValueError("Unexpected sample rate")
        result = extract_log_mel(audio, window, bank, settings["n_fft"], settings["hop_length"], settings["top_db"])
        if result.shape != (64, 259) or not np.isfinite(result).all():
            raise ValueError("Unexpected log-mel output")
        return result

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for number, offset in enumerate(range(0, len(selected), SHARD_SIZE)):
            path = cache / f"shard_{number:04d}.npy"
            if number < len(metadata["shards"]):
                if sha(path) != metadata["shards"][number]["sha256"]:
                    raise ValueError(f"Corrupt feature shard: {path}")
                continue
            rows = selected.iloc[offset:offset + SHARD_SIZE].to_dict("records")
            features = np.stack(list(executor.map(extract, rows)))
            temporary = path.with_suffix(".npy.tmp")
            with temporary.open("wb") as handle:
                np.save(handle, features, allow_pickle=False)
            temporary.replace(path)
            metadata["shards"].append({"file": path.name, "sha256": sha(path), "count": len(rows)})
            write_json(metadata_path, metadata)
            print(f"Features {offset + len(rows):,}/{len(selected):,}; elapsed {time.perf_counter()-start:.1f}s", flush=True)
    metadata["complete"] = True
    write_json(metadata_path, metadata)
    print(f"Complete cache: {cache}", flush=True)
    return metadata


def load_cache(cache: Path) -> tuple[dict, pd.DataFrame, list[np.ndarray]]:
    meta = json.loads((cache / "cache.json").read_text(encoding="utf-8"))
    if not meta["complete"] or sha(cache / "rows.parquet") != meta["rows_sha256"]:
        raise ValueError("Incomplete cache or altered row mapping")
    arrays = []
    for item in meta["shards"]:
        path = cache / item["file"]
        if sha(path) != item["sha256"]:
            raise ValueError(f"Feature checksum mismatch: {path}")
        array = np.load(path, mmap_mode="r", allow_pickle=False)
        if array.shape != (item["count"], 64, 259) or array.dtype != np.float32:
            raise ValueError("Unexpected cached feature shape/dtype")
        arrays.append(array)
    rows = pd.read_parquet(cache / "rows.parquet")
    if sum(len(a) for a in arrays) != len(rows) or rows.sample_id.tolist() != meta["sample_ids"]:
        raise ValueError("Cache cardinality/identity mismatch")
    return meta, rows, arrays


def training_statistics(arrays: list[np.ndarray], train_indexes: np.ndarray) -> tuple[float, float]:
    total, square, count = 0., 0., 0
    for number, array in enumerate(arrays):
        local = train_indexes[(train_indexes >= number * SHARD_SIZE) &
                              (train_indexes < number * SHARD_SIZE + len(array))] - number * SHARD_SIZE
        for start in range(0, len(local), 64):
            block = np.asarray(array[local[start:start+64]], dtype=np.float64)
            total += float(block.sum())
            square += float(np.square(block).sum())
            count += block.size
    if count == 0:
        raise ValueError("Cannot fit normalization without training samples")
    mean = total / count
    return mean, max(float(np.sqrt(max(square / count - mean * mean, 0.))), 1e-6)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, default=DEFAULT_PREPARED)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--scope", choices=("development", "full"), default="development")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    build_cache(args.prepared, args.cache, args.scope, args.workers)
