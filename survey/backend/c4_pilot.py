"""Versioned C4 pilot API, isolated from historical studies and response tables."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from database import get_connection
from security import require_admin

ROOT = Path(__file__).resolve().parents[2]
router = APIRouter(prefix="/api/c4-pilot")


def now():
    return datetime.now(timezone.utc).isoformat()


def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()


def bundle_path():
    return Path(os.environ.get("SURVEY_C4_BUNDLE", ROOT / "survey/deploy/study/c4_bundle.json"))


def config():
    path = Path(os.environ.get("SURVEY_C4_CONFIG", ROOT / "survey/config/c4_review_v1.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def load_bundle():
    path = bundle_path()
    if not path.is_file():
        raise HTTPException(503, "The study audio has not been prepared yet")
    payload = path.read_bytes()
    data = json.loads(payload)
    return data, hashlib.sha256(payload).hexdigest()


def initialize_pilot_database():
    with get_connection() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS c4_invites (
            invite_hash TEXT PRIMARY KEY, bundle_hash TEXT NOT NULL, assignment_id TEXT NOT NULL,
            issued_at TEXT NOT NULL, session_id TEXT, retired_at TEXT
        );
        CREATE TABLE IF NOT EXISTS c4_sessions (
            session_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, participant_id TEXT NOT NULL,
            bundle_hash TEXT NOT NULL, protocol_hash TEXT NOT NULL, study_id TEXT NOT NULL,
            protocol_snapshot TEXT NOT NULL, assignment_id TEXT NOT NULL, entry_json TEXT NOT NULL,
            trial_order TEXT NOT NULL, screen_order TEXT NOT NULL, screen_answers TEXT NOT NULL DEFAULT '[]',
            phase TEXT NOT NULL DEFAULT 'volume', current_index INTEGER NOT NULL DEFAULT 0,
            break_done INTEGER NOT NULL DEFAULT 0, started_at TEXT NOT NULL,
            completed_at TEXT, withdrawn_at TEXT, feedback_json TEXT
        );
        CREATE TABLE IF NOT EXISTS c4_ratings (
            session_id TEXT NOT NULL, presentation_id TEXT NOT NULL, triplet_json TEXT NOT NULL,
            kind TEXT NOT NULL, repeat_of TEXT, trial_order INTEGER NOT NULL,
            answers_json TEXT NOT NULL, play_count TEXT NOT NULL, completed_plays TEXT NOT NULL,
            started_at TEXT NOT NULL, submitted_at TEXT NOT NULL,
            UNIQUE(session_id, presentation_id)
        );
        CREATE TABLE IF NOT EXISTS c4_listener_labels (
            listener_number INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL UNIQUE
        );
        INSERT INTO c4_listener_labels(session_id)
            SELECT s.session_id FROM c4_sessions s
            LEFT JOIN c4_listener_labels l USING(session_id)
            WHERE l.session_id IS NULL ORDER BY s.started_at,s.session_id;
        CREATE TABLE IF NOT EXISTS c4_exposures (
            session_id TEXT NOT NULL, presentation_id TEXT NOT NULL, role TEXT NOT NULL, opened_at TEXT NOT NULL,
            UNIQUE(session_id,presentation_id,role)
        );
        ''')


def listener_label(number):
    return f"Listener {number:03d}"


def launch_issues(bundle, cfg):
    # This release implements review only. Formal C4 recruitment requires a new protocol.
    return [] if bundle.get("rehearsal") is True and bundle.get("study_id") == "c4_review_v1" else ["Only the C4 review protocol is available"]


def checked_asset(relative, expected_hash):
    root = bundle_path().resolve().parent
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(409, "Study audio unavailable")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
        raise HTTPException(409, "Study audio changed; contact the researcher")
    return path


@router.get("/status")
def status():
    cfg = config()
    try:
        bundle, _ = load_bundle()
        issues = launch_issues(bundle, cfg)
        total = len(bundle["assignments"][0]["trials"])
        rehearsal = bundle["rehearsal"]
    except HTTPException as error:
        issues, total, rehearsal = [str(error.detail)], 39, False
    return dict(config=cfg, ready=not issues, issues=issues, total_presentations=total,
                rated_presentations=total-2, rehearsal=rehearsal)


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Entry(StrictBody):
    invitation: str = Field(min_length=8, max_length=150)
    adult: Literal[True]
    consent: Literal[True]
    headphones: Literal[True]
    quiet_environment: Literal[True]
    understands_language: Literal[True]
    activities: list[Literal["Music production", "Sound design", "Synthesizer patch creation", "Instrument performance", "Singing"]] = Field(min_length=1, max_length=5)
    experience_months: int = Field(ge=0, le=1200)
    recent_frequency: Literal["Less than monthly", "Monthly", "Weekly", "Daily"]
    tools: str = Field(min_length=2, max_length=250)
    example: str = Field(min_length=20, max_length=700)


def session_row(session_id, authorization):
    with get_connection() as db:
        row = db.execute('''SELECT s.*,l.listener_number FROM c4_sessions s
                            JOIN c4_listener_labels l USING(session_id)
                            WHERE s.session_id = ?''', (session_id,)).fetchone()
    token = authorization.removeprefix("Bearer ")
    if row is None or not secrets.compare_digest(row["token_hash"], hashed(token)):
        raise HTTPException(401, "This session needs its original access token")
    return row


def context(session_id, authorization):
    row = session_row(session_id, authorization)
    bundle, checksum = load_bundle()
    if row["bundle_hash"] != checksum:
        raise HTTPException(409, "The audio bundle changed; this session cannot continue")
    # A participant stays on the exact consent/question version they entered.
    return row, bundle


@router.post("/sessions")
def start(entry: Entry):
    bundle, checksum = load_bundle()
    cfg = config()
    issues = launch_issues(bundle, cfg)
    if issues:
        raise HTTPException(403, "Study not open: " + "; ".join(issues))
    if not entry.tools.strip() or len(entry.example.strip()) < 20:
        raise HTTPException(422, "Please describe your relevant experience")
    if not set(entry.activities).issubset(cfg['eligibility']['activities']):
        raise HTTPException(422, "Select experience categories offered by this study")
    token, sid = secrets.token_urlsafe(32), "S_" + secrets.token_hex(12)
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        invitation = db.execute("SELECT * FROM c4_invites WHERE invite_hash=? AND retired_at IS NULL",
                                (hashed(entry.invitation.strip()),)).fetchone()
        if invitation is None or invitation["bundle_hash"] != checksum:
            raise HTTPException(403, "Invitation is not valid for this study")
        if invitation["session_id"]:
            raise HTTPException(409, "Invitation already used. Resume the existing session or contact the researcher.")
        block = next(b for b in bundle["assignments"] if b["assignment_id"] == invitation["assignment_id"])
        screens = [s["screen_id"] for s in bundle["headphones"]]
        secrets.SystemRandom().shuffle(screens)
        snapshot = json.dumps(cfg, sort_keys=True)
        db.execute('''INSERT INTO c4_sessions (session_id,token_hash,participant_id,bundle_hash,protocol_hash,
                     study_id,protocol_snapshot,assignment_id,entry_json,trial_order,screen_order,started_at)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                   (sid, hashed(token), "P_" + secrets.token_hex(8), checksum, hashed(snapshot), bundle["study_id"],
                    snapshot, block["assignment_id"], json.dumps(entry.model_dump(exclude={"invitation"})),
                    json.dumps(block["trials"]), json.dumps(screens), now()))
        db.execute("UPDATE c4_invites SET session_id=? WHERE invite_hash=?", (sid, invitation["invite_hash"]))
        db.execute("INSERT INTO c4_listener_labels(session_id) VALUES (?)", (sid,))
    return dict(session_id=sid, token=token)


@router.get("/sessions/{session_id}")
def state(session_id: str, authorization: str = Header(default="")):
    row, bundle = context(session_id, authorization)
    result = dict(phase=row["phase"], participant_id=row["participant_id"], server_time=now(),
                  participant_label=listener_label(row["listener_number"]), saved_presentations=row["current_index"], current_index=row["current_index"],
                  total_presentations=len(json.loads(row["trial_order"])), completed_at=row["completed_at"],
                  config=json.loads(row["protocol_snapshot"]), rehearsal=bundle["rehearsal"])
    if row["phase"] == "volume":
        result["audio_id"] = "volume_reference"
    elif row["phase"] == "headphones":
        answers = json.loads(row["screen_answers"])
        result.update(audio_id=json.loads(row["screen_order"])[len(answers)], screen_number=len(answers)+1)
    elif row["phase"] == "rating":
        trials = json.loads(row["trial_order"])
        trial = trials[row["current_index"]]
        practice = trial["kind"] == "practice"
        result.update(presentation_id=trial["presentation_id"], practice=practice,
                      index=row["current_index"], total=len(trials),
                      display_number=row["current_index"]+1 if practice else row["current_index"]-1,
                      display_total=2 if practice else len(trials)-2)
    return result


@router.get("/sessions/{session_id}/audio/{audio_id}")
def audio(session_id: str, audio_id: str, authorization: str = Header(default="")):
    row, bundle = context(session_id, authorization)
    if row["phase"] in ("withdrawn", "screen_failed", "replaced"):
        raise HTTPException(403, "Session ended")
    if audio_id == "volume_reference":
        asset = bundle["calibration"]
        path = checked_asset("audio/" + asset["path"], asset["sha256"])
    elif audio_id.startswith("headphones_"):
        asset = next((s for s in bundle["headphones"] if s["screen_id"] == audio_id), None)
        if asset is None:
            raise HTTPException(404, "Audio not found")
        path = checked_asset("audio/" + asset["path"], asset["sha256"])
    else:
        raise HTTPException(403, "Use the current comparison playback controls")
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "private, no-store"})


@router.post("/sessions/{session_id}/playback/{presentation_id}/{role}")
def presentation_playback(session_id: str, presentation_id: str,
                          role: Literal["reference", "candidate_a", "candidate_b"],
                          authorization: str = Header(default="")):
    _, bundle = context(session_id, authorization)
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM c4_sessions WHERE session_id=?", (session_id,)).fetchone()
        if row["phase"] != "rating":
            raise HTTPException(409, "No comparison is available at this step")
        trial = json.loads(row["trial_order"])[row["current_index"]]
        if trial["presentation_id"] != presentation_id:
            raise HTTPException(409, "Only the current comparison can be played")
        asset = bundle["samples"][trial[role]]
        path = checked_asset(asset["playback_path"], asset["playback_sha256"])
        db.execute("INSERT INTO c4_exposures VALUES (?,?,?,?) ON CONFLICT DO NOTHING", (session_id, presentation_id, role, now()))
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "private, no-store"})


class Played(StrictBody):
    completed_plays: int = Field(ge=1, le=1000)


@router.post("/sessions/{session_id}/volume")
def volume(session_id: str, body: Played, authorization: str = Header(default="")):
    context(session_id, authorization)
    with get_connection() as db:
        changed = db.execute("UPDATE c4_sessions SET phase='headphones' WHERE session_id=? AND phase='volume'", (session_id,)).rowcount
    if not changed:
        raise HTTPException(409, "Volume step is no longer current")
    return {"saved": True}


class ScreenAnswer(Played):
    screen_number: int = Field(ge=1, le=6)
    interval: int = Field(ge=1, le=3)


@router.post("/sessions/{session_id}/headphones")
def screen(session_id: str, body: ScreenAnswer, authorization: str = Header(default="")):
    _, bundle = context(session_id, authorization)
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM c4_sessions WHERE session_id=?", (session_id,)).fetchone()
        answers = json.loads(row["screen_answers"])
        if row["phase"] != "headphones" or len(answers) + 1 != body.screen_number:
            raise HTTPException(409, "Screening question is no longer current")
        screen_id = json.loads(row["screen_order"])[len(answers)]
        expected = next(s for s in bundle["headphones"] if s["screen_id"] == screen_id)
        answers.append(dict(screen_id=screen_id, interval=body.interval, completed_plays=body.completed_plays,
                            correct=body.interval == expected["correct_interval"], submitted_at=now()))
        phase = "headphones" if len(answers) < 6 else ("rating" if sum(a["correct"] for a in answers) >= 5 else "screen_failed")
        db.execute("UPDATE c4_sessions SET screen_answers=?, phase=? WHERE session_id=?",
                   (json.dumps(answers), phase, session_id))
    return {"saved": True}


class Counts(StrictBody):
    reference: int = Field(strict=True, ge=1, le=1000)
    candidate_a: int = Field(strict=True, ge=1, le=1000)
    candidate_b: int = Field(strict=True, ge=1, le=1000)


class Answers(StrictBody):
    choice: Literal["candidate_a", "candidate_b", "cannot_decide"]
    confidence: Annotated[int, Field(strict=True, ge=1, le=5)] | None = None
    comment: str = Field(default="", max_length=1000)


class RatingBody(StrictBody):
    presentation_id: str
    play_counts: Counts
    completed_counts: Counts
    answers: Answers
    started_at: datetime


@router.post("/sessions/{session_id}/ratings")
def rating(session_id: str, body: RatingBody, authorization: str = Header(default="")):
    context(session_id, authorization)
    if (body.answers.choice == "cannot_decide") != (body.answers.confidence is None):
        raise HTTPException(422, "Choose confidence for A or B; leave it empty for cannot decide")
    plays, completed = body.play_counts.model_dump(), body.completed_counts.model_dump()
    if any(completed[r] > plays[r] for r in plays):
        raise HTTPException(422, "Invalid playback counts")
    if body.started_at.tzinfo is None or body.started_at > datetime.now(timezone.utc):
        raise HTTPException(422, "Invalid trial start time")
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM c4_sessions WHERE session_id=?", (session_id,)).fetchone()
        trials = json.loads(row["trial_order"])
        if row["phase"] != "rating" or trials[row["current_index"]]["presentation_id"] != body.presentation_id:
            raise HTTPException(409, "This comparison is no longer current")
        exposed = db.execute("SELECT role FROM c4_exposures WHERE session_id=? AND presentation_id=?", (session_id, body.presentation_id)).fetchall()
        if {r["role"] for r in exposed} != set(plays):
            raise HTTPException(409, "Play all three sounds before answering")
        trial = trials[row["current_index"]]
        values = body.answers.model_dump()
        values["chosen_sample_id"] = trial[values["choice"]] if values["choice"] != "cannot_decide" else None
        db.execute("INSERT INTO c4_ratings VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (session_id, trial["presentation_id"], json.dumps(trial), trial["kind"], trial["repeat_of"],
                    row["current_index"]+1, json.dumps(values), json.dumps(plays), json.dumps(completed),
                    body.started_at.isoformat(), now()))
        index = row["current_index"]+1
        phase = "feedback" if index == len(trials) else "break" if index == 8 and not row["break_done"] else "rating"
        db.execute("UPDATE c4_sessions SET current_index=?,phase=? WHERE session_id=?", (index,phase,session_id))
    return {"saved": True}


@router.post("/sessions/{session_id}/continue")
def continue_after_break(session_id: str, authorization: str = Header(default="")):
    context(session_id, authorization)
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        changed = db.execute("UPDATE c4_sessions SET phase='rating',break_done=1 WHERE session_id=? AND phase='break'", (session_id,)).rowcount
    if not changed:
        raise HTTPException(409, "No break is pending")
    return {"saved": True}


class Feedback(StrictBody):
    clarity: Literal["Clear", "Some terms unclear", "Difficult to understand"]
    length: Literal["About right", "Too long", "Could be longer"]
    comment: str = Field(default="", max_length=1500)


@router.post("/sessions/{session_id}/feedback")
def feedback(session_id: str, body: Feedback, authorization: str = Header(default="")):
    context(session_id, authorization)
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        changed = db.execute("UPDATE c4_sessions SET phase='complete',completed_at=?,feedback_json=? WHERE session_id=? AND phase='feedback'",
                             (now(), json.dumps(body.model_dump()), session_id)).rowcount
    if not changed:
        raise HTTPException(409, "Feedback is no longer current")
    return {"saved": True}


@router.post("/sessions/{session_id}/withdraw")
def withdraw(session_id: str, authorization: str = Header(default="")):
    session_row(session_id, authorization)
    with get_connection() as db:
        db.execute("UPDATE c4_sessions SET withdrawn_at=?,phase='withdrawn' WHERE session_id=? AND withdrawn_at IS NULL", (now(), session_id))
    return {"withdrawn": True}


@router.post("/admin/invitations", dependencies=[Depends(require_admin)])
def issue_invitations():
    bundle, checksum = load_bundle()
    issued = []
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        for block in bundle["assignments"]:
            existing = db.execute("SELECT 1 FROM c4_invites WHERE bundle_hash=? AND assignment_id=? AND retired_at IS NULL",
                                  (checksum, block["assignment_id"])).fetchone()
            if existing:
                continue
            code = secrets.token_urlsafe(18)
            db.execute("INSERT INTO c4_invites(invite_hash,bundle_hash,assignment_id,issued_at) VALUES (?,?,?,?)",
                       (hashed(code), checksum, block["assignment_id"], now()))
            issued.append(dict(assignment_id=block["assignment_id"], invitation=code))
    return {"invitations": issued, "note": "Save these once; only hashes are retained. Do not publish."}


class ReplaceInvitation(StrictBody):
    assignment_id: str
    reason: str = Field(min_length=10, max_length=500)


@router.post("/admin/replace-invitation", dependencies=[Depends(require_admin)])
def replace_invitation(body: ReplaceInvitation):
    bundle, checksum = load_bundle()
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        invitation = db.execute("SELECT * FROM c4_invites WHERE bundle_hash=? AND assignment_id=? AND retired_at IS NULL",
                                (checksum, body.assignment_id)).fetchone()
        if invitation is None:
            raise HTTPException(404, "Active assignment not found")
        if invitation["session_id"]:
            row = db.execute("SELECT * FROM c4_sessions WHERE session_id=?", (invitation["session_id"],)).fetchone()
            if row["completed_at"] and not row["withdrawn_at"] and not bundle["rehearsal"]:
                raise HTTPException(409, "A completed assignment cannot be replaced")
            preserved_feedback = json.loads(row["feedback_json"] or "{}")
            preserved_feedback["replacement_reason"] = body.reason
            db.execute("UPDATE c4_sessions SET phase='replaced',feedback_json=? WHERE session_id=?",
                       (json.dumps(preserved_feedback), invitation["session_id"]))
        db.execute("UPDATE c4_invites SET retired_at=? WHERE invite_hash=?", (now(), invitation["invite_hash"]))
        code = secrets.token_urlsafe(18)
        db.execute("INSERT INTO c4_invites(invite_hash,bundle_hash,assignment_id,issued_at) VALUES (?,?,?,?)",
                   (hashed(code), checksum, body.assignment_id, now()))
    return {"assignment_id": body.assignment_id, "invitation": code}


@router.get("/admin/summary", dependencies=[Depends(require_admin)])
def summary():
    _, checksum = load_bundle()
    with get_connection() as db:
        sessions = db.execute('''SELECT participant_id,assignment_id,phase,current_index,started_at,completed_at,
                                withdrawn_at,listener_number FROM c4_sessions JOIN c4_listener_labels USING(session_id)
                                WHERE bundle_hash=?''', (checksum,)).fetchall()
    return dict(bundle_hash=checksum, sessions=[dict(r, participant_label=listener_label(r["listener_number"])) for r in sessions],
                completed=sum(r["phase"] == "complete" and not r["withdrawn_at"] for r in sessions))


@router.get("/admin/export", dependencies=[Depends(require_admin)])
def export():
    with get_connection() as db:
        rows = db.execute("SELECT r.*,s.participant_id,s.study_id,s.bundle_hash,s.protocol_hash,s.assignment_id,s.phase,s.withdrawn_at,s.completed_at FROM c4_ratings r JOIN c4_sessions s USING(session_id) ORDER BY s.started_at,r.trial_order").fetchall()
    columns = ["participant_id", "session_id", "study_id", "bundle_hash", "protocol_hash", "assignment_id",
               "presentation_id", "triplet_id", "reference", "candidate_a", "candidate_b", "kind", "repeat_of", "trial_order",
               "choice", "chosen_sample_id", "confidence", "comment", "play_count", "completed_plays", "started_at", "submitted_at",
               "phase", "completed_at", "withdrawn_at", "analysis_include"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for item in rows:
        row = dict(item)
        row.update(json.loads(row["triplet_json"]))
        row.update(json.loads(row["answers_json"]))
        row["analysis_include"] = False  # All sessions in this release are interface reviews.
        writer.writerow({k: safe_cell(row.get(k, "")) for k in columns})
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="c4_review_responses.csv"'})


def safe_cell(value):
    return "'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value


@router.get("/admin/sessions", dependencies=[Depends(require_admin)])
def session_export():
    columns = ["participant_id", "session_id", "study_id", "bundle_hash", "protocol_hash", "assignment_id",
               "phase", "current_index", "started_at", "completed_at", "withdrawn_at", "entry_json", "screen_answers", "feedback_json", "protocol_snapshot"]
    with get_connection() as db:
        rows = db.execute("SELECT " + ",".join("s." + c for c in columns) + ",l.listener_number FROM c4_sessions s JOIN c4_listener_labels l USING(session_id) ORDER BY s.started_at").fetchall()
    columns.insert(1, "participant_label")
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: listener_label(row["listener_number"]) if k == "participant_label" else safe_cell(row[k]) for k in columns})
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="c4_sessions.csv"'})
