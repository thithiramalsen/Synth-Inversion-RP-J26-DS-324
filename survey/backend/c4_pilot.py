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

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from database import get_connection
from experience import ExperienceEntry, experience_options
from security import require_admin

ROOT = Path(__file__).resolve().parents[2]
router = APIRouter(prefix="/api/c4-pilot")
CORRECTION_POLICY = 'previous_before_next_play_v1'


def now():
    return datetime.now(timezone.utc).isoformat()


def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()


def bundle_path():
    return Path(os.environ.get("SURVEY_C4_BUNDLE", ROOT / "survey/deploy/study/c4_bundle.json"))


def config():
    path = Path(os.environ.get("SURVEY_C4_CONFIG", ROOT / "survey/config/c4_review_v1.json"))
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if cfg.get('experience_entry_format') == 'experience_tags_v1':
        cfg['experience_selection'] = experience_options()
    return cfg


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
        CREATE TABLE IF NOT EXISTS c4_navigation (
            session_id TEXT PRIMARY KEY, correction_index INTEGER, correction_token TEXT
        );
        CREATE TABLE IF NOT EXISTS c4_rating_corrections (
            correction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL, presentation_id TEXT NOT NULL, answers_json TEXT NOT NULL,
            play_counts_json TEXT NOT NULL, completed_counts_json TEXT NOT NULL,
            started_at TEXT NOT NULL, submitted_at TEXT NOT NULL
        );
        ''')


def listener_label(number):
    return f"Listener {number:03d}"


def corrections_enabled(row):
    return json.loads(row['protocol_snapshot']).get('navigation_policy') == CORRECTION_POLICY


def active_correction(db, session_id):
    return db.execute('SELECT * FROM c4_navigation WHERE session_id=? AND correction_index IS NOT NULL', (session_id,)).fetchone()


def require_no_correction(db, session_id):
    if active_correction(db, session_id):
        raise HTTPException(409, 'Save or cancel the current correction first')


def can_correct(db, row):
    if (not corrections_enabled(row) or row['phase'] not in ('rating', 'break', 'feedback')
            or row['current_index'] == 0 or active_correction(db, row['session_id'])):
        return False
    trials = json.loads(row['trial_order'])
    if row['current_index'] < len(trials):
        current = trials[row['current_index']]['presentation_id']
        if db.execute('SELECT 1 FROM c4_exposures WHERE session_id=? AND presentation_id=?', (row['session_id'], current)).fetchone():
            return False
    return True


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


class Entry(ExperienceEntry):
    invitation: str = Field(min_length=8, max_length=150)
    adult: Literal[True]
    consent: Literal[True]
    headphones: Literal[True]
    quiet_environment: Literal[True]
    understands_language: Literal[True]
    activities: list[Literal["Music production", "Sound design", "Synthesizer patch creation", "Instrument performance", "Singing"]] = Field(min_length=1, max_length=5)
    experience_months: int = Field(ge=0, le=1200)
    recent_frequency: Literal["Less than monthly", "Monthly", "Weekly", "Daily"]


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
    with get_connection() as db:
        result['can_correct_previous'] = can_correct(db, row)
        correction = active_correction(db, session_id)
        if correction and row['phase'] in ('rating', 'break', 'feedback'):
            trial = json.loads(row['trial_order'])[correction['correction_index']]
            original = db.execute('SELECT answers_json FROM c4_ratings WHERE session_id=? AND presentation_id=?', (session_id, trial['presentation_id'])).fetchone()
            latest = db.execute('SELECT answers_json FROM c4_rating_corrections WHERE session_id=? AND presentation_id=? ORDER BY correction_id DESC LIMIT 1', (session_id, trial['presentation_id'])).fetchone()
            answers = json.loads((latest or original)['answers_json'])
            result.update(phase='correction', presentation_id=trial['presentation_id'], practice=trial['kind'] == 'practice',
                          correction_token=correction['correction_token'],
                          saved_answers={key: answers[key] for key in ('choice', 'confidence', 'comment')},
                          display_number=correction['correction_index']+1 if trial['kind'] == 'practice' else correction['correction_index']-1,
                          display_total=2 if trial['kind'] == 'practice' else result['total_presentations']-2)
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
        correction = active_correction(db, session_id)
        if row['phase'] not in ('rating', 'break', 'feedback') or (correction is None and row['phase'] != 'rating'):
            raise HTTPException(409, "No comparison is available at this step")
        index = correction['correction_index'] if correction else row['current_index']
        trial = json.loads(row["trial_order"])[index]
        if trial["presentation_id"] != presentation_id:
            raise HTTPException(409, "Only the current comparison can be played")
        asset = bundle["samples"][trial[role]]
        path = checked_asset(asset["playback_path"], asset["playback_sha256"])
        db.execute("INSERT INTO c4_exposures VALUES (?,?,?,?) ON CONFLICT DO NOTHING", (session_id, presentation_id, role, now()))
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "private, no-store"})


class Played(StrictBody):
    completed_plays: int = Field(ge=1, le=1000)


class PreviousRequest(StrictBody):
    current_index: int = Field(ge=1)


@router.post('/sessions/{session_id}/previous')
def previous(session_id: str, body: PreviousRequest, authorization: str = Header(default='')):
    context(session_id, authorization)
    with get_connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM c4_sessions WHERE session_id=?', (session_id,)).fetchone()
        if row['current_index'] != body.current_index or not can_correct(db, row):
            raise HTTPException(409, 'The previous response can no longer be reopened')
        db.execute('''INSERT INTO c4_navigation VALUES (?,?,?) ON CONFLICT(session_id)
                      DO UPDATE SET correction_index=excluded.correction_index,correction_token=excluded.correction_token''',
                   (session_id, row['current_index']-1, secrets.token_urlsafe(18)))
    return {'opened': True}


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


class CorrectionCounts(StrictBody):
    reference: int = Field(strict=True, ge=0, le=1000)
    candidate_a: int = Field(strict=True, ge=0, le=1000)
    candidate_b: int = Field(strict=True, ge=0, le=1000)


class CorrectionToken(StrictBody):
    correction_token: str


class CorrectionBody(CorrectionToken):
    presentation_id: str
    answers: Answers
    play_counts: CorrectionCounts
    completed_counts: CorrectionCounts
    started_at: datetime


def checked_correction(db, session_id, token):
    row = db.execute('SELECT * FROM c4_sessions WHERE session_id=?', (session_id,)).fetchone()
    correction = active_correction(db, session_id)
    if (not corrections_enabled(row) or row['phase'] not in ('rating', 'break', 'feedback') or not correction
            or not secrets.compare_digest(correction['correction_token'], token)):
        raise HTTPException(409, 'This correction is no longer current')
    return row, correction


@router.post('/sessions/{session_id}/previous/cancel')
def cancel_correction(session_id: str, body: CorrectionToken, authorization: str = Header(default='')):
    context(session_id, authorization)
    with get_connection() as db:
        db.execute('BEGIN IMMEDIATE')
        checked_correction(db, session_id, body.correction_token)
        db.execute('UPDATE c4_navigation SET correction_index=NULL,correction_token=NULL WHERE session_id=?', (session_id,))
    return {'cancelled': True}


@router.post('/sessions/{session_id}/previous/save')
def save_correction(session_id: str, body: CorrectionBody, authorization: str = Header(default='')):
    context(session_id, authorization)
    if (body.answers.choice == 'cannot_decide') != (body.answers.confidence is None):
        raise HTTPException(422, 'Choose confidence for A or B; leave it empty for cannot decide')
    plays, completed = body.play_counts.model_dump(), body.completed_counts.model_dump()
    if any(completed[role] > plays[role] for role in plays):
        raise HTTPException(422, 'Invalid playback counts')
    if body.started_at.tzinfo is None or body.started_at > datetime.now(timezone.utc):
        raise HTTPException(422, 'Invalid correction start time')
    with get_connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row, correction = checked_correction(db, session_id, body.correction_token)
        trial = json.loads(row['trial_order'])[correction['correction_index']]
        if trial['presentation_id'] != body.presentation_id:
            raise HTTPException(409, 'This comparison is not the active correction')
        values = body.answers.model_dump()
        values['chosen_sample_id'] = trial[values['choice']] if values['choice'] != 'cannot_decide' else None
        db.execute('''INSERT INTO c4_rating_corrections
                      (session_id,presentation_id,answers_json,play_counts_json,completed_counts_json,started_at,submitted_at)
                      VALUES (?,?,?,?,?,?,?)''',
                   (session_id, body.presentation_id, json.dumps(values), json.dumps(plays), json.dumps(completed), body.started_at.isoformat(), now()))
        db.execute('UPDATE c4_navigation SET correction_index=NULL,correction_token=NULL WHERE session_id=?', (session_id,))
    return {'saved': True}


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
        require_no_correction(db, session_id)
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
        require_no_correction(db, session_id)
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
        require_no_correction(db, session_id)
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


class ReplaceUnusedInvitations(StrictBody):
    confirm_replace_unused: Literal[True]


@router.post("/admin/replace-unused-invitations", dependencies=[Depends(require_admin)])
def replace_unused_invitations(body: ReplaceUnusedInvitations, response: Response):
    """Recover a lost invitation download without interrupting any claimed slot."""
    bundle, checksum = load_bundle()
    issued, skipped = [], []
    replaced = 0
    with get_connection() as db:
        # Uses the same lock as invitation claims, including on PostgreSQL.
        db.execute("BEGIN IMMEDIATE")
        for block in bundle["assignments"]:
            assignment_id = block["assignment_id"]
            existing = db.execute(
                "SELECT * FROM c4_invites WHERE bundle_hash=? AND assignment_id=? AND retired_at IS NULL",
                (checksum, assignment_id),
            ).fetchall()
            if any(row["session_id"] is not None for row in existing):
                skipped.append(assignment_id)
                continue
            timestamp = now()
            if existing:
                db.execute(
                    "UPDATE c4_invites SET retired_at=? WHERE bundle_hash=? AND assignment_id=? AND retired_at IS NULL",
                    (timestamp, checksum, assignment_id),
                )
                replaced += 1
            code = secrets.token_urlsafe(18)
            db.execute("INSERT INTO c4_invites(invite_hash,bundle_hash,assignment_id,issued_at) VALUES (?,?,?,?)",
                       (hashed(code), checksum, assignment_id, timestamp))
            issued.append(dict(assignment_id=assignment_id, invitation=code))
    response.headers["Cache-Control"] = "no-store"
    return dict(bundle_hash=checksum, invitations=issued, skipped_assignments=skipped,
                replaced_count=replaced, created_count=len(issued)-replaced,
                note="Save these once; only hashes are retained. Previous unused codes are invalid. "
                     "All assignments with a started session were left untouched. Do not publish.")


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
    bundle, checksum = load_bundle()
    with get_connection() as db:
        sessions = db.execute('''SELECT participant_id,assignment_id,phase,current_index,started_at,completed_at,
                                withdrawn_at,listener_number FROM c4_sessions JOIN c4_listener_labels USING(session_id)
                                WHERE bundle_hash=?''', (checksum,)).fetchall()
        invitations = db.execute('''SELECT i.assignment_id,i.issued_at,s.phase,s.current_index,
                                    s.completed_at,s.withdrawn_at,l.listener_number
                                    FROM c4_invites i
                                    LEFT JOIN c4_sessions s ON s.session_id=i.session_id AND s.bundle_hash=i.bundle_hash
                                    LEFT JOIN c4_listener_labels l ON l.session_id=s.session_id
                                    WHERE i.bundle_hash=? AND i.retired_at IS NULL''', (checksum,)).fetchall()
    active = {row["assignment_id"]: row for row in invitations}
    assignments = []
    for block in bundle["assignments"]:
        row = active.get(block["assignment_id"])
        status = "missing"
        if row is not None:
            status = "issued"
            if row["withdrawn_at"]:
                status = "withdrawn"
            elif row["completed_at"] or row["phase"] == "complete":
                status = "completed"
            elif row["phase"] == "screen_failed":
                status = "screen_failed"
            elif row["phase"]:
                status = "in_progress"
        protected = row is not None and row["completed_at"] and not row["withdrawn_at"] and not bundle["rehearsal"]
        assignments.append(dict(
            assignment_id=block["assignment_id"], status=status,
            issued_at=row["issued_at"] if row is not None else None,
            participant_label=listener_label(row["listener_number"]) if row is not None and row["listener_number"] is not None else None,
            phase=row["phase"] if row is not None else None,
            saved_presentations=(row["current_index"] or 0) if row is not None else 0,
            can_replace=row is not None and not protected,
        ))
    return dict(bundle_hash=checksum, sessions=[dict(r, participant_label=listener_label(r["listener_number"])) for r in sessions],
                completed=sum(r["phase"] == "complete" and not r["withdrawn_at"] for r in sessions),
                assignments=assignments, assignment_capacity=len(assignments),
                missing_invitation_count=sum(row["status"] == "missing" for row in assignments))


@router.get("/admin/export", dependencies=[Depends(require_admin)])
def export():
    with get_connection() as db:
        rows = db.execute("SELECT r.*,s.participant_id,s.study_id,s.bundle_hash,s.protocol_hash,s.assignment_id,s.phase,s.withdrawn_at,s.completed_at FROM c4_ratings r JOIN c4_sessions s USING(session_id) ORDER BY s.started_at,r.trial_order").fetchall()
        corrections = db.execute('SELECT * FROM c4_rating_corrections ORDER BY correction_id').fetchall()
    correction_map = {}
    for item in corrections:
        correction_map.setdefault((item['session_id'], item['presentation_id']), []).append(dict(item))
    columns = ["participant_id", "session_id", "study_id", "bundle_hash", "protocol_hash", "assignment_id",
               "presentation_id", "triplet_id", "reference", "candidate_a", "candidate_b", "kind", "repeat_of", "trial_order",
               "choice", "chosen_sample_id", "confidence", "comment", "play_count", "completed_plays", "started_at", "submitted_at",
               "phase", "completed_at", "withdrawn_at", "analysis_include",
               "choice_first", "chosen_sample_id_first", "confidence_first", "comment_first", "revision_count", "corrections_json"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for item in rows:
        row = dict(item)
        row.update(json.loads(row["triplet_json"]))
        first = json.loads(row['answers_json'])
        revisions = correction_map.get((row['session_id'], row['presentation_id']), [])
        row.update({key+'_first': value for key, value in first.items()})
        row.update(json.loads(revisions[-1]['answers_json']) if revisions else first)
        row.update(revision_count=len(revisions), corrections_json=json.dumps(revisions))
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
