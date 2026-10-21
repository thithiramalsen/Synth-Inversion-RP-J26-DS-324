"""Versioned C1 pilot API, isolated from historical studies and response tables."""
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

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from database import get_connection
from listening_setup import headphone_screening_enabled, session_screening_enabled, retire_participant_screen
from c1_protocol import PARTICIPANT_STUDY_ID, PARTICIPANT_PROTOCOL_VERSION, analysis_include
from experience import ExperienceEntry, experience_options
from response_viewer import KindFilter, PhaseFilter, response_page
from security import require_admin
from assignment_roster import AssignmentName, AssignmentInvitation, change_invitation, reserved_assignments, roster, save_name
from invitation_codes import remember_code

ROOT = Path(__file__).resolve().parents[2]
router = APIRouter(prefix="/api/c1-pilot")
Rating = Annotated[int, Field(strict=True, ge=1, le=7)] | Literal["unclear"]
CORRECTION_POLICY = "previous_before_next_play_v1"


def now():
    return datetime.now(timezone.utc).isoformat()


def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()


def bundle_path():
    return Path(os.environ.get("SURVEY_C1_BUNDLE", ROOT / "survey/deploy/study/c1_participant_bundle_v1.json"))


def known_bundle_paths():
    legacy = os.environ.get('SURVEY_C1_LEGACY_BUNDLES', str(ROOT / 'survey/deploy/study/bundle.json'))
    return list(dict.fromkeys([bundle_path().resolve(), *[Path(path).resolve() for path in legacy.split(os.pathsep) if path]]))


def config():
    path = Path(os.environ.get("SURVEY_C1_CONFIG", ROOT / "survey/config/c1_participants_v1.json"))
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if cfg.get('experience_entry_format') == 'experience_tags_v1':
        cfg['experience_selection'] = experience_options()
    return cfg


def load_bundle(path=None):
    path = Path(path) if path is not None else bundle_path()
    if not path.is_file():
        raise HTTPException(503, "The study audio has not been prepared yet")
    payload = path.read_bytes()
    data = json.loads(payload)
    if data["rehearsal"] == (data["study_id"] in ("c1_pilot_v1", PARTICIPANT_STUDY_ID)):
        raise HTTPException(409, "Rehearsal and production study IDs must be distinct")
    return data, hashlib.sha256(payload).hexdigest()


def bundle_for_hash(checksum):
    for path in known_bundle_paths():
        if not path.is_file():
            continue
        try:
            bundle, actual = load_bundle(path)
        except (ValueError, OSError, HTTPException):
            continue
        if secrets.compare_digest(actual, checksum):
            return bundle, path
    raise HTTPException(409, 'The saved study audio bundle is unavailable or changed; contact the researcher')


def admin_bundle_hashes(bundle, checksum):
    """Keep registered versions of the same researcher rehearsal visible.

    Participant and supervisor-review dashboards retain their current-bundle
    scope. This only broadens the explicitly separate researcher rehearsal.
    """
    hashes = [checksum]
    if not bundle['rehearsal'] or config().get('collection_mode') != 'researcher_rehearsal':
        return hashes
    for path in known_bundle_paths():
        if not path.is_file():
            continue
        previous, previous_hash = load_bundle(path)
        if (previous['rehearsal'] and previous['study_id'] == bundle['study_id']
                and previous_hash not in hashes):
            hashes.append(previous_hash)
    return hashes


