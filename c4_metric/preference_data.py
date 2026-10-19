"""Validate C4 survey CSVs and preserve both individual and aggregated votes."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "data/raw/corpus_v4/manifest.csv"
DEFAULT_OUTPUT = ROOT / "c4_metric/outputs/responses"
SYNTHETIC_MARK = "SYNTHETIC_DO_NOT_USE_AS_HUMAN_EVIDENCE"
DEFAULT_ALIASES = {
    "participant_id": ["participant_id", "participant_label", "listener_id"],
    "comparison_id": ["comparison_id", "triplet_id", "trial_id", "question_id"],
    "presentation_id": ["presentation_id", "response_id", "trial_id"],
    "anchor_id": ["anchor_id", "reference", "reference_sample_id", "target_id", "anchor_sample_id"],
    "candidate_a_id": ["candidate_a_id", "candidate_a", "candidate_b_id", "candidate_a_sample_id", "b_id"],
    "candidate_b_id": ["candidate_b_id", "candidate_b", "candidate_c_id", "candidate_b_sample_id", "c_id"],
    "choice": ["choice", "selected_candidate", "selected", "answer"],
    "chosen_id": ["chosen_sample_id", "chosen_id", "preferred_candidate_id"],
    "confidence": ["confidence", "confidence_1_to_5"],
    "analysis_include": ["analysis_include"],
    "data_status": ["data_status"],
}
DEFAULT_CHOICE_VALUES = {
    "candidate_a": "candidate_a", "a": "candidate_a",
    "candidate_b": "candidate_b", "b": "candidate_b",
    "cannot_decide": "uncertain", "i_cannot_decide": "uncertain", "uncertain": "uncertain",
    "no_preference": "uncertain",
}


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("Input CSV needs a header row")
        return list(reader.fieldnames), list(reader)


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def find_column(row: dict[str, str], aliases: list[str]) -> str | None:
    return next((name for name in aliases if name in row), None)


def load_sample_ids(manifest_path: Path) -> set[str]:
    _, rows = read_rows(manifest_path)
    if not rows or "sample_id" not in rows[0]:
        raise ValueError("Audio manifest must contain sample_id")
    ids = {row["sample_id"].strip() for row in rows if row.get("sample_id", "").strip()}
    if len(ids) != len(rows):
        raise ValueError("Audio manifest contains blank or duplicate sample IDs")
    return ids


def _bool_value(value: str) -> bool | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip().casefold()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    return None


def normalize_responses(input_path: Path, manifest_path: Path, output_dir: Path, *,
                        mapping_path: Path | None = None, allow_synthetic: bool = False,
                        minimum_agreement: float = 0.67) -> dict[str, Any]:
    """Validate rows; emit normalized individual choices and vote aggregates.

    Disagreement remains in ``cleaned_responses.csv`` and individual preference
    triplets. Aggregate ties are explicitly retained as ties. Uncertainty is
    counted separately and never turned into a forced preference.
    """
    if not 0.5 <= minimum_agreement <= 1.0:
        raise ValueError("minimum_agreement must be between 0.5 and 1.0")
    columns, raw_rows = read_rows(input_path)
    if not raw_rows:
        raise ValueError("Response CSV has a header but contains no response rows")
    aliases = DEFAULT_ALIASES.copy()
    choice_values = DEFAULT_CHOICE_VALUES.copy()
    if mapping_path:
        config = json.loads(mapping_path.read_text(encoding="utf-8"))
        for field, names in config.get("columns", {}).items():
            if field not in aliases or not isinstance(names, list):
                raise ValueError(f"Invalid column mapping for {field}")
            aliases[field] = names
        for token, destination in config.get("choice_values", {}).items():
            destination = str(destination).casefold()
            if destination not in {"candidate_a", "candidate_b", "uncertain"}:
                raise ValueError(f"Invalid choice destination for {token}")
            choice_values[str(token).strip().casefold().replace(" ", "_")] = destination
    sample_ids = load_sample_ids(manifest_path)
    rejected: list[dict[str, Any]] = []
    cleaned: list[dict[str, Any]] = []
    preferences: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    values_by_field = {field: find_column(raw_rows[0], choices) if raw_rows else None
                       for field, choices in aliases.items()}
    synthetic_kinds = {str(raw.get(values_by_field["data_status"] or "", "")).strip() == SYNTHETIC_MARK
                       for raw in raw_rows}
    if len(synthetic_kinds) > 1:
        raise ValueError("Do not combine synthetic and human survey rows in one processing run")
    for line_number, raw in enumerate(raw_rows, start=2):
        status = str(raw.get(values_by_field["data_status"] or "", "")).strip()
        synthetic = status == SYNTHETIC_MARK
        reason = None
        if synthetic and not allow_synthetic:
            reason = "synthetic_row_requires_explicit_allow_synthetic"
        participant = str(raw.get(values_by_field["participant_id"] or "", "")).strip()
        comparison = str(raw.get(values_by_field["comparison_id"] or "", "")).strip()
        presentation = str(raw.get(values_by_field["presentation_id"] or "", "")).strip()
        anchor = str(raw.get(values_by_field["anchor_id"] or "", "")).strip()
        candidate_a = str(raw.get(values_by_field["candidate_a_id"] or "", "")).strip()
        candidate_b = str(raw.get(values_by_field["candidate_b_id"] or "", "")).strip()
        choice_col = values_by_field["choice"]
        choice = str(raw.get(choice_col or "", "")).strip().casefold().replace(" ", "_")
        chosen_col = values_by_field["chosen_id"]
        explicit_chosen = str(raw.get(chosen_col or "", "")).strip()
        confidence_col = values_by_field["confidence"]
        confidence_text = str(raw.get(confidence_col or "", "")).strip()
        confidence: int | None = None
        if not reason and (not participant or not comparison or not anchor or not candidate_a or not candidate_b):
            reason = "missing_required_identity_or_audio_id"
        elif not reason and (candidate_a == candidate_b or anchor in {candidate_a, candidate_b}):
            reason = "triplet_audio_ids_must_be_distinct"
        elif not reason and any(x not in sample_ids for x in (anchor, candidate_a, candidate_b)):
            reason = "audio_id_not_found_in_manifest"
        answer_key = presentation or comparison
        duplicate_key = (participant, answer_key)
        if not reason and duplicate_key in seen:
            reason = "duplicate_participant_presentation"
        if confidence_text:
            try:
                confidence = int(confidence_text)
            except ValueError:
                reason = reason or "confidence_not_integer_1_to_5"
            if confidence is not None and confidence not in range(1, 6):
                reason = reason or "confidence_not_integer_1_to_5"
        if not reason:
            route = choice_values.get(choice)
            if choice in {candidate_a.casefold(), candidate_b.casefold()}:
                route = "candidate_a" if choice == candidate_a.casefold() else "candidate_b"
            if choice and route is None:
                reason = "choice_not_a_valid_candidate_or_uncertainty"
            uncertainty = route == "uncertain" or (not choice and not explicit_chosen)
            selected = explicit_chosen
            if not selected and not uncertainty:
                if route in {"candidate_a", "candidate_b"}:
                    selected = candidate_a if route == "candidate_a" else candidate_b
                else:
                    reason = "choice_not_a_valid_candidate_or_uncertainty"
            if selected and selected not in {candidate_a, candidate_b}:
                reason = "chosen_sample_id_does_not_match_presented_candidates"
            elif selected and route in {"candidate_a", "candidate_b"}:
                expected_selected = candidate_a if route == "candidate_a" else candidate_b
                if selected != expected_selected:
                    reason = "choice_and_chosen_sample_id_conflict"
            if not reason and uncertainty and selected:
                reason = "uncertainty_response_must_not_select_candidate"
            if not reason and not uncertainty and not selected:
                reason = "missing_selected_candidate"
            if not reason and uncertainty and confidence is not None:
                reason = "uncertainty_response_must_not_have_confidence"
            include_col = values_by_field["analysis_include"]
            include = _bool_value(raw.get(include_col or "", ""))
            # Synthetic rehearsal rows are deliberately marked excluded; explicit
            # opt-in permits pipeline exercise while retaining their synthetic mark.
            if not reason and include is False and not (synthetic and allow_synthetic):
                reason = "analysis_excluded"
        if reason:
            rejected.append({"source_row": line_number, "reason": reason,
                             "raw_row_json": json.dumps(raw, ensure_ascii=False, sort_keys=True)})
            continue
        seen.add(duplicate_key)
        uncertainty = (choice_values.get(choice) == "uncertain"
                       or (not choice and not explicit_chosen))
        respondent = {
            **raw,
            "normalized_participant_id": participant,
            "comparison_id": comparison,
            "presentation_id": presentation or comparison,
            "anchor_id": anchor,
            "candidate_a_id": candidate_a,
            "candidate_b_id": candidate_b,
            "selected_candidate_id": "" if uncertainty else selected,
            "confidence_normalized": "" if confidence is None else confidence,
            "uncertain": str(uncertainty).lower(),
            "data_status_normalized": SYNTHETIC_MARK if synthetic else "human_response",
        }
        cleaned.append(respondent)
        if not uncertainty:
            negative = candidate_b if selected == candidate_a else candidate_a
            preferences.append({
                "data_status": SYNTHETIC_MARK if synthetic else "human_response",
                "participant_id": participant,
                "comparison_id": comparison,
                "presentation_id": presentation or comparison,
                "anchor_id": anchor,
                "positive_id": selected,
                "negative_id": negative,
                "confidence": "" if confidence is None else confidence,
                **{key: raw.get(key, "") for key in
                   ("case_type", "comparison_type", "hard_case_type", "metric_disagreement",
                    "near_tie", "parameter_far_audio_close", "locally_sensitive") if key in raw},
            })

    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    uncertainty_counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for row in cleaned:
        pair = sorted([row["candidate_a_id"], row["candidate_b_id"]])
        key = (row["anchor_id"], pair[0], pair[1])
        if key not in grouped:
            grouped[key] = {"first_candidate_id": pair[0], "second_candidate_id": pair[1],
                            "anchor_id": key[0], "votes_first": 0, "votes_second": 0,
                            "uncertain_count": 0, "comparison_ids": set(), "participants": set(),
                            "data_status": row["data_status_normalized"]}
        item = grouped[key]
        item["comparison_ids"].add(row["comparison_id"])
        item["participants"].add(row["normalized_participant_id"])
        if row["uncertain"] == "true":
            item["uncertain_count"] += 1
        elif row["selected_candidate_id"] == pair[0]:
            item["votes_first"] += 1
        else:
            item["votes_second"] += 1
    aggregates = []
    for item in grouped.values():
        decisive = item["votes_first"] + item["votes_second"]
        agreement = max(item["votes_first"], item["votes_second"]) / decisive if decisive else ""
        if not decisive or item["votes_first"] == item["votes_second"]:
            winner = "tie" if decisive else "no_decisive_votes"
        else:
            winner = item["first_candidate_id"] if item["votes_first"] > item["votes_second"] else item["second_candidate_id"]
        aggregates.append({
            "data_status": item["data_status"], "anchor_id": item["anchor_id"],
            "first_candidate_id": item["first_candidate_id"], "second_candidate_id": item["second_candidate_id"],
            "votes_first": item["votes_first"], "votes_second": item["votes_second"],
            "uncertain_count": item["uncertain_count"], "agreement": agreement,
            "majority_winner": winner,
            "meets_minimum_agreement": bool(decisive and agreement != "" and agreement >= minimum_agreement),
            "participant_count": len(item["participants"]),
            "comparison_ids": "|".join(sorted(item["comparison_ids"])),
        })
    output_dir.mkdir(parents=True, exist_ok=True)
    clean_fields = list(dict.fromkeys(columns + [
        "normalized_participant_id", "comparison_id", "presentation_id", "anchor_id",
        "candidate_a_id", "candidate_b_id", "selected_candidate_id", "confidence_normalized",
        "uncertain", "data_status_normalized",
    ]))
    preference_fields = ["data_status", "participant_id", "comparison_id", "presentation_id",
                         "anchor_id", "positive_id", "negative_id", "confidence"]
    preference_fields.extend(key for key in ("case_type", "comparison_type", "hard_case_type",
                                              "metric_disagreement", "near_tie",
                                              "parameter_far_audio_close", "locally_sensitive")
                             if any(key in row for row in preferences))
    aggregate_fields = ["data_status", "anchor_id", "first_candidate_id", "second_candidate_id",
                        "votes_first", "votes_second", "uncertain_count", "agreement", "majority_winner",
                        "meets_minimum_agreement", "participant_count", "comparison_ids"]
    write_csv(output_dir / "cleaned_responses.csv", cleaned, clean_fields)
    write_csv(output_dir / "rejected_responses.csv", rejected, ["source_row", "reason", "raw_row_json"])
    write_csv(output_dir / "preference_triplets.csv", preferences, preference_fields)
    write_csv(output_dir / "aggregate_preferences.csv", aggregates, aggregate_fields)
    synthetic = any(r["data_status_normalized"] == SYNTHETIC_MARK for r in cleaned)
    summary = {
        "data_status": SYNTHETIC_MARK if synthetic else "human_response_or_empty",
        "input_file": str(input_path), "manifest": str(manifest_path),
        "input_rows": len(raw_rows), "valid_rows": len(cleaned), "rejected_rows": len(rejected),
        "preference_triplets": len(preferences), "uncertain_rows": sum(r["uncertain"] == "true" for r in cleaned),
        "aggregate_comparisons": len(aggregates), "ties_preserved": sum(r["majority_winner"] == "tie" for r in aggregates),
        "minimum_agreement": minimum_agreement,
        "analysis_include": False if synthetic else True,
        "note": "Individual disagreement is preserved; aggregate ties and uncertainty are not forced into labels.",
    }
    (output_dir / "quality_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("responses", type=Path)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--mapping", type=Path, help="JSON field alias configuration")
    parser.add_argument("--allow-synthetic", action="store_true", help="Allow marked dummy rows for software checks")
    parser.add_argument("--minimum-agreement", type=float, default=0.67)
    args = parser.parse_args()
    print(json.dumps(normalize_responses(args.responses, args.manifest, args.output_dir,
                                         mapping_path=args.mapping,
                                         allow_synthetic=args.allow_synthetic,
                                         minimum_agreement=args.minimum_agreement), indent=2))


if __name__ == "__main__":
    main()
