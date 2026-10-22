"""Cache frozen CLAP audio embeddings for audio IDs used by preference triplets."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from c4_metric.similarity import prepare_audio


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rows(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def extract(triplets_path: Path, manifest_path: Path, output: Path, *,
            model_id: str = "laion/clap-htsat-unfused",
            revision: str | None = "8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a",
            batch_size: int = 16, local_files_only: bool = True) -> dict:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    triplets = rows(triplets_path)
    if not triplets:
        raise ValueError("Triplet file is empty")
    id_columns = ("anchor_id", "positive_id", "negative_id")
    if not set(id_columns).issubset(triplets[0]):
        # Permit either the survey export format or the CLAP bank format.
        alternatives = (("reference", "candidate_a", "candidate_b"),
                        ("reference_sample_id", "candidate_a_sample_id", "candidate_b_sample_id"))
        match = next((fields for fields in alternatives if set(fields).issubset(triplets[0])), None)
        if match is None:
            raise ValueError("Need anchor/positive/negative, reference/A/B, or reference_sample_id/candidate_sample_id columns")
        id_columns = match
    wanted = sorted({row[column].strip() for row in triplets for column in id_columns})
    manifest = rows(manifest_path)
    by_id = {row["sample_id"]: row for row in manifest}
    missing = set(wanted) - by_id.keys()
    if missing:
        raise ValueError(f"Manifest is missing {len(missing)} requested sample IDs: {sorted(missing)[:8]}")
    audio = []
    for sid in wanted:
        row = by_id[sid]
        if row.get("raw_audio_path"):
            from generation.corpus_audio import read_raw
            waveform, rate = read_raw(row, ROOT), 44_100
        else:
            text_path = row.get("audio_path") or row.get("audio_path_text")
            if not text_path:
                raise ValueError(f"Manifest has no audio path for {sid}")
            path = (ROOT / text_path).resolve()
            if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
                raise ValueError(f"Unsafe or missing audio path for {sid}: {path}")
            waveform, rate = sf.read(path, dtype="float32", always_2d=False)
        audio.append(prepare_audio((waveform, rate)))
    try:
        import torch
        from transformers import ClapAudioModelWithProjection, ClapProcessor
    except ImportError as error:
        raise RuntimeError("CLAP embedding cache requires torch and transformers") from error
    processor = ClapProcessor.from_pretrained(model_id, revision=revision,
                                               local_files_only=local_files_only)
    model = ClapAudioModelWithProjection.from_pretrained(model_id, revision=revision,
                                                          local_files_only=local_files_only)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device).eval()
    vectors = []
    for start in range(0, len(audio), batch_size):
        waveforms = [resample_poly(x, 160, 147).astype(np.float32)
                     for x in audio[start:start + batch_size]]
        inputs = processor(audios=waveforms, sampling_rate=48_000, return_tensors="pt", padding=True)
        inputs = {key: value.to(device) for key, value in inputs.items()}
        with torch.inference_mode():
            values = model(**inputs).audio_embeds.detach().cpu().numpy().astype(np.float32)
        norms = np.linalg.norm(values, axis=1, keepdims=True)
        if np.any(norms < 1e-12) or not np.isfinite(values).all():
            raise ValueError("CLAP returned invalid embeddings")
        vectors.append(values / norms)
        print(f"Encoded {min(start + len(waveforms), len(wanted))}/{len(wanted)} audio IDs")
    matrix = np.concatenate(vectors)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, sample_ids=np.asarray(wanted), embeddings=matrix)
    meta = {
        "data_status": "frozen_encoder_embeddings",
        "model": model_id, "revision": revision, "sample_rate_hz": 48_000,
        "canonical_input_rate_hz": 44_100, "preprocessing": "mono, DC high-pass, clip RMS match, resample_poly to 48 kHz",
        "manifest": str(manifest_path), "manifest_sha256": file_hash(manifest_path),
        "triplets": str(triplets_path), "triplets_sha256": file_hash(triplets_path),
        "sample_count": len(wanted), "embedding_dimension": int(matrix.shape[1]),
        "normalized": True, "data_path": str(output),
    }
    output.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("triplets", type=Path)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/raw/corpus_v4/manifest.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "c4_metric/outputs/embeddings/clap_embeddings.npz")
    parser.add_argument("--model-id", default="laion/clap-htsat-unfused")
    parser.add_argument("--revision", default="8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--allow-model-download", action="store_true",
                        help="Allow Transformers to download the pinned model when it is not cached locally")
    args = parser.parse_args()
    print(json.dumps(extract(args.triplets, args.manifest, args.output,
                             model_id=args.model_id, revision=args.revision,
                             batch_size=args.batch_size,
                             local_files_only=not args.allow_model_download), indent=2))


if __name__ == "__main__":
    main()