def initialize_pilot_database():
    with get_connection() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS c1_invites (
            invite_hash TEXT PRIMARY KEY, bundle_hash TEXT NOT NULL, assignment_id TEXT NOT NULL,
            issued_at TEXT NOT NULL, session_id TEXT, retired_at TEXT
        );
        CREATE TABLE IF NOT EXISTS c1_sessions (
            session_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, participant_id TEXT NOT NULL,
            bundle_hash TEXT NOT NULL, protocol_hash TEXT NOT NULL, study_id TEXT NOT NULL,
            protocol_snapshot TEXT NOT NULL, assignment_id TEXT NOT NULL, entry_json TEXT NOT NULL,
            trial_order TEXT NOT NULL, screen_order TEXT NOT NULL, screen_answers TEXT NOT NULL DEFAULT '[]',
            phase TEXT NOT NULL DEFAULT 'volume', current_index INTEGER NOT NULL DEFAULT 0,
            break_done INTEGER NOT NULL DEFAULT 0, started_at TEXT NOT NULL,
            completed_at TEXT, withdrawn_at TEXT, feedback_json TEXT
        );
        CREATE TABLE IF NOT EXISTS c1_ratings (
            session_id TEXT NOT NULL, presentation_id TEXT NOT NULL, sample_id TEXT NOT NULL,
            kind TEXT NOT NULL, repeat_of TEXT, trial_order INTEGER NOT NULL,
            answers_json TEXT NOT NULL, play_count INTEGER NOT NULL, completed_plays INTEGER NOT NULL,
            started_at TEXT NOT NULL, submitted_at TEXT NOT NULL,
            UNIQUE(session_id, presentation_id)
        );
        CREATE TABLE IF NOT EXISTS c1_listener_labels (
            listener_number INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL UNIQUE
        );
        INSERT INTO c1_listener_labels(session_id)
            SELECT s.session_id FROM c1_sessions s
            LEFT JOIN c1_listener_labels l USING(session_id)
            WHERE l.session_id IS NULL ORDER BY s.started_at,s.session_id;
        CREATE TABLE IF NOT EXISTS c1_navigation (
            session_id TEXT PRIMARY KEY, correction_index INTEGER, correction_token TEXT
        );
        CREATE TABLE IF NOT EXISTS c1_exposures (
            session_id TEXT NOT NULL, presentation_id TEXT NOT NULL, opened_at TEXT NOT NULL,
            UNIQUE(session_id,presentation_id)
        );
        CREATE TABLE IF NOT EXISTS c1_rating_corrections (
            correction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL, presentation_id TEXT NOT NULL, answers_json TEXT NOT NULL,
            play_count INTEGER NOT NULL, completed_plays INTEGER NOT NULL,
            started_at TEXT NOT NULL, submitted_at TEXT NOT NULL
        );
        ''')


def listener_label(number):
    return f"Listener {number:03d}"


def corrections_enabled(row):
    return json.loads(row["protocol_snapshot"]).get("navigation_policy") == CORRECTION_POLICY


def active_correction(db, session_id):
    return db.execute("SELECT * FROM c1_navigation WHERE session_id=? AND correction_index IS NOT NULL", (session_id,)).fetchone()


def require_no_correction(db, session_id):
    if active_correction(db, session_id):
        raise HTTPException(409, "Save or cancel the current correction first")


def can_correct(db, row):
    if not corrections_enabled(row) or row["phase"] not in ("rating", "break", "feedback") or row["current_index"] == 0:
        return False
    if active_correction(db, row["session_id"]):
        return False
    trials = json.loads(row["trial_order"])
    if row["current_index"] < len(trials):
        current = trials[row["current_index"]]["presentation_id"]
        if db.execute("SELECT 1 FROM c1_exposures WHERE session_id=? AND presentation_id=?", (row["session_id"], current)).fetchone():
            return False
    return True


def launch_issues(bundle, cfg):
    if bundle.get('study_id') == PARTICIPANT_STUDY_ID and bundle.get('rehearsal') is False:
        issues = []
        if (cfg.get('study_id') != PARTICIPANT_STUDY_ID or cfg.get('collection_mode') != 'participants'
                or cfg.get('protocol_version') != PARTICIPANT_PROTOCOL_VERSION):
            issues.append('C1 participant information and collection version do not match')
        if cfg.get('headphone_screening_enabled') is not False:
            issues.append('This participant protocol goes directly from volume setup to practice')
        if os.environ.get('SURVEY_C1_OPEN', '1') != '1':
            issues.append('Participant entry is currently closed')
        for name in ('researcher_name', 'researcher_email', 'retention_statement', 'withdrawal_statement'):
            if not cfg.get(name, '').strip():
                issues.append(f'Complete {name.replace("_", " ")}')
        for block in bundle['assignments']:
            primary = [trial['sample_id'] for trial in block['trials'] if trial['kind'] == 'primary']
            if (len(block['trials']) != 23 or len(primary) != 20 or len(set(primary)) != 20
                    or sum(trial['kind'] == 'practice' for trial in block['trials']) != 3
                    or cfg.get('unique_sounds_per_person') != 20 or cfg.get('break_after_rated') != 10):
                issues.append('C1 assignment counts do not match the participant protocol')
                break
        return issues
    if bundle["rehearsal"]:
        return []
    issues = []
    if os.environ.get("SURVEY_C1_OPEN") != "1":
        issues.append("Recruitment has not been opened")
    for name in ("researcher_name", "researcher_email", "supervisor_contact", "retention_statement"):
        if not cfg.get(name):
            issues.append(f"Complete {name.replace('_', ' ')}")
    if cfg.get("institutional_review_status") not in ("reviewed_clearance_not_required", "approved"):
        issues.append("Record the applicable supervisor/institutional review outcome")
    if not cfg["eligibility"]["supervisor_confirmed"]:
        issues.append("Confirm participant eligibility/evidence with the supervisor")
    for key in ("level_policy_listening_checked", "rehearsal_completed"):
        if not cfg.get(key):
            issues.append(key.replace("_", " "))
    return issues


def checked_asset(relative, expected_hash, checksum):
    _, source_path = bundle_for_hash(checksum)
    root = source_path.parent
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
        practice = sum(trial['kind'] == 'practice' for trial in bundle['assignments'][0]['trials'])
        rehearsal = bundle["rehearsal"]
    except HTTPException as error:
        issues, total, practice, rehearsal = [str(error.detail)], 39, 3, False
    return dict(config=cfg, ready=not issues, issues=issues, total_presentations=total,
                practice_presentations=practice, rated_presentations=total-practice,
                rehearsal=rehearsal, study_id=cfg.get('study_id'))


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
        row = db.execute('''SELECT s.*,l.listener_number FROM c1_sessions s
                            JOIN c1_listener_labels l USING(session_id)
                            WHERE s.session_id = ?''', (session_id,)).fetchone()
    token = authorization.removeprefix("Bearer ")
    if row is None or not secrets.compare_digest(row["token_hash"], hashed(token)):
        raise HTTPException(401, "This session needs its original access token")
    return row


def context(session_id, authorization):
    row = session_row(session_id, authorization)
    bundle, _ = bundle_for_hash(row['bundle_hash'])
    if retire_participant_screen(row, PARTICIPANT_STUDY_ID, 'C1'):
        row = session_row(session_id, authorization)
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
        invitation = db.execute("SELECT * FROM c1_invites WHERE invite_hash=? AND retired_at IS NULL",
                                (hashed(entry.invitation.strip()),)).fetchone()
        if invitation is None or invitation["bundle_hash"] != checksum:
            raise HTTPException(403, "Invitation is not valid for this study")
        if invitation["session_id"]:
            raise HTTPException(409, "Invitation already used. Resume the existing session or contact the researcher.")
        block = next(b for b in bundle["assignments"] if b["assignment_id"] == invitation["assignment_id"])
        screens = [s["screen_id"] for s in bundle["headphones"]] if headphone_screening_enabled(cfg) else []
        secrets.SystemRandom().shuffle(screens)
        snapshot = json.dumps(cfg, sort_keys=True)
        db.execute('''INSERT INTO c1_sessions (session_id,token_hash,participant_id,bundle_hash,protocol_hash,
                     study_id,protocol_snapshot,assignment_id,entry_json,trial_order,screen_order,started_at)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                   (sid, hashed(token), "P_" + secrets.token_hex(8), checksum, hashed(snapshot), bundle["study_id"],
                    snapshot, block["assignment_id"], json.dumps(entry.model_dump(exclude={"invitation"})),
                    json.dumps(block["trials"]), json.dumps(screens), now()))
        db.execute("UPDATE c1_invites SET session_id=? WHERE invite_hash=?", (sid, invitation["invite_hash"]))
        db.execute("INSERT INTO c1_listener_labels(session_id) VALUES (?)", (sid,))
    return dict(session_id=sid, token=token)


