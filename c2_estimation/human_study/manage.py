"""Local researcher export/withdrawal; no public administration endpoints."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import sqlite3
from statistics import mean

from .design import SEED
from .server import DEFAULT_DB


def summarize(sessions):
    completed = [s for s in sessions if s["phase"] == "complete"]
    paired, comprehension = {}, []
    for metric in ("usefulness", "clarity", "confidence"):
        differences, rows = [], []
        for session in completed:
            groups = {c: [r["answers"][metric] for r in session["responses"] if r["condition"] == c] for c in ("with", "without")}
            numeric = {c: [v for v in values if type(v) is int] for c, values in groups.items()}
            means = {c: mean(v) if v else None for c, v in numeric.items()}
            # Freeze a conservative complete-case paired rule: all four ratings per condition.
            eligible = all(len(values) == 4 for values in numeric.values())
            difference = means["with"] - means["without"] if eligible else None
            if difference is not None:
                differences.append(difference)
            rows.append({"code": session["code"], "means": means,
                         "valid_counts": {c: len(v) for c, v in numeric.items()},
                         "cannot_judge_counts": {c: len(groups[c])-len(numeric[c]) for c in groups},
                         "paired_eligible": eligible, "with_minus_without": difference})
        interval = None
        if len(differences) >= 2:
            rng = random.Random(SEED)
            draws = sorted(mean(rng.choices(differences, k=len(differences))) for _ in range(2000))
            interval = [draws[49], draws[1949]]
        paired[metric] = {"participants": rows, "n_paired_participants": len(differences),
                          "mean_with_minus_without": mean(differences) if differences else None,
                          "exploratory_participant_bootstrap_95_percent": interval}
    for session in completed:
        rows = [r for r in session["responses"] if r["condition"] == "with"]
        comprehension.append({"code": session["code"], "tasks": len(rows),
            "no_perceptual_guarantee_correct": sum(r["answers"]["guarantee"] == "no" for r in rows),
            "low_reliability_not_impossible_correct": sum(r["answers"]["impossible"] == "no" for r in rows),
            "unsure_count": sum(r["answers"][f] == "unsure" for r in rows for f in ("guarantee", "impossible")),
            "open_ended_rubric_status": "requires human coding; not automatically scored"})
    return {"mode": "rehearsal", "not_research_findings": True,
            "enrolments": len(sessions), "completed_participants": len(completed),
            "status_counts": dict(Counter(s["phase"] for s in sessions)),
            "scored_task_observations": sum(len(s["responses"]) for s in completed),
            "analysis_unit": "participant; tasks and controls are repeated observations, not independent participants",
            "interpretation": "Formative only; conditional on eight fixed development cases. Rehearsal responses must never enter the research analysis.",
            "paired_exploratory": paired, "comprehension_with_reliability_only": comprehension,
            "display_preference_counts": dict(Counter(s["feedback"]["preference"] for s in completed))}


def export(database, output):
    if output.exists():
        raise ValueError("Use a fresh export folder; preserve previous exports")
    with sqlite3.connect(f"file:{Path(database).resolve().as_posix()}?mode=ro", uri=True) as db:
        sessions = [json.loads(row[0]) for row in db.execute("SELECT state FROM sessions")]
    if any(s["mode"] != "rehearsal" for s in sessions):
        raise ValueError("This exporter is for rehearsal data only")
    completed = [s for s in sessions if s["phase"] == "complete"]
    response_fields = ("code", "mode", "fingerprint", "consent_version", "slot", "assignment", "experience",
                       "created", "completed", "responses", "feedback", "playback", "excluded_from_research")
    exported = [{k: s[k] for k in response_fields} for s in completed]
    coding = [{"code": s["code"], "case_id": r["case_id"], "position": r["position"],
               "meaning": r["answers"]["meaning"], "coder_1_score": None, "coder_2_score": None,
               "agreed_score": None, "notes": ""} for s in completed for r in s["responses"] if r["condition"] == "with"]
    output.mkdir(parents=True)
    for name, payload in (("completed_rehearsals.json", exported), ("summary.json", summarize(sessions)), ("comprehension_coding.json", coding)):
        (output / name).write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Exported {len(completed)} completed REHEARSALS to {output}. Not research findings.")


def withdraw(database, code):
    with sqlite3.connect(f"file:{Path(database).resolve().as_posix()}?mode=rw", uri=True) as db:
        db.execute("PRAGMA secure_delete=ON")
        db.execute("BEGIN IMMEDIATE")
        found = db.execute("SELECT state FROM sessions WHERE code=?", (code,)).fetchone()
        if not found:
            raise ValueError("Unknown code; no changes")
        state = json.loads(found[0])
        for field in ("experience", "practice_response", "feedback"):
            state.pop(field, None)
        state.update(phase="withdrawn", withdrawn=datetime.now(timezone.utc).isoformat(),
                     responses=[], headphone_answers=[], playback={}, revision=state["revision"]+1)
        db.execute("UPDATE sessions SET state=? WHERE code=?", (json.dumps(state), code))
    print("Linked answers removed from active local storage; minimal consent/withdrawal audit retained. Update any prior exports/backups separately.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    commands = parser.add_subparsers(dest="command", required=True)
    export_args = commands.add_parser("export")
    export_args.add_argument("--output", type=Path, required=True)
    withdraw_args = commands.add_parser("withdraw")
    withdraw_args.add_argument("--code", required=True)
    args = parser.parse_args()
    if args.command == "export":
        export(args.database, args.output)
    else:
        withdraw(args.database, args.code)
