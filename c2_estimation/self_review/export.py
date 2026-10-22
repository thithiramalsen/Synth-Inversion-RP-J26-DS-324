"""Export researcher rehearsal runs without treating repeated runs as participants."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .server import DEFAULT_DB, VERSION


def export(database, output):
    database, output = Path(database).resolve(), Path(output)
    if output.exists():
        raise ValueError("Choose a new export folder; preserve previous exports")
    with closing(sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)) as db:
        marker = db.execute("SELECT value FROM metadata WHERE key='self_review_version'").fetchone()
        if not marker or marker[0] != VERSION:
            raise ValueError("This is not a researcher self-review database")
        states = [json.loads(row[0]) for row in db.execute("SELECT state FROM sessions")]
    if any(s.get("mode") != "rehearsal" or not s.get("excluded_from_research") for s in states):
        raise ValueError("Non-rehearsal data found; export stopped")
    completed = [s for s in states if s["phase"] == "complete"]
    allowed = ("code", "created", "completed", "assignment", "responses", "feedback", "fingerprint")
    runs = [{**{key: s[key] for key in allowed}, "operator_role": "project_researcher",
             "excluded_from_research": True} for s in completed]
    summary = {
        "purpose": "researcher_self_review", "version": VERSION,
        "independent_participants": 0, "rehearsal_sessions_started": len(states),
        "completed_rehearsal_runs": len(completed), "not_participant_findings": True,
        "group_statistics_computed": False,
        "interpretation": "Developer observations only. Repeated runs by the researcher are not independent participants; do not pool with an approved participant study.",
    }
    output.mkdir(parents=True)
    for name, value in (("self_review_runs.json", runs), ("self_review_summary.json", summary)):
        (output / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Saved {len(completed)} completed researcher rehearsal runs; zero independent participant findings.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    export(args.database, args.output)