def presentation_number(trials, index):
    practice = trials[index]['kind'] == 'practice'
    same_group = lambda trial: (trial['kind'] == 'practice') == practice
    return dict(display_number=sum(same_group(t) for t in trials[:index+1]),
                display_total=sum(same_group(t) for t in trials))


@router.get("/sessions/{session_id}")
def state(session_id: str, authorization: str = Header(default="")):
    row, bundle = context(session_id, authorization)
    trials = json.loads(row['trial_order'])
    result = dict(phase=row["phase"], participant_id=row["participant_id"], server_time=now(),
                  participant_label=listener_label(row["listener_number"]), saved_presentations=row["current_index"], current_index=row["current_index"],
                  total_presentations=len(trials), practice_presentations=sum(t['kind'] == 'practice' for t in trials), completed_at=row["completed_at"],
                  config=json.loads(row["protocol_snapshot"]), rehearsal=bundle["rehearsal"],
                  headphone_screening_enabled=session_screening_enabled(row))
    if row["phase"] == "volume":
        result["audio_id"] = "volume_reference"
    elif row["phase"] == "headphones":
        answers = json.loads(row["screen_answers"])
        result.update(audio_id=json.loads(row["screen_order"])[len(answers)], screen_number=len(answers)+1)
    elif row["phase"] == "rating":
        trials = json.loads(row["trial_order"])
        trial = trials[row["current_index"]]
        practice = trial["kind"] == "practice"
        result.update(presentation_id=trial["presentation_id"], audio_id=trial["sample_id"],
                      practice=practice, index=row["current_index"], total=len(trials),
                      **presentation_number(trials, row['current_index']))
    with get_connection() as db:
        correction = active_correction(db, session_id)
        result["can_correct_previous"] = can_correct(db, row)
        if correction and row["phase"] in ("rating", "break", "feedback"):
            trial = json.loads(row["trial_order"])[correction["correction_index"]]
            original = db.execute("SELECT answers_json FROM c1_ratings WHERE session_id=? AND presentation_id=?", (session_id, trial["presentation_id"])).fetchone()
            latest = db.execute("SELECT answers_json FROM c1_rating_corrections WHERE session_id=? AND presentation_id=? ORDER BY correction_id DESC LIMIT 1", (session_id, trial["presentation_id"])).fetchone()
            practice = trial["kind"] == "practice"
            result.update(phase="correction", presentation_id=trial["presentation_id"], audio_id=trial["sample_id"],
                          practice=practice, correction_token=correction["correction_token"],
                          saved_answers=json.loads((latest or original)["answers_json"]),
                          **presentation_number(trials, correction['correction_index']))
    return result


