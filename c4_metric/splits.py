"""Create deterministic leakage-safe C4 preference-triplet splits."""
from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}
        self.rank: dict[str, int] = {}

    def find(self, item: str) -> str:
        if item not in self.parent:
            self.parent[item] = item
            self.rank[item] = 0
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1


def create_splits(input_path: Path, output_path: Path, summary_path: Path, *,
                  seed: int = 20261014, ratios: tuple[float, float, float] = (0.7, 0.15, 0.15)) -> dict:
    if len(ratios) != 3 or any(r <= 0 for r in ratios) or abs(sum(ratios) - 1) > 1e-8:
        raise ValueError("Split ratios must be three positive values summing to 1")
    with input_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    required = {"anchor_id", "positive_id", "negative_id"}
    if not rows or not required.issubset(fields):
        raise ValueError(f"Input triplets must be nonempty and contain {sorted(required)}")
    input_row_count = len(rows)
    excluded = {"tie": 0, "unresolved": 0}
    training_rows = []
    for row in rows:
        status = row.get("vote_status", "preference") or "preference"
        if status in excluded:
            excluded[status] += 1
            continue
        if status not in {"preference", "majority", ""}:
            raise ValueError(f"Unknown vote_status {status!r}; refusing ambiguous training data")
        training_rows.append(row)
    if not training_rows:
        raise ValueError("No unambiguous preference rows remain after excluding ties and unresolved comparisons")
    rows = training_rows
    synthetic_flags = {"SYNTHETIC" in row.get("data_status", "") for row in rows}
    if len(synthetic_flags) > 1:
        raise ValueError("Do not mix synthetic and human preference rows in a split run")
    union = UnionFind()
    row_audio: list[set[str]] = []
    for index, row in enumerate(rows):
        ids = {row[k].strip() for k in required}
        if "" in ids or len(ids) != 3:
            raise ValueError(f"Invalid audio identities in preference row {index + 2}")
        row_audio.append(ids)
        ids_list = sorted(ids)
        for sid in ids_list[1:]:
            union.union(ids_list[0], sid)
    groups: dict[str, list[int]] = defaultdict(list)
    for index, ids in enumerate(row_audio):
        group = union.find(next(iter(ids)))
        groups[group].append(index)
    if len(groups) < 3:
        raise ValueError("Need at least three audio-identity components for train/validation/test splits")
    rng = random.Random(seed)
    components = list(groups.values())
    rng.shuffle(components)
    components.sort(key=len, reverse=True)
    split_names = ("train", "validation", "test")
    targets = [len(rows) * ratio for ratio in ratios]
    counts = [0, 0, 0]
    assigned: dict[int, str] = {}
    for component in components:
        # Pick the split most below its target; seeded tie-breaking comes from order.
        scores = [(counts[i] + len(component)) / targets[i] for i in range(3)]
        chosen = min(range(3), key=lambda i: scores[i])
        for row_index in component:
            assigned[row_index] = split_names[chosen]
        counts[chosen] += len(component)
    if any(not any(split == name for split in assigned.values()) for name in split_names):
        raise ValueError("A split is empty; reduce grouping connectivity or use more independent audio identities")
    # Confidence remains in response artifacts for analysis, but is deliberately
    # removed from the model-facing split manifest.
    output_fields = [field for field in fields
                     if field not in {"confidence", "confidence_normalized", "confidence_status"}]
    output_rows = [{key: value for key, value in row.items() if key in output_fields} |
                   {"split": assigned[i]} for i, row in enumerate(rows)]
    split_audio = {name: set() for name in split_names}
    split_anchors = {name: set() for name in split_names}
    split_participants = {name: set() for name in split_names}
    split_comparisons = {name: set() for name in split_names}
    for index, row in enumerate(rows):
        name = assigned[index]
        split_audio[name].update(row_audio[index])
        split_anchors[name].add(row["anchor_id"])
        if row.get("participant_id"):
            split_participants[name].add(row["participant_id"])
        if row.get("comparison_id"):
            split_comparisons[name].add(row["comparison_id"])
    for i, left in enumerate(split_names):
        for right in split_names[i + 1:]:
            overlap = split_audio[left] & split_audio[right]
            if overlap:
                raise AssertionError(f"Audio identity leakage between {left}/{right}: {len(overlap)}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_fields + ["split"])
        writer.writeheader()
        writer.writerows(output_rows)
    summary = {
        "data_status": ("SYNTHETIC_DO_NOT_USE_AS_HUMAN_EVIDENCE"
                        if any("SYNTHETIC" in row.get("data_status", "") for row in rows)
                        else "human_response_or_unknown"),
        "seed": seed, "ratios": dict(zip(split_names, ratios)),
        "input_rows": len(rows), "audio_identity_components": len(groups),
        "grouping": "connected components over anchor, positive, and negative sample IDs",
        "splits": {name: {"records": counts[i], "unique_anchors": len(split_anchors[name]),
                           "unique_comparisons": len(split_comparisons[name]),
                           "unique_audio_ids": len(split_audio[name]),
                           "unique_participants": len(split_participants[name])}
                   for i, name in enumerate(split_names)},
        "cross_split_audio_overlap": 0,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("triplets", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "c4_metric/outputs/splits/split_manifest.csv")
    parser.add_argument("--summary", type=Path, default=ROOT / "c4_metric/outputs/splits/split_summary.json")
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--train", type=float, default=.70)
    parser.add_argument("--validation", type=float, default=.15)
    parser.add_argument("--test", type=float, default=.15)
    args = parser.parse_args()
    print(json.dumps(create_splits(args.triplets, args.output, args.summary, seed=args.seed,
                                   ratios=(args.train, args.validation, args.test)), indent=2))


if __name__ == "__main__":
    main()
