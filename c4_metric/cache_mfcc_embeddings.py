"""Build post-survey C4 MFCC26 vectors using C3's established extractor."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from c4_metric.mfcc26 import (  # noqa: E402
    F_MAX_HZ, F_MIN_HZ, FEATURE_DIMENSION, HOP_LENGTH, N_FFT, N_MELS, N_MFCC,
    SAMPLE_RATE, dct_basis, extract_mfcc_summary, mel_filterbank, read_target_audio,
)

REPRESENTATION = "mfcc26"
ENCODER_ID = "c3-mfcc26"
PILOT_MARK = "REHEARSAL_PILOT_DO_NOT_USE_AS_VALIDATED_HUMAN_STUDY_RESULTS"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV needs a header row: {path}")
        return list(reader.fieldnames), list(reader)


def _manifest_rows(path: Path) -> tuple[list[str], list[dict[str, str]], dict[str, dict[str, str]]]:
    fields, rows = read_csv(path)
    if "sample_id" not in fields:
        raise ValueError("Audio manifest must contain sample_id")
    by_id: dict[str, dict[str, str]] = {}
    for line, row in enumerate(rows, start=2):
        sample_id = row.get("sample_id", "").strip()
        if not sample_id:
            raise ValueError(f"Blank sample_id in manifest row {line}")
        if sample_id in by_id:
            raise ValueError(f"Duplicate sample_id in manifest: {sample_id}")
        by_id[sample_id] = row
    return fields, rows, by_id


def _audio_for_row(row: dict[str, str], sample_id: str) -> tuple[np.ndarray, int]:
    audio_path_text = (row.get("audio_path") or row.get("audio_path_text") or "").strip()
    if audio_path_text:
        path = Path(audio_path_text.replace("\\", "/"))
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_file():
            raise FileNotFoundError(f"Missing audio for {sample_id}: {path}")
        return read_target_audio(path, SAMPLE_RATE), SAMPLE_RATE
    if row.get("raw_audio_path", "").strip():
        from generation.corpus_audio import load_audio
        audio, sample_rate = load_audio(row, ROOT, verify=True)
        # C3's wav loader receives the already DC-conditioned canonical waveform.
        return np.asarray(audio, dtype=np.float64), int(sample_rate)
    raise ValueError(f"Manifest has no audio_path or raw_audio_path for {sample_id}")


def _parameter_metadata(row: dict[str, str]) -> dict[str, Any]:
    keys = [key for key in row if key.endswith(("_normalized", "_sample_01"))]
    metadata: dict[str, Any] = {}
    for key in keys:
        value = row.get(key, "")
        if value == "":
            metadata[key] = None
            continue
        try:
            metadata[key] = float(value)
        except ValueError as error:
            raise ValueError(f"Invalid numeric synthesizer metadata {key}={value!r}") from error
    return metadata


def extract(triplets_path: Path, manifest_path: Path, output: Path, *,
            allow_synthetic: bool = False, allow_pilot_rehearsal: bool = False,
            overwrite: bool = False) -> dict[str, Any]:
    if output.suffix.casefold() != ".npz":
        raise ValueError("Embedding output must use the .npz extension")
    triplet_fields, triplets = read_csv(triplets_path)
    required_triplet_fields = {"data_status", "comparison_ids", "anchor_id", "positive_id",
                               "negative_id", "vote_status"}
    if not triplets or not required_triplet_fields.issubset(triplet_fields):
        raise ValueError(f"Aggregated triplets must be nonempty and contain {sorted(required_triplet_fields)}")
    statuses = {row.get("vote_status", "").strip() for row in triplets}
    if statuses != {"preference"}:
        raise ValueError(f"Embedding cache accepts only aggregated preference rows, found statuses: {sorted(statuses)}")
    if any(not row.get("comparison_ids", "").strip() for row in triplets):
        raise ValueError("Aggregated preference rows must retain their comparison IDs")
    data_statuses = {row.get("data_status", "").strip() for row in triplets}
    if len(data_statuses) != 1 or not next(iter(data_statuses)):
        raise ValueError("Triplets must have one consistent, nonblank data_status")
    data_status = next(iter(data_statuses))
    pilot_rehearsal = data_status == PILOT_MARK
    if data_status not in {"human_response", PILOT_MARK} and "SYNTHETIC" not in data_status:
        raise ValueError(f"Unrecognized survey data_status: {next(iter(data_statuses))!r}")
    synthetic = "SYNTHETIC" in data_status
    if synthetic and not allow_synthetic:
        raise ValueError("Synthetic preferences require explicit allow_synthetic=True")
    if pilot_rehearsal and not allow_pilot_rehearsal:
        raise ValueError("Rehearsal pilot preferences require explicit --pilot-rehearsal")
    if allow_pilot_rehearsal and not pilot_rehearsal:
        raise ValueError("--pilot-rehearsal accepts only marked rehearsal pilot triplets")
    wanted = sorted({row[column].strip() for row in triplets for column in
                     ("anchor_id", "positive_id", "negative_id")})
    if "" in wanted:
        raise ValueError("Aggregated triplets contain a blank audio sample ID")

    manifest_fields, _, by_id = _manifest_rows(manifest_path)
    missing = sorted(set(wanted) - by_id.keys())
    if missing:
        raise ValueError(f"Manifest is missing {len(missing)} sample IDs: {missing[:8]}")
    if not any(name in manifest_fields for name in ("audio_path", "audio_path_text", "raw_audio_path")):
        raise ValueError("Audio manifest must provide audio_path or raw_audio_path")

    metadata_path = output.with_suffix(".json")
    source_hashes = {"triplets_sha256": sha256_file(triplets_path),
                     "manifest_sha256": sha256_file(manifest_path)}
    if output.exists() or metadata_path.exists():
        if output.is_file() and metadata_path.is_file() and not overwrite:
            try:
                old_meta = json.loads(metadata_path.read_text(encoding="utf-8"))
                with np.load(output, allow_pickle=False) as archive:
                    cached_ids = archive["sample_ids"].astype(str).tolist()
                    cached = archive["embeddings"]
                if (old_meta.get("representation") == REPRESENTATION
                        and old_meta.get("sample_ids") == wanted
                        and all(old_meta.get(key) == value for key, value in source_hashes.items())
                        and cached.shape == (len(wanted), FEATURE_DIMENSION)
                        and cached.dtype == np.float32 and cached_ids == wanted):
                    return old_meta
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                pass
            raise FileExistsError(f"Existing embedding artifact differs or is incomplete: {output}; use overwrite=True to replace it")
        if not overwrite:
            raise FileExistsError(f"Refusing to overwrite existing embedding artifact: {output}")

    settings = {
        "sample_rate": SAMPLE_RATE, "n_fft": N_FFT,
        "hop_length": HOP_LENGTH, "n_mels": N_MELS,
        "n_mfcc": N_MFCC, "f_min_hz": F_MIN_HZ,
        "f_max_hz": F_MAX_HZ, "window": "Hann",
        "frame_padding": "reflect", "summary": "per-coefficient mean and standard deviation",
    }
    bank = mel_filterbank(SAMPLE_RATE, N_FFT, N_MELS, F_MIN_HZ, F_MAX_HZ)
    basis = dct_basis(N_MFCC, N_MELS)
    feature_rows: list[np.ndarray] = []
    sample_metadata: list[dict[str, Any]] = []
    for index, sample_id in enumerate(wanted, start=1):
        row = by_id[sample_id]
        audio, rate = _audio_for_row(row, sample_id)
        if rate != SAMPLE_RATE:
            raise ValueError(f"C3 MFCC extractor requires {SAMPLE_RATE} Hz audio for {sample_id}, got {rate}")
        feature = np.asarray(extract_mfcc_summary(audio, settings, bank, basis), dtype=np.float64)
        if feature.shape != (FEATURE_DIMENSION,) or not np.isfinite(feature).all():
            raise ValueError(f"Invalid mfcc26 feature for {sample_id}: shape={feature.shape}")
        feature_rows.append(feature.astype(np.float32))
        sample_metadata.append({
            "sample_id": sample_id,
            "audio_path": row.get("audio_path") or row.get("audio_path_text") or row.get("raw_audio_path"),
            "synthesizer_parameters": _parameter_metadata(row),
        })
        if index == 1 or index % 64 == 0 or index == len(wanted):
            print(f"Extracted {index}/{len(wanted)} MFCC26 samples")

    matrix = np.stack(feature_rows).astype(np.float32, copy=False)
    if matrix.shape != (len(wanted), FEATURE_DIMENSION) or not np.isfinite(matrix).all():
        raise ValueError(f"Invalid embedding matrix: shape={matrix.shape}, dtype={matrix.dtype}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, sample_ids=np.asarray(wanted, dtype=np.str_), embeddings=matrix)
    temporary.replace(output)
    meta = {
        "data_status": ("SYNTHETIC_DO_NOT_USE_AS_HUMAN_EVIDENCE" if synthetic else
                         PILOT_MARK if pilot_rehearsal else "human_response"),
        "representation": REPRESENTATION, "model": ENCODER_ID,
        "feature_dimension": FEATURE_DIMENSION, "embedding_dimension": FEATURE_DIMENSION,
        "dtype": "float32", "shape": list(matrix.shape), "normalized": False,
        "preprocessing": settings, "feature_source": "C3 extract_mfcc_summary contract (c4_metric.mfcc26)",
        "manifest_path": str(manifest_path), "triplets_path": str(triplets_path),
        **source_hashes, "sample_count": len(wanted), "sample_ids": wanted,
        "samples": sample_metadata, "data_path": str(output),
    }
    temp_meta = metadata_path.with_name(metadata_path.name + ".tmp")
    temp_meta.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    temp_meta.replace(metadata_path)
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("triplets", type=Path, help="aggregate_preference_triplets.csv")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/raw/corpus_v4/manifest.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "c4_metric/outputs/human_embeddings/mfcc26_embeddings.npz")
    parser.add_argument("--allow-synthetic", action="store_true")
    parser.add_argument("--pilot-rehearsal", action="store_true",
                        help="Explicitly cache marked rehearsal pilot triplets")
    parser.add_argument("--overwrite", action="store_true", help="Replace a non-matching existing cache")
    args = parser.parse_args()
    print(json.dumps(extract(args.triplets, args.manifest, args.output,
                             allow_synthetic=args.allow_synthetic,
                             allow_pilot_rehearsal=args.pilot_rehearsal,
                             overwrite=args.overwrite), indent=2))


if __name__ == "__main__":
    main()