@router.get("/sessions/{session_id}/audio/{audio_id}")
def audio(session_id: str, audio_id: str, authorization: str = Header(default="")):
    row, bundle = context(session_id, authorization)
    if row["phase"] in ("withdrawn", "screen_failed", "replaced"):
        raise HTTPException(403, "Session ended")
    if audio_id == "volume_reference":
        asset = bundle["calibration"]
        path = checked_asset("audio/" + asset["path"], asset["sha256"], row['bundle_hash'])
    elif audio_id.startswith("headphones_"):
        if not session_screening_enabled(row):
            raise HTTPException(403, 'Headphone screening is not part of this session')
        asset = next((s for s in bundle["headphones"] if s["screen_id"] == audio_id), None)
        if asset is None:
            raise HTTPException(404, "Audio not found")
        path = checked_asset("audio/" + asset["path"], asset["sha256"], row['bundle_hash'])
    else:
        if corrections_enabled(row):
            raise HTTPException(403, "Start this sound through its presentation playback control")
        permitted = {t["sample_id"] for t in json.loads(row["trial_order"])}
        if audio_id not in permitted:
            raise HTTPException(404, "Audio not assigned")
        asset = bundle["samples"][audio_id]
        path = checked_asset(asset["playback_path"], asset["playback_sha256"], row['bundle_hash'])
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "private, no-store"})


@router.post("/sessions/{session_id}/playback/{presentation_id}")
def presentation_playback(session_id: str, presentation_id: str, authorization: str = Header(default="")):
    _, bundle = context(session_id, authorization)
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM c1_sessions WHERE session_id=?", (session_id,)).fetchone()
        if not corrections_enabled(row) or row["phase"] not in ("rating", "break", "feedback"):
            raise HTTPException(409, "No sound is available at this step")
        correction = active_correction(db, session_id)
        if not correction and row["phase"] != "rating":
            raise HTTPException(409, "No sound is available at this step")
        index = correction["correction_index"] if correction else row["current_index"]
        trial = json.loads(row["trial_order"])[index]
        if trial["presentation_id"] != presentation_id:
            raise HTTPException(409, "Only the current presentation can be played")
        asset = bundle["samples"][trial["sample_id"]]
        path = checked_asset(asset["playback_path"], asset["playback_sha256"], row['bundle_hash'])
        db.execute("INSERT INTO c1_exposures VALUES (?,?,?) ON CONFLICT DO NOTHING", (session_id, presentation_id, now()))
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "private, no-store"})


class PreviousRequest(StrictBody):
    current_index: int = Field(ge=1)


@router.post("/sessions/{session_id}/previous")
def previous(session_id: str, body: PreviousRequest, authorization: str = Header(default="")):
    context(session_id, authorization)
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM c1_sessions WHERE session_id=?", (session_id,)).fetchone()
        if row["current_index"] != body.current_index or not can_correct(db, row):
            raise HTTPException(409, "The previous response can no longer be reopened")
        db.execute('''INSERT INTO c1_navigation VALUES (?,?,?) ON CONFLICT(session_id)
                      DO UPDATE SET correction_index=excluded.correction_index,correction_token=excluded.correction_token''',
                   (session_id, row["current_index"]-1, secrets.token_urlsafe(18)))
    return {"opened": True}


class Played(StrictBody):
    completed_plays: int = Field(ge=1, le=1000)


