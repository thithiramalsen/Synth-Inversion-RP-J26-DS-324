"""Select a reproducible development triplet set from mean MFCC embeddings."""

from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FEATURES = ROOT / "c1_timbre" / "outputs" / "c1_audio_features.csv"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "development_triplets.csv"
MFCC_COLUMNS = [f"mfcc_{index:02d}" for index in range(1, 14)]
OUTPUT_COLUMNS = [
    "triplet_id",
    "anchor_sample_id",
    "candidate_a_sample_id",
    "candidate_b_sample_id",
    "closer_candidate_by_rank",
    "mfcc_baseline_choice",
    "anchor_to_a_cosine_similarity",
    "anchor_to_b_cosine_similarity",
    "anchor_to_a_mfcc_distance",
    "anchor_to_b_mfcc_distance",
    "selection_seed",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Select C4 anchor/candidate triplets from development MFCC embeddings."
    )
    parser.add_argument("--features", type=Path, default=DEFAULT_FEATURES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--anchors", type=int, default=10)
    parser.add_argument("--seed", type=int, default=324)
    return parser.parse_args()


def percentile_index_bounds(candidate_count: int, low: float, high: float) -> tuple[int, int]:
    start = max(0, math.ceil(low * candidate_count) - 1)
    stop = min(candidate_count - 1, math.ceil(high * candidate_count) - 1)
    if stop < start:
        raise ValueError("Dataset is too small for the requested percentile range")
    return start, stop


def main() -> None:
    args = parse_args()
    if args.anchors < 1:
        raise ValueError("--anchors must be at least 1")
    with args.features.resolve().open(newline="", encoding="utf-8-sig") as feature_file:
        feature_rows = list(csv.DictReader(feature_file))
    if len(feature_rows) < 4:
        raise ValueError("At least four feature rows are required to form development triplets")
    missing_columns = [column for column in ["sample_id", *MFCC_COLUMNS] if column not in feature_rows[0]]
    if missing_columns:
        raise ValueError(f"Feature CSV is missing columns: {', '.join(missing_columns)}")
    if args.anchors > len(feature_rows):
        raise ValueError(f"Requested {args.anchors} anchors from only {len(feature_rows)} samples")

    sample_ids = [row["sample_id"] for row in feature_rows]
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("Feature CSV contains duplicate sample IDs")
    raw_embeddings = np.asarray(
        [[float(row[column]) for column in MFCC_COLUMNS] for row in feature_rows], dtype=np.float64
    )
    feature_mean = raw_embeddings.mean(axis=0)
    feature_std = raw_embeddings.std(axis=0)
    feature_std[feature_std < np.finfo(float).eps] = 1.0
    embeddings = (raw_embeddings - feature_mean) / feature_std
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    embeddings = embeddings / np.maximum(norms, np.finfo(float).eps)

    rng = random.Random(args.seed)
    anchor_indexes = rng.sample(range(len(sample_ids)), args.anchors)
    output_rows = []
    for triplet_number, anchor_index in enumerate(anchor_indexes, start=1):
        similarities = embeddings @ embeddings[anchor_index]
        ranked_indexes = [
            index
            for index in np.argsort(-similarities, kind="stable")
            if index != anchor_index
        ]
        similar_start, similar_stop = percentile_index_bounds(len(ranked_indexes), 0.06, 0.25)
        moderate_start, moderate_stop = percentile_index_bounds(len(ranked_indexes), 0.26, 0.60)
        closer_index = ranked_indexes[rng.randint(similar_start, similar_stop)]
        farther_index = ranked_indexes[rng.randint(moderate_start, moderate_stop)]

        if rng.choice([True, False]):
            candidate_a_index, candidate_b_index = closer_index, farther_index
            closer_candidate = "candidate_a"
        else:
            candidate_a_index, candidate_b_index = farther_index, closer_index
            closer_candidate = "candidate_b"

        distance_a = float(np.linalg.norm(embeddings[anchor_index] - embeddings[candidate_a_index]))
        distance_b = float(np.linalg.norm(embeddings[anchor_index] - embeddings[candidate_b_index]))
        output_rows.append(
            {
                "triplet_id": f"c4_triplet_{triplet_number:03d}",
                "anchor_sample_id": sample_ids[anchor_index],
                "candidate_a_sample_id": sample_ids[candidate_a_index],
                "candidate_b_sample_id": sample_ids[candidate_b_index],
                "closer_candidate_by_rank": closer_candidate,
                "mfcc_baseline_choice": "candidate_a" if distance_a < distance_b else "candidate_b",
                "anchor_to_a_cosine_similarity": f"{similarities[candidate_a_index]:.8f}",
                "anchor_to_b_cosine_similarity": f"{similarities[candidate_b_index]:.8f}",
                "anchor_to_a_mfcc_distance": f"{distance_a:.8f}",
                "anchor_to_b_mfcc_distance": f"{distance_b:.8f}",
                "selection_seed": args.seed,
            }
        )

    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(output_rows)
    print(f"Wrote {len(output_rows)} development triplets to {output_path}")
    for row in output_rows:
        print(
            f"{row['triplet_id']}: {row['anchor_sample_id']} -> "
            f"A={row['candidate_a_sample_id']}, B={row['candidate_b_sample_id']}"
        )


if __name__ == "__main__":
    main()
