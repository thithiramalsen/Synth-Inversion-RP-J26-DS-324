"""Validate and prepare a clearly marked C4 rehearsal-pilot response export."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from c4_metric.cache_mfcc_embeddings import _audio_for_row, _manifest_rows, read_csv, sha256_file
from c4_metric.mfcc26 import SAMPLE_RATE

PILOT_MARK = "REHEARSAL_PILOT_DO_NOT_USE_AS_VALIDATED_HUMAN_STUDY_RESULTS"


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def prepare(responses: Path, manifest: Path, output_dir: Path, *,
            pilot_rehearsal: bool = False) -> dict[str, Any]:
    if not pilot_rehearsal:
        raise ValueError("This processor is restricted to explicit rehearsal-pilot preparation")
    fields, source_rows = read_csv(responses)
    required = {"participant_id", "session_id", "triplet_id", "reference", "candidate_a",
                "candidate_b", "choice", "chosen_sample_id", "phase", "analysis_include",
                "data_origin", "session_type"}
    missing_fields = sorted(required - set(fields))
    if missing_fields:
        raise ValueError(f"Response export is missing required fields: {missing_fields}")
    _, _, manifest_by_id = _manifest_rows(manifest)
    audio_fields = {"audio_path", "audio_path_text", "raw_audio_path"}
    if not audio_fields.intersection(manifest_by_id[next(iter(manifest_by_id))]):
        raise ValueError("Manifest does not provide a supported audio path")

    processed: list[dict[str, Any]] = []
    triplets: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    accepted_audio_ids: set[str] = set()
    validated_audio_ids: set[str] = set()
    seen_presentation_keys: set[tuple[str, str]] = set()
    for line, source in enumerate(source_rows, start=2):
        reason = ""
        phase = (source.get("phase") or "").strip().casefold()
        choice = (source.get("choice") or "").strip().casefold()
        anchor = (source.get("reference") or "").strip()
        candidate_a = (source.get("candidate_a") or "").strip()
        candidate_b = (source.get("candidate_b") or "").strip()
        participant = (source.get("participant_id") or "").strip()
        session = (source.get("session_id") or "").strip()
        triplet_id = (source.get("triplet_id") or "").strip()
        presentation_id = (source.get("presentation_id") or triplet_id).strip()
        chosen = (source.get("chosen_sample_id") or "").strip()
        ids = (anchor, candidate_a, candidate_b)
        expected = candidate_a if choice == "candidate_a" else candidate_b
        key = (participant, presentation_id)

        if phase != "complete":
            reason = "incomplete_response"
        elif choice not in {"candidate_a", "candidate_b"}:
            reason = "choice_not_explicit_candidate"
        elif not all((participant, session, triplet_id, presentation_id, *ids)):
            reason = "missing_required_identity_or_audio_id"
        elif len(set(ids)) != 3:
            reason = "audio_ids_not_distinct"
        elif chosen != expected:
            reason = "choice_and_chosen_sample_id_conflict"
        elif any(sample_id not in manifest_by_id for sample_id in ids):
            reason = "audio_id_not_found_in_manifest"
        elif key in seen_presentation_keys:
            reason = "duplicate_participant_presentation"
        else:
            try:
                for sample_id in ids:
                    if sample_id not in validated_audio_ids:
                        audio, rate = _audio_for_row(manifest_by_id[sample_id], sample_id)
                        if rate != SAMPLE_RATE or audio.ndim != 1 or not len(audio):
                            raise ValueError(f"Invalid C3-compatible audio for {sample_id}")
                        validated_audio_ids.add(sample_id)
                    accepted_audio_ids.add(sample_id)
            except Exception as error:
                reason = "audio_missing_or_unloadable"

        usable = not reason
        if reason:
            reasons[reason] += 1
        else:
            seen_presentation_keys.add(key)
            negative = candidate_b if chosen == candidate_a else candidate_a
            triplets.append({
                "data_status": PILOT_MARK,
                "comparison_ids": triplet_id,
                "comparison_id": triplet_id,
                "presentation_id": presentation_id,
                "participant_id": participant,
                "session_id": session,
                "anchor_id": anchor,
                "positive_id": chosen,
                "negative_id": negative,
                "vote_status": "preference",
            })
        processed.append({**source, "pipeline_triplet_usable": usable,
                          "pipeline_triplet_rejection_reason": reason})

    output_dir.mkdir(parents=True, exist_ok=False)
    processed_path = output_dir / "processed_rehearsal_responses.csv"
    triplets_path = output_dir / "pilot_preference_triplets.csv"
    validation_path = output_dir / "validation_report.json"
    _write_csv(processed_path, processed, fields + ["pipeline_triplet_usable",
                                                    "pipeline_triplet_rejection_reason"])
    triplet_fields = ["data_status", "comparison_ids", "comparison_id", "presentation_id",
                      "participant_id", "session_id", "anchor_id", "positive_id",
                      "negative_id", "vote_status"]
    _write_csv(triplets_path, triplets, triplet_fields)
    analysis_values = Counter((row.get("analysis_include") or "").strip() for row in source_rows)
    data_origins = Counter((row.get("data_origin") or "").strip() for row in source_rows)
    report = {
        "data_status": PILOT_MARK,
        "input_file": str(responses.resolve()),
        "input_sha256": sha256_file(responses),
        "manifest_file": str(manifest.resolve()),
        "manifest_sha256": sha256_file(manifest),
        "total_rows": len(source_rows),
        "accepted_rows": len(triplets),
        "rejected_rows": len(source_rows) - len(triplets),
        "exclusions_by_reason": dict(sorted(reasons.items())),
        "analysis_include_original_values_preserved": dict(analysis_values),
        "data_origin_values": dict(data_origins),
        "unique_audio_files_loaded": len(accepted_audio_ids),
        "audio_sample_rate_required": SAMPLE_RATE,
        "audio_validation": "Every accepted triplet's three audio files loaded through the C3-compatible audio path.",
        "processed_csv": str(processed_path.resolve()),
        "pilot_triplets_csv": str(triplets_path.resolve()),
        "research_note": "Researcher rehearsal data only; not validated human-study evidence.",
    }
    validation_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["validation_report"] = str(validation_path.resolve())
    validation_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("responses", type=Path)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/raw/corpus_v4/manifest.csv")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pilot-rehearsal", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(args.responses, args.manifest, args.output_dir,
                             pilot_rehearsal=args.pilot_rehearsal), indent=2))


if __name__ == "__main__":
    main()