@router.post("/sessions/{session_id}/volume")
def volume(session_id: str, body: Played, authorization: str = Header(default="")):
    row, _ = context(session_id, authorization)
    next_phase = 'headphones' if session_screening_enabled(row) else 'rating'
    with get_connection() as db:
        changed = db.execute("UPDATE c1_sessions SET phase=? WHERE session_id=? AND phase='volume'", (next_phase, session_id)).rowcount
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
        row = db.execute("SELECT * FROM c1_sessions WHERE session_id=?", (session_id,)).fetchone()
        answers = json.loads(row["screen_answers"])
        if row["phase"] != "headphones" or len(answers) + 1 != body.screen_number:
            raise HTTPException(409, "Screening question is no longer current")
        screen_id = json.loads(row["screen_order"])[len(answers)]
        expected = next(s for s in bundle["headphones"] if s["screen_id"] == screen_id)
        answers.append(dict(screen_id=screen_id, interval=body.interval, completed_plays=body.completed_plays,
                            correct=body.interval == expected["correct_interval"], submitted_at=now()))
        phase = "headphones" if len(answers) < 6 else ("rating" if sum(a["correct"] for a in answers) >= 5 else "screen_failed")
        db.execute("UPDATE c1_sessions SET screen_answers=?, phase=? WHERE session_id=?",
                   (json.dumps(answers), phase, session_id))
    return {"saved": True}


class Answers(StrictBody):
    brightness: Rating
    roughness: Rating
    percussiveness: Rating
    sustainedness: Rating = None
    comment: str = Field(default="", max_length=1000)


def checked_answers(row, answers: Answers):
    """Require the descriptors in this session's frozen questionnaire only."""
    expected = {d["id"] for d in json.loads(row["protocol_snapshot"])["descriptors"]}
    supplied = answers.model_fields_set - {"comment"}
    if supplied != expected:
        raise HTTPException(422, "Answer each descriptor shown in this session")
    values = answers.model_dump(include=expected | {"comment"})
    if any(values[name] != "unclear" and
           (type(values[name]) is not int or not 1 <= values[name] <= 7)
           for name in expected):
        raise HTTPException(422, "Select a rating from 1 to 7 or unclear")
    return values


class RatingBody(Played):
    presentation_id: str
    play_count: int = Field(ge=1, le=1000)
    answers: Answers
    started_at: datetime


class CorrectionToken(StrictBody):
    correction_token: str


class CorrectionBody(CorrectionToken):
    presentation_id: str
    answers: Answers
    play_count: int = Field(ge=0, le=1000)
    completed_plays: int = Field(ge=0, le=1000)
    started_at: datetime


def checked_correction(db, session_id, token):
    row = db.execute("SELECT * FROM c1_sessions WHERE session_id=?", (session_id,)).fetchone()
    correction = active_correction(db, session_id)
    if (not corrections_enabled(row) or row["phase"] not in ("rating", "break", "feedback")
            or not correction or not secrets.compare_digest(correction["correction_token"], token)):
        raise HTTPException(409, "This correction is no longer current")
    return row, correction


@router.post("/sessions/{session_id}/previous/cancel")
def cancel_correction(session_id: str, body: CorrectionToken, authorization: str = Header(default="")):
    context(session_id, authorization)
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        checked_correction(db, session_id, body.correction_token)
        db.execute("UPDATE c1_navigation SET correction_index=NULL,correction_token=NULL WHERE session_id=?", (session_id,))
    return {"cancelled": True}


@router.post("/sessions/{session_id}/previous/save")
def save_correction(session_id: str, body: CorrectionBody, authorization: str = Header(default="")):
    context(session_id, authorization)
    if body.completed_plays > body.play_count:
        raise HTTPException(422, "Invalid playback counts")
    if body.started_at.tzinfo is None or body.started_at > datetime.now(timezone.utc):
        raise HTTPException(422, "Invalid correction start time")
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row, correction = checked_correction(db, session_id, body.correction_token)
        trial = json.loads(row["trial_order"])[correction["correction_index"]]
        if trial["presentation_id"] != body.presentation_id:
            raise HTTPException(409, "This presentation is not the active correction")
        values = checked_answers(row, body.answers)
        db.execute('''INSERT INTO c1_rating_corrections
                      (session_id,presentation_id,answers_json,play_count,completed_plays,started_at,submitted_at)
                      VALUES (?,?,?,?,?,?,?)''',
                   (session_id, body.presentation_id, json.dumps(values), body.play_count,
                    body.completed_plays, body.started_at.isoformat(), now()))
        db.execute("UPDATE c1_navigation SET correction_index=NULL,correction_token=NULL WHERE session_id=?", (session_id,))
    return {"saved": True}


