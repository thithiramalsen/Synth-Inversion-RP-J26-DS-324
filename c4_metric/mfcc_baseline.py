"""Compare exported human C4 choices with the frozen MFCC baseline choices."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRIPLETS = Path(__file__).resolve().parent / "development_triplets.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calculate MFCC baseline agreement on C4 survey exports.")
    parser.add_argument("responses", type=Path, help="CSV exported from /api/admin/export/c4_triplets")
    parser.add_argument("--triplets", type=Path, default=DEFAULT_TRIPLETS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with args.triplets.resolve().open(newline="", encoding="utf-8-sig") as triplet_file:
        triplets = {row["triplet_id"]: row for row in csv.DictReader(triplet_file)}
    with args.responses.resolve().open(newline="", encoding="utf-8-sig") as response_file:
        responses = list(csv.DictReader(response_file))
    labeled = [row for row in responses if row.get("trial_id") in triplets and row.get("choice")]
    if not labeled:
        print("No labeled C4 responses were found in the export.")
        return
    correct = sum(
        row["choice"] == triplets[row["trial_id"]]["mfcc_baseline_choice"]
        for row in labeled
    )
    print(f"MFCC baseline agreement: {correct}/{len(labeled)} = {correct / len(labeled):.3f}")


if __name__ == "__main__":
    main()
