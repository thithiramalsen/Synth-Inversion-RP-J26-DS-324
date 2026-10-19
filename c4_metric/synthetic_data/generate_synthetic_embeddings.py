"""Generate controlled dummy embeddings and A/P/N labels for pipeline checks."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = Path(__file__).resolve().parent / "pipeline_smoke"
MARK = "SYNTHETIC_DO_NOT_USE_AS_HUMAN_EVIDENCE"


def unit(value: np.ndarray) -> np.ndarray:
    return value / np.maximum(np.linalg.norm(value, axis=-1, keepdims=True), 1e-12)


def generate(output_dir: Path, triplets: int = 600, dimension: int = 128,
             seed: int = 20261014) -> tuple[Path, Path]:
    if triplets < 30 or dimension < 4:
        raise ValueError("Use at least 30 triplets and embedding dimension >= 4")
    rng = np.random.default_rng(seed)
    rows = []
    sample_ids = []
    vectors = []
    for i in range(triplets):
        anchor = unit(rng.normal(size=dimension))
        positive = unit(anchor + 0.20 * rng.normal(size=dimension))
        negative = unit(anchor + 0.85 * rng.normal(size=dimension))
        ids = [f"DUMMY_AUDIO_{3*i+j:06d}" for j in range(3)]
        sample_ids.extend(ids)
        vectors.extend([anchor, positive, negative])
        rows.append({
            "data_status": MARK,
            "comparison_id": f"DUMMY_CMP_{i+1:05d}",
            "participant_id": f"DUMMY_LISTENER_{i+1:05d}",
            "anchor_id": ids[0], "positive_id": ids[1], "negative_id": ids[2],
            "confidence": 5,
        })
    output_dir.mkdir(parents=True, exist_ok=True)
    embedding_path = output_dir / "synthetic_embeddings.npz"
    triplet_path = output_dir / "synthetic_preference_triplets.csv"
    np.savez_compressed(embedding_path, sample_ids=np.asarray(sample_ids),
                        embeddings=np.asarray(vectors, dtype=np.float32))
    with triplet_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    metadata = {"data_status": MARK, "seed": seed, "triplets": triplets,
                "embedding_dimension": dimension,
                "construction": "positive vectors are perturbed less than negative vectors from each anchor",
                "human_evidence": False}
    (output_dir / "synthetic_embeddings_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return embedding_path, triplet_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--triplets", type=int, default=600)
    parser.add_argument("--dimension", type=int, default=128)
    parser.add_argument("--seed", type=int, default=20261014)
    args = parser.parse_args()
    embedding_path, triplet_path = generate(args.output_dir, args.triplets, args.dimension, args.seed)
    print(f"Wrote controlled synthetic embeddings: {embedding_path}")
    print(f"Wrote synthetic preference triplets: {triplet_path}")
    print(f"Triplets={args.triplets}; dimension={args.dimension}; seed={args.seed}")
    print("Synthetic software-test data only; not human evidence.")


if __name__ == "__main__":
    main()