@router.post("/sessions/{session_id}/ratings")
def rating(session_id: str, body: RatingBody, authorization: str = Header(default="")):
    row, _ = context(session_id, authorization)
    values = checked_answers(row, body.answers)
    if body.completed_plays > body.play_count:
        raise HTTPException(422, "Invalid playback counts")
    if body.started_at.tzinfo is None or body.started_at > datetime.now(timezone.utc):
        raise HTTPException(422, "Invalid trial start time")
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM c1_sessions WHERE session_id=?", (session_id,)).fetchone()
        trials = json.loads(row["trial_order"])
        require_no_correction(db, session_id)
        if row["phase"] != "rating" or trials[row["current_index"]]["presentation_id"] != body.presentation_id:
            raise HTTPException(409, "This presentation is no longer current")
        if corrections_enabled(row) and not db.execute("SELECT 1 FROM c1_exposures WHERE session_id=? AND presentation_id=?", (session_id,body.presentation_id)).fetchone():
            raise HTTPException(409, "Start and listen to this sound before rating it")
        trial = trials[row["current_index"]]
        db.execute("INSERT INTO c1_ratings VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (session_id, trial["presentation_id"], trial["sample_id"], trial["kind"], trial["repeat_of"],
                    row["current_index"] + 1, json.dumps(values), body.play_count, body.completed_plays,
                    body.started_at.isoformat(), now()))
        index = row["current_index"] + 1
        practice_count = sum(t['kind'] == 'practice' for t in trials)
        break_after = json.loads(row['protocol_snapshot']).get('break_after_rated', 18)
        phase = "feedback" if index == len(trials) else "break" if index == practice_count + break_after and not row["break_done"] else "rating"
        db.execute("UPDATE c1_sessions SET current_index=?, phase=? WHERE session_id=?", (index, phase, session_id))
    return {"saved": True}


@router.post("/sessions/{session_id}/continue")
def continue_after_break(session_id: str, authorization: str = Header(default="")):
    context(session_id, authorization)
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        require_no_correction(db, session_id)
        changed = db.execute("UPDATE c1_sessions SET phase='rating',break_done=1 WHERE session_id=? AND phase='break'", (session_id,)).rowcount
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
        changed = db.execute("UPDATE c1_sessions SET phase='complete',completed_at=?,feedback_json=? WHERE session_id=? AND phase='feedback'",
                             (now(), json.dumps(body.model_dump()), session_id)).rowcount
    if not changed:
        raise HTTPException(409, "Feedback is no longer current")
    return {"saved": True}


@router.post("/sessions/{session_id}/withdraw")
def withdraw(session_id: str, authorization: str = Header(default="")):
    session_row(session_id, authorization)
    with get_connection() as db:
        db.execute("UPDATE c1_sessions SET withdrawn_at=?,phase='withdrawn' WHERE session_id=? AND withdrawn_at IS NULL", (now(), session_id))
    return {"withdrawn": True}


@router.post("/admin/invitations", dependencies=[Depends(require_admin)])
def issue_invitations():
    bundle, checksum = load_bundle()
    issued = []
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        for block in bundle["assignments"]:
            existing = db.execute("SELECT 1 FROM c1_invites WHERE bundle_hash=? AND assignment_id=? AND retired_at IS NULL",
                                  (checksum, block["assignment_id"])).fetchone()
            if existing:
                continue
            code = secrets.token_urlsafe(18)
            db.execute("INSERT INTO c1_invites(invite_hash,bundle_hash,assignment_id,issued_at) VALUES (?,?,?,?)",
                       (hashed(code), checksum, block["assignment_id"], now()))
            remember_code(db, "c1", code)
            issued.append(dict(assignment_id=block["assignment_id"], invitation=code))
    return {"invitations": issued, "note": "Codes are available to signed-in researchers in the shared assignment list. Do not publish."}


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
    reserved = []
    replaced = 0
    with get_connection() as db:
        # Uses the same lock as invitation claims, including on PostgreSQL.
        db.execute("BEGIN IMMEDIATE")
        named = reserved_assignments(db, "c1", bundle, checksum)
        for block in bundle["assignments"]:
            assignment_id = block["assignment_id"]
            if assignment_id in named:
                skipped.append(assignment_id)
                reserved.append(assignment_id)
                continue
            existing = db.execute(
                "SELECT * FROM c1_invites WHERE bundle_hash=? AND assignment_id=? AND retired_at IS NULL",
                (checksum, assignment_id),
            ).fetchall()
            if any(row["session_id"] is not None for row in existing):
                skipped.append(assignment_id)
                continue
            timestamp = now()
            if existing:
                db.execute(
                    "UPDATE c1_invites SET retired_at=? WHERE bundle_hash=? AND assignment_id=? AND retired_at IS NULL",
                    (timestamp, checksum, assignment_id),
                )
                replaced += 1
            code = secrets.token_urlsafe(18)
            db.execute("INSERT INTO c1_invites(invite_hash,bundle_hash,assignment_id,issued_at) VALUES (?,?,?,?)",
                       (hashed(code), checksum, assignment_id, timestamp))
            remember_code(db, "c1", code)
            issued.append(dict(assignment_id=assignment_id, invitation=code))
    response.headers["Cache-Control"] = "no-store"
    return dict(bundle_hash=checksum, invitations=issued, skipped_assignments=skipped, reserved_assignments=reserved,
                replaced_count=replaced, created_count=len(issued)-replaced,
                note="Codes are available in the shared assignment list. Previous unused codes are invalid. "
                     "Started sessions and assignments reserved with a name were left untouched. Do not publish.")


