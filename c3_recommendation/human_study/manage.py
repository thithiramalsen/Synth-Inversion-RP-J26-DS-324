"""Local researcher export and withdrawal for the C3 rehearsal; no public admin endpoints.

Usage (repository root):
    python -B -m c3_recommendation.human_study.manage export --output data/processed/c3_v4/human_study_rehearsal_v2_export_v1
    python -B -m c3_recommendation.human_study.manage analyze --output data/processed/c3_v4/human_study_rehearsal_v2_analysis_v1
    python -B -m c3_recommendation.human_study.manage analyze --simulate 12 --effect 0 --output data/processed/c3_v4/human_study_simulated_check_v1
    python -B -m c3_recommendation.human_study.manage withdraw --code C3-R-EXACTCODE
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from .analysis import analyze, chosen_method, simulate_sessions
from .design import N_SCORED, SEED, SET_QUESTIONS
from .server import DEFAULT_BUNDLE, DEFAULT_DB

BOOTSTRAP_DRAWS = 2000


def bootstrap(values: list[float]):
    """Exploratory participant-level percentile interval (2,000 draws, fixed seed)."""
    if len(values) < 2:
        return None
    rng = random.Random(SEED)
    draws = sorted(mean(rng.choices(values, k=len(values))) for _ in range(BOOTSTRAP_DRAWS))
    return [draws[int(0.025 * BOOTSTRAP_DRAWS) - 1], draws[int(0.975 * BOOTSTRAP_DRAWS) - 1]]


def summarize(sessions: list[dict]) -> dict:
    completed = [s for s in sessions if s["phase"] == "complete"]
    preference = {}
    for question in SET_QUESTIONS:
        rows, shares = [], []
        for session in completed:
            counts = Counter(chosen_method(r["answers"][question], r["set_a"]) for r in session["responses"])
            decisive = counts["mmr"] + counts["topk"]
            share = counts["mmr"] / decisive if decisive else None
            if share is not None:
                shares.append(share)
            rows.append({"code": session["code"], "counts": dict(counts), "c3_share_of_decisive": share})
        preference[question] = {
            "participants": rows, "n_participants_with_decisive_answers": len(shares),
            "mean_c3_share_of_decisive": mean(shares) if shares else None,
            "exploratory_participant_bootstrap_95_percent": bootstrap(shares),
            "note": "0.5 = no preference between methods; ties and Cannot judge are reported in counts, not dropped silently",
        }
    closeness_rows, differences = [], []
    for session in completed:
        by_group = {"mmr_only": [], "topk_only": [], "both": []}
        cannot = Counter()
        for r in session["responses"]:
            for number, rating in r["answers"]["closeness"].items():
                group = r["membership"][number]
                if type(rating) is int:
                    by_group[group].append(rating)
                else:
                    cannot[group] += 1
        means = {g: mean(v) if v else None for g, v in by_group.items()}
        difference = (means["mmr_only"] - means["topk_only"]
                      if means["mmr_only"] is not None and means["topk_only"] is not None else None)
        if difference is not None:
            differences.append(difference)
        closeness_rows.append({"code": session["code"], "means": means,
                               "valid_counts": {g: len(v) for g, v in by_group.items()},
                               "cannot_judge_counts": dict(cannot), "c3_only_minus_topk_only": difference})
    return {
        "mode": "rehearsal", "not_research_findings": True,
        "enrolments": len(sessions), "completed_participants": len(completed),
        "status_counts": dict(Counter(s["phase"] for s in sessions)),
        "scored_case_observations": sum(len(s["responses"]) for s in completed),
        "analysis_unit": "participant; cases and sounds are repeated observations, not independent participants",
        "interpretation": (f"Formative only; conditional on {N_SCORED} fixed validation cases and the Phase 7 operating "
                           "point. Rehearsal responses must never enter the research analysis."),
        "set_preference": preference,
        "closeness": {"participants": closeness_rows, "n_paired_participants": len(differences),
                      "mean_c3_only_minus_topk_only": mean(differences) if differences else None,
                      "exploratory_participant_bootstrap_95_percent": bootstrap(differences)},
        "knob_bar_usefulness_counts": dict(Counter(str(s["feedback"]["knob_bars"]) for s in completed)),
        "length_counts": dict(Counter(s["feedback"]["length"] for s in completed)),
    }


def read_sessions(database: Path) -> list[dict]:
    with sqlite3.connect(f"file:{Path(database).resolve().as_posix()}?mode=ro", uri=True) as db:
        return [json.loads(row[0]) for row in db.execute("SELECT state FROM sessions")]


def export(database: Path, output: Path) -> None:
    if output.exists():
        raise ValueError("Use a fresh export folder; preserve previous exports")
    sessions = read_sessions(database)
    if any(s["mode"] != "rehearsal" for s in sessions):
        raise ValueError("This exporter is for rehearsal data only")
    completed = [s for s in sessions if s["phase"] == "complete"]
    fields = ("code", "mode", "fingerprint", "consent_version", "slot", "assignment", "experience",
              "created", "completed", "responses", "feedback", "playback", "excluded_from_research")
    reasons = [{"code": s["code"], "case_id": r["case_id"], "position": r["position"], "reason": r["answers"]["reason"]}
               for s in completed for r in s["responses"] if r["answers"]["reason"].strip()]
    output.mkdir(parents=True)
    for name, payload in (("completed_rehearsals.json", [{k: s[k] for k in fields} for s in completed]),
                          ("summary.json", summarize(sessions)),
                          ("free_text_reasons.json", reasons)):
        (output / name).write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Exported {len(completed)} completed REHEARSALS to {output}. Not research findings.")


def withdraw(database: Path, code: str) -> None:
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
                     responses=[], headphone_answers=[], playback={}, revision=state["revision"] + 1)
        db.execute("UPDATE sessions SET state=? WHERE code=?", (json.dumps(state), code))
    print("Linked answers removed from active local storage; minimal consent/withdrawal audit retained. "
          "Update any prior exports/backups separately.")


def run_analysis(database: Path, bundle_dir: Path, output: Path, simulate: int | None, effect: float) -> None:
    """Perceptual closeness evaluation on rehearsal responses, or on simulated sessions."""
    bundle = json.loads((Path(bundle_dir) / "bundle.json").read_text(encoding="utf-8"))
    if simulate:
        sessions, mode = simulate_sessions(bundle, simulate, effect), "simulated"
    else:
        sessions, mode = read_sessions(database), "rehearsal"
        if any(s["mode"] != "rehearsal" for s in sessions):
            raise ValueError("This analysis accepts rehearsal data only while research collection is disabled")
    result = analyze(sessions, bundle, output, mode)
    p = result["primary"]
    print(f"[{mode.upper()}] {result['completed_participants']} participants; C3-only minus top-k-only "
          f"closeness = {p['mean'] if p['mean'] is None else round(p['mean'], 3)} CI {p['ci95']} -> {p['decision']}")
    print(f"Report: {Path(output) / 'REPORT.md'}" + ("  (simulated: not a result)" if simulate else ""))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("export").add_argument("--output", type=Path, required=True)
    analyze_args = commands.add_parser("analyze")
    analyze_args.add_argument("--output", type=Path, required=True)
    analyze_args.add_argument("--simulate", type=int, default=None, help="number of simulated participants (software check)")
    analyze_args.add_argument("--effect", type=float, default=0.0, help="simulated C3-only rating shift in points")
    commands.add_parser("withdraw").add_argument("--code", required=True)
    args = parser.parse_args()
    if args.command == "export":
        export(args.database, args.output)
    elif args.command == "analyze":
        run_analysis(args.database, args.bundle, args.output, args.simulate, args.effect)
    else:
        withdraw(args.database, args.code)
