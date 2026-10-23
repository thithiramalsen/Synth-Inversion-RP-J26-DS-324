"""Evaluate a rehearsal-only C4 checkpoint on its held-out pilot split."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from c4_metric.model import TripletProjection, cosine_distance

PILOT_MARK = "REHEARSAL_PILOT_DO_NOT_USE_AS_VALIDATED_HUMAN_STUDY_RESULTS"
CLAP_MODEL = "laion/clap-htsat-unfused"
CLAP_REVISION = "8fa0f1c6d0433df6e97c127f64b2a1d6c0dcda8a"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def split_digest(path: Path, split: str) -> str:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = [row for row in csv.DictReader(stream) if row.get("split") == split]
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def check(split_path: Path, embeddings_path: Path, checkpoint_path: Path,
          output_path: Path, *, bootstrap_draws: int = 10_000, seed: int = 20261023) -> dict:
    if bootstrap_draws < 100:
        raise ValueError("Use at least 100 bootstrap draws")
    with split_path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or any(row.get("data_status") != PILOT_MARK for row in rows):
        raise ValueError("Pilot check accepts only explicitly marked rehearsal-pilot rows")
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    if (checkpoint.get("data_status") != PILOT_MARK or not checkpoint.get("pilot_rehearsal")
            or checkpoint.get("encoder_model") != CLAP_MODEL
            or checkpoint.get("encoder_revision") != CLAP_REVISION
            or checkpoint.get("input_dim") != 512):
        raise ValueError("Checkpoint is not the expected pinned-CLAP rehearsal-pilot checkpoint")
    expected_split_hash = checkpoint.get("test_triplets_sha256")
    actual_split_hash = split_digest(split_path, "test")
    if expected_split_hash != actual_split_hash:
        raise ValueError("Test split does not match the split used by this checkpoint")

    metadata_path = embeddings_path.with_suffix(".json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if (metadata.get("data_status") != PILOT_MARK or not metadata.get("pilot_rehearsal")
            or metadata.get("model") != CLAP_MODEL
            or metadata.get("revision") != CLAP_REVISION
            or metadata.get("embedding_dimension") != 512):
        raise ValueError("Embedding cache is not the expected pinned-CLAP rehearsal-pilot cache")
    with np.load(embeddings_path, allow_pickle=False) as archive:
        sample_ids = archive["sample_ids"].astype(str)
        vectors = np.asarray(archive["embeddings"], dtype=np.float32)
    if (vectors.shape != (len(sample_ids), 512) or len(set(sample_ids)) != len(sample_ids)
            or not np.isfinite(vectors).all()):
        raise ValueError("CLAP cache has invalid IDs, dimensions, or values")
    index = {sample_id: i for i, sample_id in enumerate(sample_ids)}
    test_rows = [row for row in rows if row.get("split") == "test"
                 and row.get("vote_status", "preference") in {"preference", "majority", ""}]
    if not test_rows:
        raise ValueError("No decisive held-out test rows remain")
    missing = {row[key] for row in test_rows for key in ("anchor_id", "positive_id", "negative_id")
               if row[key] not in index}
    if missing:
        raise ValueError(f"Embedding cache misses {len(missing)} held-out sample IDs")

    model = TripletProjection(512, checkpoint["output_dim"], checkpoint.get("normalize", True))
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    ids = np.asarray([[index[row[key]] for key in ("anchor_id", "positive_id", "negative_id")]
                      for row in test_rows], dtype=np.int64)
    triplet_embeddings = torch.from_numpy(vectors[ids])
    with torch.inference_mode():
        anchor = model(triplet_embeddings[:, 0, :])
        positive = model(triplet_embeddings[:, 1, :])
        negative = model(triplet_embeddings[:, 2, :])
        positive_distance = cosine_distance(anchor, positive).numpy()
        negative_distance = cosine_distance(anchor, negative).numpy()
    row_accuracy = (positive_distance < negative_distance).astype(np.float64)
    ties = np.isclose(positive_distance, negative_distance, atol=1e-12, rtol=0)
    row_accuracy[ties] = 0.5
    signatures = [row.get("comparison_ids") or row.get("comparison_id") or
                  "|".join(row[key] for key in ("anchor_id", "positive_id", "negative_id"))
                  for row in test_rows]
    by_signature: dict[str, list[float]] = {}
    for signature, value in zip(signatures, row_accuracy, strict=True):
        by_signature.setdefault(signature, []).append(float(value))
    signature_accuracy = np.asarray([np.mean(values) for values in by_signature.values()])
    rng = np.random.default_rng(seed)
    sampled = rng.integers(0, len(signature_accuracy),
                           size=(bootstrap_draws, len(signature_accuracy)))
    bootstrap_means = signature_accuracy[sampled].mean(axis=1)
    report = {
        "data_status": PILOT_MARK,
        "pilot_rehearsal": True,
        "evaluation": "Held-out rehearsal-pilot diagnostic only; not validated human-study evidence.",
        "checkpoint": str(checkpoint_path.resolve()),
        "checkpoint_sha256": sha256(checkpoint_path),
        "encoder": CLAP_MODEL,
        "encoder_revision": CLAP_REVISION,
        "embedding_dimension": 512,
        "test_split_sha256": actual_split_hash,
        "test_response_rows": len(test_rows),
        "test_comparison_signatures": len(by_signature),
        "response_level_preference_accuracy": float(row_accuracy.mean()),
        "comparison_signature_macro_preference_accuracy": float(signature_accuracy.mean()),
        "signature_cluster_bootstrap_95_percent_ci": [
            float(np.quantile(bootstrap_means, 0.025)), float(np.quantile(bootstrap_means, 0.975))],
        "ties": int(ties.sum()),
        "test_labels_used_for_training_or_checkpoint_selection": False,
        "warning": "Rehearsal pilot data, not validated human-study results. Participants and sessions may overlap across splits.",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite accuracy report: {output_path}")
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--embeddings", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-draws", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20261023)
    args = parser.parse_args()
    print(json.dumps(check(args.split, args.embeddings, args.checkpoint, args.output,
                           bootstrap_draws=args.bootstrap_draws, seed=args.seed), indent=2))


if __name__ == "__main__":
    main()
