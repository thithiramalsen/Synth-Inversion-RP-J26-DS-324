"""Summarize C4 confidence metadata without changing training data or models."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def analyze(cleaned_responses: Path, output: Path) -> dict[str, Any]:
    rows = read_csv(cleaned_responses)
    levels: Counter[int] = Counter()
    confidence_by_status: dict[int, Counter[str]] = defaultdict(Counter)
    confidence_by_choice: dict[int, Counter[str]] = defaultdict(Counter)
    values: list[int] = []
    missing = invalid = 0
    repeats: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)
    for row in rows:
        raw = row.get("confidence_normalized", "").strip()
        try:
            level = int(raw)
            if level not in range(1, 6):
                raise ValueError
        except (TypeError, ValueError):
            if row.get("confidence_status") == "invalid":
                invalid += 1
            else:
                missing += 1
            continue
        values.append(level)
        levels[level] += 1
        confidence_by_status[level][row.get("vote_status", "unresolved")] += 1
        selected = row.get("selected_candidate_id", "")
        choice = ("candidate_a" if selected and selected == row.get("candidate_a_id") else
                  "candidate_b" if selected and selected == row.get("candidate_b_id") else "uncertain")
        confidence_by_choice[level][choice] += 1
        pair = sorted((row.get("candidate_a_id", ""), row.get("candidate_b_id", "")))
        repeats[(row.get("normalized_participant_id", ""), row.get("anchor_id", ""), *pair)].append(
            row.get("selected_candidate_id", "")
        )

    repeat_groups = [choices for choices in repeats.values() if len(choices) > 1]
    repeated_judgments = sum(map(len, repeat_groups))
    consistent_groups = sum(len(set(choices)) == 1 for choices in repeat_groups)
    confidence_total = len(values)
    result = {
        "source": str(cleaned_responses),
        "response_count": len(rows),
        "confidence_valid_count": confidence_total,
        "confidence_missing_count": missing,
        "confidence_invalid_count": invalid,
        "confidence_scale": {"1": "Not confident", "2-4": "No separate labels specified by the survey",
                             "5": "Very confident"},
        "confidence_level_counts": {
            str(level): {"count": levels[level],
                        "percent_of_valid_ratings": (100 * levels[level] / confidence_total
                                                      if confidence_total else None),
                        "comparison_vote_status": {
                            status: confidence_by_status[level][status]
                            for status in ("preference", "tie", "unresolved")
                        }}
                        | {"participant_choice": {
                            choice: confidence_by_choice[level][choice]
                            for choice in ("candidate_a", "candidate_b", "uncertain")
                        }}
            for level in range(1, 6)
        },
        "mean_confidence": statistics.mean(values) if values else None,
        "median_confidence": statistics.median(values) if values else None,
        "repeat_consistency": {
            "participant_comparable_item_groups_with_repeats": len(repeat_groups),
            "repeated_judgment_responses": repeated_judgments,
            "groups_with_identical_choices": consistent_groups,
            "identical_choice_group_percent": (100 * consistent_groups / len(repeat_groups)
                                               if repeat_groups else None),
            "definition": "same participant, anchor, and unordered candidate pair; choices compared after mapping to sample IDs",
        },
        "interpretation": "Descriptive self-reported confidence only; it is not correctness, a training weight, or a tie breaker.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cleaned_responses", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(analyze(args.cleaned_responses, args.output), indent=2))


if __name__ == "__main__":
    main()