@router.post("/admin/replace-invitation", dependencies=[Depends(require_admin)])
def replace_invitation(body: ReplaceInvitation):
    bundle, checksum = load_bundle()
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        invitation = db.execute("SELECT * FROM c1_invites WHERE bundle_hash=? AND assignment_id=? AND retired_at IS NULL",
                                (checksum, body.assignment_id)).fetchone()
        if invitation is None:
            raise HTTPException(404, "Active assignment not found")
        if invitation["session_id"]:
            row = db.execute("SELECT * FROM c1_sessions WHERE session_id=?", (invitation["session_id"],)).fetchone()
            if row["completed_at"] and not row["withdrawn_at"] and not bundle["rehearsal"]:
                raise HTTPException(409, "A completed assignment cannot be replaced")
            preserved_feedback = json.loads(row["feedback_json"] or "{}")
            preserved_feedback["replacement_reason"] = body.reason
            db.execute("UPDATE c1_sessions SET phase='replaced',feedback_json=? WHERE session_id=?",
                       (json.dumps(preserved_feedback), invitation["session_id"]))
        db.execute("UPDATE c1_invites SET retired_at=? WHERE invite_hash=?", (now(), invitation["invite_hash"]))
        code = secrets.token_urlsafe(18)
        db.execute("INSERT INTO c1_invites(invite_hash,bundle_hash,assignment_id,issued_at) VALUES (?,?,?,?)",
                   (hashed(code), checksum, body.assignment_id, now()))
        remember_code(db, "c1", code)
    return {"assignment_id": body.assignment_id, "invitation": code}


@router.post("/admin/assignment-invitation", dependencies=[Depends(require_admin)])
def assignment_invitation(body: AssignmentInvitation, response: Response):
    bundle, checksum = load_bundle()
    response.headers["Cache-Control"] = "private, no-store"
    return change_invitation("c1", bundle, checksum, body)


@router.get("/admin/roster", dependencies=[Depends(require_admin)])
def assignment_roster(response: Response):
    bundle, checksum = load_bundle()
    response.headers["Cache-Control"] = "private, no-store"
    return roster("c1", bundle, checksum)


@router.post("/admin/assignment-name")
def assignment_name(body: AssignmentName, response: Response, actor: str = Depends(require_admin)):
    bundle, checksum = load_bundle()
    response.headers["Cache-Control"] = "private, no-store"
    return save_name("c1", bundle, checksum, body, actor)


@router.get("/admin/summary", dependencies=[Depends(require_admin)])
def summary():
    bundle, checksum = load_bundle()
    issues = launch_issues(bundle, config())
    hashes = admin_bundle_hashes(bundle, checksum)
    placeholders = ','.join('?' for _ in hashes)
    with get_connection() as db:
        sessions = db.execute(f'''SELECT participant_id,assignment_id,phase,current_index,started_at,completed_at,bundle_hash,
                                withdrawn_at,listener_number FROM c1_sessions JOIN c1_listener_labels USING(session_id)
                                WHERE bundle_hash IN ({placeholders}) AND study_id=?
                                ORDER BY listener_number''', (*hashes, bundle['study_id'])).fetchall()
    return dict(bundle_hash=checksum, sessions=[dict(r, participant_label=listener_label(r["listener_number"]),
                                                   is_current_version=r['bundle_hash'] == checksum) for r in sessions],
                completed=sum(r["phase"] == "complete" and not r["withdrawn_at"] for r in sessions),
                includes_previous_versions=len(hashes) > 1,
                previous_version_sessions=sum(r['bundle_hash'] != checksum for r in sessions),
                rehearsal=bundle['rehearsal'], study_id=bundle['study_id'], ready=not issues, issues=issues,
                assignment_capacity=len(bundle['assignments']))


