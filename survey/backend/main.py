import csv
import io
import json
import random
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import ValidationError

from database import get_connection, initialize_database
from models import (
    C1DescriptorAnswers,
    PilotQualityAnswers,
    ResponseRequest,
    SingleAudioPlayCounts,
    StartSessionRequest,
)


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "data" / "manifests" / "pilot_v1.csv"
CONFIG_DIR = ROOT / "survey" / "config"
STUDY_CONFIGS = {
    "pilot_quality": CONFIG_DIR / "pilot_quality.json",
    "c1_descriptors": CONFIG_DIR / "c1_descriptors.json",
}
STUDY_ALIASES = {"pilot_v1": "pilot_quality"}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Synth Inversion Listening Survey", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):517\d$",
    allow_methods=["*"],
    allow_headers=["*"],
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_study_id(study_id: str) -> str:
    canonical = STUDY_ALIASES.get(study_id, study_id)
    if canonical not in STUDY_CONFIGS:
        raise HTTPException(status_code=404, detail="Study not found")
    return canonical


def load_study(study_id: str) -> dict[str, Any]:
    canonical = canonical_study_id(study_id)
    return json.loads(STUDY_CONFIGS[canonical].read_text(encoding="utf-8"))


def load_manifest() -> list[dict[str, str]]:
    with MANIFEST_PATH.open(newline="", encoding="utf-8-sig") as manifest_file:
        manifest = list(csv.DictReader(manifest_file))
    sample_ids = [row["sample_id"] for row in manifest]
    if len(sample_ids) != len(set(sample_ids)):
        raise RuntimeError("The survey manifest contains duplicate sample IDs")
    return manifest


def manifest_by_sample_id() -> dict[str, dict[str, str]]:
    return {row["sample_id"]: row for row in load_manifest()}


def get_session(session_id: str) -> sqlite3.Row:
    with get_connection() as connection:
        session = connection.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def get_stable_trial_ids(session: sqlite3.Row) -> list[str]:
    """Return saved sample IDs and migrate development sessions that stored CSV indexes."""
    stored_order = json.loads(session["trial_order"])
    if not isinstance(stored_order, list):
        raise HTTPException(status_code=500, detail="Session trial order is invalid")
    if all(isinstance(item, str) for item in stored_order):
        return stored_order
    if not all(isinstance(item, int) for item in stored_order):
        raise HTTPException(status_code=500, detail="Session trial order is invalid")

    manifest = load_manifest()
    try:
        stable_order = [manifest[index]["sample_id"] for index in stored_order]
    except IndexError as error:
        raise HTTPException(
            status_code=409,
            detail="This legacy session cannot be resumed because the manifest changed.",
        ) from error
    with get_connection() as connection:
        connection.execute(
            "UPDATE sessions SET trial_order = ? WHERE session_id = ?",
            (json.dumps(stable_order), session["session_id"]),
        )
    return stable_order


def validate_response(study_id: str, request: ResponseRequest) -> tuple[dict, dict]:
    try:
        plays = SingleAudioPlayCounts.model_validate(request.play_counts)
        if study_id == "pilot_quality":
            answers = PilotQualityAnswers.model_validate(request.answers)
        elif study_id == "c1_descriptors":
            answers = C1DescriptorAnswers.model_validate(request.answers)
        else:
            raise HTTPException(status_code=404, detail="Study not found")
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors()) from error
    validated_answers = answers.model_dump()
    validated_answers["comment"] = validated_answers.get("comment", "").strip()
    return validated_answers, plays.model_dump()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/studies")
def studies() -> list[dict[str, Any]]:
    manifest_count = len(load_manifest())
    result = []
    for study_id in STUDY_CONFIGS:
        config = load_study(study_id)
        trial_limit = config.get("trial_limit")
        config["total_trials"] = min(trial_limit or manifest_count, manifest_count)
        result.append(config)
    return result


@app.get("/api/study/{study_id}")
def study(study_id: str) -> dict[str, Any]:
    config = load_study(study_id)
    manifest_count = len(load_manifest())
    trial_limit = config.get("trial_limit")
    config["total_trials"] = min(trial_limit or manifest_count, manifest_count)
    return config


@app.post("/api/session/start")
def start_session(request: StartSessionRequest) -> dict[str, Any]:
    study_id = canonical_study_id(request.study_id)
    config = load_study(study_id)
    sample_ids = [row["sample_id"] for row in load_manifest()]
    random.SystemRandom().shuffle(sample_ids)
    trial_limit = config.get("trial_limit")
    if trial_limit:
        sample_ids = sample_ids[:trial_limit]

    participant_id = f"P_{secrets.token_hex(3).upper()}"
    session_id = f"S_{secrets.token_hex(3).upper()}"
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO sessions (session_id, participant_id, study_id, trial_order, started_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, participant_id, study_id, json.dumps(sample_ids), now()),
        )
    return {
        "session_id": session_id,
        "participant_id": participant_id,
        "study_id": study_id,
        "total_trials": len(sample_ids),
    }


