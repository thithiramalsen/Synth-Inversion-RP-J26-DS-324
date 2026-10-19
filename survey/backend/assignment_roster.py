"""Private recruitment labels, kept apart from responses and research exports."""
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from database import get_connection


class AssignmentName(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bundle_hash: str = Field(min_length=1, max_length=128)
    assignment_id: str = Field(min_length=1, max_length=128)
    participant_name: str = Field(strict=True, max_length=100)
    expected_version: int = Field(strict=True, ge=0)

    @field_validator("participant_name", mode="before")
    @classmethod
    def clean_name(cls, value):
        if not isinstance(value, str):
            return value
        value = value.strip()
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Use a name or nickname without control characters")
        return value


def initialize_roster_database():
    with get_connection() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS assignment_roster (
                component TEXT NOT NULL, study_id TEXT NOT NULL,
                bundle_hash TEXT NOT NULL, assignment_id TEXT NOT NULL,
                participant_name TEXT NOT NULL DEFAULT '',
                version INTEGER NOT NULL,
                updated_by TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(component,study_id,bundle_hash,assignment_id)
            );
        """)


def _scope(component, bundle, checksum):
    if component not in ("c1", "c4"):
        raise ValueError("Unknown recruitment roster")
    return component, bundle["study_id"], checksum


def reserved_assignments(db, component, bundle, checksum):
    rows = db.execute(
        "SELECT assignment_id FROM assignment_roster "
        "WHERE component=? AND study_id=? AND bundle_hash=? AND participant_name<>''",
        _scope(component, bundle, checksum),
    ).fetchall()
    return {row["assignment_id"] for row in rows}


def _records(db, component, bundle, checksum):
    scope = _scope(component, bundle, checksum)
    names = {row["assignment_id"]: row for row in db.execute(
        "SELECT * FROM assignment_roster WHERE component=? AND study_id=? AND bundle_hash=?", scope
    ).fetchall()}
    # component is restricted above; all user-provided values remain parameters.
    active = {row["assignment_id"]: row for row in db.execute(
        f"SELECT i.assignment_id,s.phase,s.current_index,s.completed_at,s.withdrawn_at,l.listener_number "
        f"FROM {component}_invites i "
        f"LEFT JOIN {component}_sessions s ON s.session_id=i.session_id AND s.bundle_hash=i.bundle_hash "
        f"LEFT JOIN {component}_listener_labels l ON l.session_id=s.session_id "
        "WHERE i.bundle_hash=? AND i.retired_at IS NULL", (checksum,)
    ).fetchall()}
    records = []
    for block in bundle["assignments"]:
        assignment_id = block["assignment_id"]
        entry, session = names.get(assignment_id), active.get(assignment_id)
        status = "missing" if session is None else "issued"
        if session is not None:
            if session["withdrawn_at"]:
                status = "withdrawn"
            elif session["phase"] == "replaced":
                status = "replaced"
            elif session["completed_at"] or session["phase"] == "complete":
                status = "completed"
            elif session["phase"] == "screen_failed":
                status = "screen_failed"
            elif session["phase"]:
                status = "in_progress"
        number = session["listener_number"] if session is not None else None
        records.append(dict(
            assignment_id=assignment_id,
            participant_name=entry["participant_name"] if entry is not None else "",
            version=entry["version"] if entry is not None else 0,
            updated_by=entry["updated_by"] if entry is not None else "",
            updated_at=entry["updated_at"] if entry is not None else None,
            status=status,
            participant_label=f"Listener {number:03d}" if number is not None else None,
            saved_presentations=(session["current_index"] or 0) if session is not None else 0,
        ))
    return records


def roster(component, bundle, checksum):
    with get_connection() as db:
        assignments = _records(db, component, bundle, checksum)
    return dict(bundle_hash=checksum, study_id=bundle["study_id"], assignments=assignments)


def save_name(component, bundle, checksum, body, actor):
    scope = _scope(component, bundle, checksum)
    if body.bundle_hash != checksum:
        raise HTTPException(409, "The study version has changed. Reload the assignment list before saving.")
    if body.assignment_id not in {block["assignment_id"] for block in bundle["assignments"]}:
        raise HTTPException(404, "That assignment is not part of the current study")
    with get_connection() as db:
        # Same transaction lock as invitation claims/regeneration on both databases.
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute(
            "SELECT version FROM assignment_roster "
            "WHERE component=? AND study_id=? AND bundle_hash=? AND assignment_id=?",
            (*scope, body.assignment_id),
        ).fetchone()
        version = previous["version"] if previous is not None else 0
        if version != body.expected_version:
            raise HTTPException(409, "Another researcher updated this assignment. Reload the list and check their change before saving.")
        timestamp = datetime.now(timezone.utc).isoformat()
        if previous is None:
            db.execute("INSERT INTO assignment_roster "
                       "(component,study_id,bundle_hash,assignment_id,participant_name,version,updated_by,updated_at) "
                       "VALUES (?,?,?,?,?,?,?,?)",
                       (*scope, body.assignment_id, body.participant_name, version + 1, actor, timestamp))
        else:
            db.execute("UPDATE assignment_roster SET participant_name=?,version=?,updated_by=?,updated_at=? "
                       "WHERE component=? AND study_id=? AND bundle_hash=? AND assignment_id=?",
                       (body.participant_name, version + 1, actor, timestamp, *scope, body.assignment_id))
        assignment = next(item for item in _records(db, component, bundle, checksum)
                          if item["assignment_id"] == body.assignment_id)
    return dict(bundle_hash=checksum, study_id=bundle["study_id"], assignment=assignment)