@router.get("/admin/export", dependencies=[Depends(require_admin)])
def export():
    with get_connection() as db:
        rows = db.execute('''SELECT r.*,s.participant_id,s.study_id,s.bundle_hash,s.protocol_hash,s.assignment_id,
                            s.entry_json,s.screen_answers,s.phase,s.started_at AS session_started_at,s.completed_at,
                            s.withdrawn_at,s.feedback_json,s.protocol_snapshot,l.listener_number FROM c1_ratings r JOIN c1_sessions s USING(session_id)
                            JOIN c1_listener_labels l USING(session_id)
                            ORDER BY s.started_at,r.trial_order''').fetchall()
        corrections = db.execute("SELECT * FROM c1_rating_corrections ORDER BY correction_id").fetchall()
    correction_map = {}
    for item in corrections:
        correction_map.setdefault((item["session_id"],item["presentation_id"]), []).append(dict(item))
    columns = ["participant_id", "participant_label", "session_id", "study_id", "bundle_hash", "protocol_hash", "descriptor_ids", "assignment_id",
               "presentation_id", "sample_id", "kind", "repeat_of", "trial_order", "phase", "analysis_include",
               "brightness", "roughness", "percussiveness", "sustainedness", "comment", "play_count", "completed_plays",
               "started_at", "submitted_at", "completed_at", "withdrawn_at", "entry_json", "screen_answers", "feedback_json",
               "brightness_first", "roughness_first", "percussiveness_first", "sustainedness_first", "comment_first", "revision_count", "corrections_json",
               "protocol_version", "collection_mode", "target_ratings_per_sound"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for item in rows:
        row = dict(item)
        row["descriptor_ids"] = json.dumps([d["id"] for d in json.loads(row["protocol_snapshot"])["descriptors"]])
        row["participant_label"] = listener_label(row["listener_number"])
        first_answers = json.loads(row["answers_json"])
        row.update({k+"_first":v for k,v in first_answers.items()})
        revisions = correction_map.get((row["session_id"],row["presentation_id"]), [])
        row.update(json.loads(revisions[-1]["answers_json"]) if revisions else first_answers)
        row.update(revision_count=len(revisions),corrections_json=json.dumps(revisions))
        protocol = json.loads(row['protocol_snapshot'])
        row.update(protocol_version=protocol.get('protocol_version', ''), collection_mode=protocol.get('collection_mode', ''),
                   target_ratings_per_sound=protocol.get('target_ratings_per_sound', 8))
        row['analysis_include'] = analysis_include(row)
        # A spreadsheet must not execute participant-entered text as formulas.
        writer.writerow({k: safe_cell(row.get(k, "")) for k in columns})
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="c1_pilot_responses.csv"'})


@router.get('/admin/responses', dependencies=[Depends(require_admin)])
def view_responses(response: Response, offset: int = Query(default=0, ge=0), limit: int = Query(default=25, ge=1, le=100),
                   listener_number: int | None = Query(default=None, ge=1), phase: PhaseFilter = 'all', kind: KindFilter = 'all'):
    bundle, checksum = load_bundle()
    response.headers['Cache-Control'] = 'private, no-store'
    return response_page('C1', checksum, offset=offset, limit=limit, listener_number=listener_number,
                         phase=phase, kind=kind, rehearsal=bundle['rehearsal'],
                         bundle_hashes=admin_bundle_hashes(bundle, checksum))


def safe_cell(value):
    return "'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value


@router.get("/admin/sessions", dependencies=[Depends(require_admin)])
def session_export():
    columns = ["participant_id", "session_id", "study_id", "bundle_hash", "protocol_hash", "assignment_id",
               "phase", "current_index", "started_at", "completed_at", "withdrawn_at", "entry_json", "screen_answers", "feedback_json", "protocol_snapshot"]
    with get_connection() as db:
        rows = db.execute("SELECT " + ",".join("s." + c for c in columns) + ",l.listener_number FROM c1_sessions s JOIN c1_listener_labels l USING(session_id) ORDER BY s.started_at").fetchall()
    columns.insert(1, "participant_label")
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: listener_label(row["listener_number"]) if k == "participant_label" else safe_cell(row[k]) for k in columns})
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="c1_sessions.csv"'})