@app.get("/api/session/{session_id}/trial")
def current_trial(session_id: str) -> dict[str, Any]:
    session = get_session(session_id)
    order = get_stable_trial_ids(session)
    current_index = session["current_index"]
    if current_index >= len(order):
        return {
            "completed": True,
            "study_id": canonical_study_id(session["study_id"]),
            "progress": {"current": len(order), "total": len(order)},
        }

    sample_id = order[current_index]
    if sample_id not in manifest_by_sample_id():
        raise HTTPException(
            status_code=409,
            detail="This session cannot continue because a saved sample is no longer in the manifest.",
        )
    return {
        "completed": False,
        "study_id": canonical_study_id(session["study_id"]),
        "trial": {
            "trial_id": sample_id,
            "sample_id": sample_id,
            "trial_order": current_index + 1,
            "audio_sources": [
                {
                    "id": "sample",
                    "label": "Audio sample",
                    "audio_url": f"/api/audio/{sample_id}",
                }
            ],
        },
        "progress": {"current": current_index + 1, "total": len(order)},
    }


@app.post("/api/session/{session_id}/response")
def submit_response(session_id: str, request: ResponseRequest) -> dict[str, bool]:
    session = get_session(session_id)
    study_id = canonical_study_id(session["study_id"])
    order = get_stable_trial_ids(session)
    current_index = session["current_index"]
    if current_index >= len(order) or request.trial_id != order[current_index]:
        raise HTTPException(status_code=409, detail="This trial is no longer current")

    answers, play_counts = validate_response(study_id, request)
    sample_id = order[current_index]
    submitted_at = now()
    try:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO study_responses (
                    participant_id, session_id, study_id, trial_id, sample_id,
                    trial_order, answers_json, play_counts_json, started_at, submitted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session["participant_id"],
                    session_id,
                    study_id,
                    request.trial_id,
                    sample_id,
                    current_index + 1,
                    json.dumps(answers),
                    json.dumps(play_counts),
                    request.started_at.isoformat(),
                    submitted_at,
                ),
            )
            next_index = current_index + 1
            completed_at = submitted_at if next_index == len(order) else None
            connection.execute(
                "UPDATE sessions SET current_index = ?, completed_at = ? WHERE session_id = ?",
                (next_index, completed_at, session_id),
            )
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="Response already submitted") from error
    return {"saved": True, "completed": current_index + 1 == len(order)}


@app.get("/api/audio/{sample_id}")
def audio(sample_id: str) -> FileResponse:
    row = manifest_by_sample_id().get(sample_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Audio not found")
    audio_path = ROOT / Path(row["audio_path"].replace("\\", "/"))
    if not audio_path.is_file():
        raise HTTPException(status_code=404, detail="Audio file missing")
    return FileResponse(audio_path, media_type="audio/wav", filename="sample.wav")


def build_export(study_id: str | None) -> StreamingResponse:
    canonical = canonical_study_id(study_id) if study_id else None
    query = "SELECT * FROM study_responses"
    parameters: tuple[str, ...] = ()
    if canonical:
        query += " WHERE study_id = ?"
        parameters = (canonical,)
    query += " ORDER BY submitted_at"
    with get_connection() as connection:
        database_rows = connection.execute(query, parameters).fetchall()

    rows = []
    answer_columns: set[str] = set()
    play_columns: set[str] = set()
    for database_row in database_rows:
        answers = json.loads(database_row["answers_json"])
        plays = json.loads(database_row["play_counts_json"])
        answer_columns.update(answers)
        play_columns.update(plays)
        rows.append((database_row, answers, plays))

    base_columns = [
        "participant_id",
        "session_id",
        "study_id",
        "trial_id",
        "sample_id",
        "trial_order",
        "started_at",
        "submitted_at",
    ]
    fieldnames = base_columns + sorted(answer_columns) + [
        f"play_count_{column}" for column in sorted(play_columns)
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for database_row, answers, plays in rows:
        row = {column: database_row[column] for column in base_columns}
        row.update(answers)
        row.update({f"play_count_{key}": value for key, value in plays.items()})
        writer.writerow(row)
    filename = f"{canonical or 'all_studies'}_responses.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/api/admin/export")
def export_all_responses() -> StreamingResponse:
    return build_export(None)


@app.get("/api/admin/export/{study_id}")
def export_study_responses(study_id: str) -> StreamingResponse:
    return build_export(study_id)
