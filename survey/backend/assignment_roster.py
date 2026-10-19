"""Private recruitment labels, kept apart from responses and research exports."""
import hashlib
import json
import secrets
from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from database import get_connection
from invitation_codes import remember_code, recover_code


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


class AssignmentInvitation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    bundle_hash: str = Field(min_length=1, max_length=128)
    assignment_id: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(strict=True, ge=0)
    expected_invitation: str | None = Field(max_length=128)
    reason: str = Field(min_length=10, max_length=500)
    confirm_session_close: bool = Field(default=False, strict=True)


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
            CREATE TABLE IF NOT EXISTS invitation_code_vault (
                component TEXT NOT NULL, invite_hash TEXT NOT NULL,
                encrypted_code TEXT NOT NULL,
                PRIMARY KEY(component,invite_hash)
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
        f"SELECT i.assignment_id,i.invite_hash,i.session_id,v.encrypted_code,s.phase,s.current_index,s.completed_at,s.withdrawn_at,l.listener_number "
        f"FROM {component}_invites i "
        "LEFT JOIN invitation_code_vault v ON v.invite_hash=i.invite_hash AND v.component=? "
        f"LEFT JOIN {component}_sessions s ON s.session_id=i.session_id AND s.bundle_hash=i.bundle_hash "
        f"LEFT JOIN {component}_listener_labels l ON l.session_id=s.session_id "
        "WHERE i.bundle_hash=? AND i.retired_at IS NULL", (component, checksum)
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
        protected = session is not None and session['completed_at'] and not session['withdrawn_at'] and not bundle['rehearsal']
        invitation, code_status = recover_code(component, session['invite_hash'] if session is not None else None,
                                               session['encrypted_code'] if session is not None else None)
        records.append(dict(
            assignment_id=assignment_id,
            participant_name=entry["participant_name"] if entry is not None else "",
            version=entry["version"] if entry is not None else 0,
            updated_by=entry["updated_by"] if entry is not None else "",
            updated_at=entry["updated_at"] if entry is not None else None,
            status=status,
            participant_label=f"Listener {number:03d}" if number is not None else None,
            saved_presentations=(session["current_index"] or 0) if session is not None else 0,
            invitation=invitation, invitation_status=code_status,
            invitation_version=session['invite_hash'] if session is not None else None,
            can_replace_invitation=session is not None and not bool(protected),
            has_started_session=bool(session is not None and session['session_id']),
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


def change_invitation(component, bundle, checksum, body):
    scope = _scope(component, bundle, checksum)
    if body.bundle_hash != checksum:
        raise HTTPException(409, 'The study version changed. Refresh the assignment list before replacing a code.')
    if body.assignment_id not in {block['assignment_id'] for block in bundle['assignments']}:
        raise HTTPException(404, 'That assignment is not part of the current study')
    with get_connection() as db:
        db.execute('BEGIN IMMEDIATE')
        entry = db.execute('SELECT version FROM assignment_roster WHERE component=? AND study_id=? AND bundle_hash=? AND assignment_id=?',
                           (*scope, body.assignment_id)).fetchone()
        if (entry['version'] if entry is not None else 0) != body.expected_version:
            raise HTTPException(409, 'Another researcher changed this assignment. Refresh and check the name before replacing its code.')
        active = db.execute(f'SELECT * FROM {component}_invites WHERE bundle_hash=? AND assignment_id=? AND retired_at IS NULL',
                            (checksum, body.assignment_id)).fetchone()
        if (active['invite_hash'] if active is not None else None) != body.expected_invitation:
            raise HTTPException(409, 'Another researcher changed this invitation. Refresh to see the current code.')
        if active is not None and active['session_id']:
            session = db.execute(f'SELECT * FROM {component}_sessions WHERE session_id=?', (active['session_id'],)).fetchone()
            if session['completed_at'] and not session['withdrawn_at'] and not bundle['rehearsal']:
                raise HTTPException(409, 'A completed research assignment cannot be replaced')
            if not body.confirm_session_close:
                raise HTTPException(409, 'Confirm that replacing this invitation closes the existing session. Saved answers will be preserved.')
            feedback = json.loads(session['feedback_json'] or '{}')
            feedback['replacement_reason'] = body.reason
            db.execute(f"UPDATE {component}_sessions SET phase='replaced',feedback_json=? WHERE session_id=?",
                       (json.dumps(feedback), active['session_id']))
        timestamp = datetime.now(timezone.utc).isoformat()
        if active is not None:
            db.execute(f'UPDATE {component}_invites SET retired_at=? WHERE invite_hash=?', (timestamp, active['invite_hash']))
        code = secrets.token_urlsafe(18)
        db.execute(f'INSERT INTO {component}_invites(invite_hash,bundle_hash,assignment_id,issued_at) VALUES (?,?,?,?)',
                   (hashlib.sha256(code.encode()).hexdigest(), checksum, body.assignment_id, timestamp))
        remember_code(db, component, code)
        assignment = next(row for row in _records(db, component, bundle, checksum) if row['assignment_id'] == body.assignment_id)
    return dict(bundle_hash=checksum, study_id=bundle['study_id'], assignment=assignment)
