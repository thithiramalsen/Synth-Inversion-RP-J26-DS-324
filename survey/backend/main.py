import csv
import io
import json
import random
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from database import get_connection, initialize_database
from models import ResponseRequest, StartSessionRequest


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "data" / "manifests" / "pilot_v1.csv"
CONFIG_PATH = ROOT / "survey" / "config" / "pilot_v1.json"

app = FastAPI(title="Synth Inversion Listening Survey")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_manifest() -> list[dict[str, str]]:
    with MANIFEST_PATH.open(newline="", encoding="utf-8-sig") as manifest_file:
        return list(csv.DictReader(manifest_file))


def get_session(session_id: str) -> sqlite3.Row:
    with get_connection() as connection:
        session = connection.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.on_event("startup")
def startup() -> None:
    initialize_database()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/study/{study_id}")
def study(study_id: str) -> dict:
    if study_id != "pilot_v1":
        raise HTTPException(status_code=404, detail="Study not found")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


@app.post("/api/session/start")
def start_session(request: StartSessionRequest) -> dict:
    if request.study_id != "pilot_v1":
        raise HTTPException(status_code=404, detail="Study not found")
    manifest = load_manifest()
    order = list(range(len(manifest)))
    random.SystemRandom().shuffle(order)
    participant_id = f"P_{secrets.token_hex(3).upper()}"
    session_id = f"S_{secrets.token_hex(3).upper()}"
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO sessions (session_id, participant_id, study_id, trial_order, started_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, participant_id, request.study_id, json.dumps(order), now()),
        )
    return {"session_id": session_id, "participant_id": participant_id, "total_trials": len(order)}


@app.get("/api/session/{session_id}/trial")
def current_trial(session_id: str) -> dict:
    session = get_session(session_id)
    order = json.loads(session["trial_order"])
    if session["current_index"] >= len(order):
        return {"completed": True, "progress": {"current": len(order), "total": len(order)}}
    manifest = load_manifest()
    manifest_index = order[session["current_index"]]
    return {
        "completed": False,
        "trial": {"trial_id": manifest_index, "sample_id": manifest[manifest_index]["sample_id"], "trial_order": session["current_index"] + 1},
        "audio_url": f"/api/audio/{manifest[manifest_index]['sample_id']}",
        "progress": {"current": session["current_index"] + 1, "total": len(order)},
    }


@app.post("/api/session/{session_id}/response")
def submit_response(session_id: str, request: ResponseRequest) -> dict:
    session = get_session(session_id)
    order = json.loads(session["trial_order"])
    current_index = session["current_index"]
    if current_index >= len(order) or request.trial_id != order[current_index]:
        raise HTTPException(status_code=409, detail="This trial is no longer current")
    manifest = load_manifest()
    submitted_at = now()
    try:
        with get_connection() as connection:
            connection.execute(
                "INSERT INTO responses (participant_id, session_id, trial_id, sample_id, trial_order, issue_type, quality_rating, comment, play_count, started_at, submitted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session["participant_id"], session_id, request.trial_id, manifest[request.trial_id]["sample_id"], current_index + 1, request.issue_type, request.quality_rating, request.comment.strip(), request.play_count, request.started_at, submitted_at),
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
    row = next((item for item in load_manifest() if item["sample_id"] == sample_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Audio not found")
    audio_path = ROOT / Path(row["audio_path"].replace("\\", "/"))
    if not audio_path.is_file():
        raise HTTPException(status_code=404, detail="Audio file missing")
    return FileResponse(audio_path, media_type="audio/wav", filename="sample.wav")


@app.get("/api/admin/export")
def export_responses() -> StreamingResponse:
    columns = ["participant_id", "session_id", "sample_id", "trial_order", "issue_type", "quality_rating", "comment", "play_count", "started_at", "submitted_at"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    with get_connection() as connection:
        for row in connection.execute(f"SELECT {', '.join(columns)} FROM responses ORDER BY submitted_at"):
            writer.writerow(dict(row))
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=responses.csv"})