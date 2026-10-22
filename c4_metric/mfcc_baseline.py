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
    parser.add_argument("--allow-synthetic", action="store_true",
                        help="Permit explicitly marked synthetic rows for a software-only check")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with args.triplets.resolve().open(newline="", encoding="utf-8-sig") as triplet_file:
        triplets = {row["triplet_id"]: row for row in csv.DictReader(triplet_file)}
    with args.responses.resolve().open(newline="", encoding="utf-8-sig") as response_file:
        responses = list(csv.DictReader(response_file))
    agreement = []
    skipped_synthetic = 0
    for row in responses:
        is_synthetic = "SYNTHETIC" in row.get("data_status", "")
        if is_synthetic:
            if not args.allow_synthetic:
                skipped_synthetic += 1
                continue
        if row.get("analysis_include", "").strip().casefold() in {"false", "0", "no"} and not is_synthetic:
            continue
        comparison_id = next((row.get(key, "") for key in
                              ("triplet_id", "trial_id", "comparison_id", "question_id")
                              if row.get(key, "")), "")
        if comparison_id not in triplets:
            continue
        triplet = triplets[comparison_id]
        baseline_side = triplet.get("mfcc_baseline_choice", "")
        if baseline_side not in {"candidate_a", "candidate_b"}:
            continue
        baseline_id = triplet.get(f"{baseline_side}_sample_id", "")
        chosen_id = row.get("chosen_sample_id", "") or row.get("selected_candidate_id", "")
        if not chosen_id:
            choice = row.get("choice", "").strip().casefold()
            candidate_a = row.get("candidate_a", row.get("candidate_a_sample_id", ""))
            candidate_b = row.get("candidate_b", row.get("candidate_b_sample_id", ""))
            if choice in {"candidate_a", "a"}:
                chosen_id = candidate_a or triplet.get("candidate_a_sample_id", "")
            elif choice in {"candidate_b", "b"}:
                chosen_id = candidate_b or triplet.get("candidate_b_sample_id", "")
        if chosen_id and baseline_id and chosen_id in {
                triplet.get("candidate_a_sample_id", ""),
                triplet.get("candidate_b_sample_id", ""),
                row.get("candidate_a", ""), row.get("candidate_b", "")}:
            agreement.append(chosen_id == baseline_id)
    if not agreement:
        print("No labeled C4 responses were found in the export.")
        if skipped_synthetic:
            print(f"Skipped {skipped_synthetic} explicitly synthetic rows (use --allow-synthetic only for software checks).")
        return
    correct = sum(agreement)
    print(f"MFCC baseline agreement: {correct}/{len(agreement)} = {correct / len(agreement):.3f}")
    if skipped_synthetic:
        print(f"Skipped {skipped_synthetic} explicitly synthetic rows.")


if __name__ == "__main__":
    main()
