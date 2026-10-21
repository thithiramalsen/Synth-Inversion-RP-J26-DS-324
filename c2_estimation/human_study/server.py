"""Loopback-only rehearsal server with an isolated SQLite database.

Deliberately not a public research deployment. Never mount the bundle directory:
it contains private identities, reliability scores and headphone answer keys.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from .design import CAP, CONSENT, NAMES, TARGET, VERSION, assignment

ROOT = Path(__file__).resolve().parents[2]
ASSETS = Path(__file__).with_name("web")
DEFAULT_BUNDLE = ROOT / "data/processed/c2_v4/human_study_bundle_v1"
DEFAULT_DB = ROOT / "data/processed/c2_v4/human_study_rehearsal_v1/responses.sqlite3"


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fail(message, code=400):
    raise HTTPException(code, message)


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    consent: dict[str, bool]
    experience: str


class Play(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    audio_id: str
    event: str


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int
    op: str
    answers: dict = Field(default_factory=dict)


class Store:
    def __init__(self, path, fingerprint):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL, state TEXT NOT NULL)")
            previous = db.execute("SELECT value FROM metadata WHERE key='fingerprint'").fetchone()
            if previous and previous[0] != fingerprint:
                raise ValueError("Study source/bundle changed. Use a fresh versioned rehearsal database; preserve previous data.")
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('fingerprint', ?)", (fingerprint,))
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('mode', 'rehearsal')")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute("PRAGMA secure_delete=ON")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def create_app(bundle_path=DEFAULT_BUNDLE, database=DEFAULT_DB):
    bundle_path = Path(bundle_path).resolve()
    manifest = json.loads((bundle_path / "manifest.json").read_text())
    for name, checksum in manifest["files"].items():
        candidate = (bundle_path / name).resolve()
        if not candidate.is_relative_to(bundle_path) or digest(candidate) != checksum:
            raise ValueError("Study bundle changed: " + name)
    bundle = json.loads((bundle_path / "bundle.json").read_text())
    if bundle["version"] != VERSION or bundle["test_evaluated"] is not False:
        raise ValueError("Wrong study bundle")
    cases = {case["case_id"]: case for case in bundle["cases"]}
    if set(cases) != {"practice", *[f"case_{i:02d}" for i in range(1, 9)]}:
        raise ValueError("Need exactly eight scored cases and separate practice")
    if bundle["assignments"] != [assignment(i) for i in range(TARGET)]:
        raise ValueError("Counterbalancing changed after bundle freeze")
    source_hashes = {p.name: digest(p) for p in sorted(Path(__file__).parent.glob("*.py"))}
    source_hashes.update({p.name: digest(p) for p in sorted(ASSETS.glob("*")) if p.is_file()})
    fingerprint = hashlib.sha256(json.dumps({"bundle": digest(bundle_path / "manifest.json"),
        "source": source_hashes}, sort_keys=True).encode()).hexdigest()
    store = Store(database, fingerprint)
    app = FastAPI(title="C2 study rehearsal", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store

    @app.middleware("http")
    async def local_guard(request: Request, call_next):
        # No CORS; validate Host as protection against DNS rebinding of local services.
        host = request.url.hostname
        if host not in {"127.0.0.1", "localhost", "testserver"}:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Local rehearsal only"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Cross-origin requests are not allowed"}, status_code=403)
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > 16000:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        result = await call_next(request)
        result.headers["Cache-Control"] = "no-store"
        result.headers["X-Content-Type-Options"] = "nosniff"
        result.headers["Referrer-Policy"] = "no-referrer"
        result.headers["Content-Security-Policy"] = "default-src 'self'; media-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return result

    def token_hash(authorization):
        if not authorization or not re.fullmatch(r"Bearer [a-f0-9]{64}", authorization):
            fail("Session not found. Use the same browser, or start a rehearsal.", 401)
        return hashlib.sha256(authorization[7:].encode()).hexdigest()

    def get_session(db, authorization):
        key = token_hash(authorization)
        row = db.execute("SELECT state FROM sessions WHERE token_hash=?", (key,)).fetchone()
        if not row:
            fail("No saved session in this browser", 401)
        return key, json.loads(row[0])

    def save(db, key, state):
        state["updated"] = now()
        db.execute("UPDATE sessions SET state=? WHERE token_hash=?", (json.dumps(state), key))

    def current(state):
        if state["phase"] == "practice":
            return "practice", "with"
        task = state["assignment"][len(state["responses"])]
        return task["case_id"], task["condition"]

    def allowed_audio(state):
        phase = state["phase"]
        if phase == "volume":
            return {"volume_reference": bundle["volume"]["path"]}
        if phase == "headphones":
            item = bundle["headphones"][len(state["headphone_answers"]) ]
            return {item["screen_id"]: item["path"]}
        if phase in {"practice", "task"}:
            case_id, _ = current(state)
            return {f"{case_id}_{label}": info["file"] for label, info in cases[case_id]["audio"].items()}
        return {}

    def public(state):
        result = {k: state[k] for k in ("code", "phase", "revision", "created")}
        result.update(mode="rehearsal", version=VERSION, scored_completed=len(state["responses"]),
                      excluded_from_research=True, played=state["playback"], audio_ids=list(allowed_audio(state)))
        if state["phase"] == "headphones":
            result["screen_number"] = len(state["headphone_answers"]) + 1
        if state["phase"] in {"practice", "task"}:
            case_id, condition = current(state)
            # Allowlist fields: never serve truth, errors, IDs, q for baseline, or future cases.
            fields = ("name", "label", "predicted_z", "q") if condition == "with" else ("name", "label", "predicted_z")
            result["case"] = {"case_id": case_id, "condition": condition,
                              "parameters": [{k: p[k] for k in fields} for p in cases[case_id]["parameters"]]}
        return result

    @app.get("/")
    def index():
        return FileResponse(ASSETS / "index.html")

    @app.get("/assets/{name}")
    def static(name: str):
        if name not in {"app.js", "style.css"}:
            fail("Not found", 404)
        return FileResponse(ASSETS / name)

    @app.get("/api/info")
    def info():
        return {"mode": "rehearsal", "version": VERSION, "target": TARGET, "cap": CAP,
                "research_collection_enabled": False, "fingerprint": fingerprint}

    @app.post("/api/start")
    def start(body: Start, authorization: str | None = Header(default=None)):
        if set(body.consent) != set(CONSENT) or not all(body.consent.values()):
            fail("All eligibility and consent statements must be confirmed; otherwise please stop.")
        if body.experience not in {"under_1", "1_to_3", "over_3"}:
            fail("Choose an experience range")
        key = token_hash(authorization)
        with store.connect() as db:
            existing = db.execute("SELECT state FROM sessions WHERE token_hash=?", (key,)).fetchone()
            if existing:
                return public(json.loads(existing[0]))
            sessions = [json.loads(r[0]) for r in db.execute("SELECT state FROM sessions")]
            if len(sessions) >= CAP:
                fail("This rehearsal has reached its 16-enrolment cap. The researcher must start a new rehearsal database.", 409)
            occupied = {s["slot"] for s in sessions if s["phase"] not in {"withdrawn", "screen_failed"}}
            slots = [i for i in range(TARGET) if i not in occupied]
            if not slots:
                fail("All 12 assignment slots are in use", 409)
            slot = slots[0]
            state = {"code": "C2-R-" + secrets.token_hex(5).upper(), "created": now(), "updated": now(),
                     "consent_version": VERSION, "consent": body.consent, "experience": body.experience,
                     "mode": "rehearsal", "fingerprint": fingerprint, "slot": slot, "assignment": assignment(slot),
                     "phase": "volume", "revision": 0, "responses": [], "headphone_answers": [], "playback": {},
                     "excluded_from_research": True, "stage_started": now()}
            db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (key, state["code"], json.dumps(state)))
            return public(state)

    @app.get("/api/session")
    def session(authorization: str | None = Header(default=None)):
        with store.connect() as db:
            _, state = get_session(db, authorization)
            return public(state)

    @app.get("/api/audio/{audio_id}")
    def audio(audio_id: str, authorization: str | None = Header(default=None)):
        with store.connect() as db:
            _, state = get_session(db, authorization)
            permitted = allowed_audio(state)
            if audio_id not in permitted:
                fail("Audio is not part of the current task", 403)
            path = bundle_path / "audio" / permitted[audio_id]
            return FileResponse(path, media_type="audio/wav")

    @app.post("/api/play")
    def play(body: Play, authorization: str | None = Header(default=None)):
        with store.connect() as db:
            key, state = get_session(db, authorization)
            if body.audio_id not in allowed_audio(state) or body.event not in {"start", "end"}:
                fail("Invalid playback event")
            counts = state["playback"].setdefault(body.audio_id, {"start": 0, "end": 0})
            if body.event == "end" and counts["end"] >= counts["start"]:
                fail("Playback has not started")
            counts[body.event] = min(counts[body.event] + 1, 1000)
            save(db, key, state)
            return {"saved": True}

    def listened(state):
        if any(state["playback"].get(a, {}).get("end", 0) < 1 for a in allowed_audio(state)):
            fail("Please listen to each clip all the way through once. Replays are welcome.")

    def response(answers, condition):
        required = {"decisions", "usefulness", "clarity", "confidence", "reason"}
        if condition == "with":
            required |= {"meaning", "guarantee", "impossible"}
        if set(answers) != required:
            fail("The response fields do not match this display condition")
        decisions = answers["decisions"]
        if not isinstance(decisions, dict) or set(decisions) != set(NAMES) or any(not isinstance(v, str) or v not in {"retain", "check", "cannot_judge"} for v in decisions.values()):
            fail("Please choose an action for every control; Cannot judge is a valid answer.")
        for field in ("usefulness", "clarity", "confidence"):
            value = answers[field]
            if value != "cannot_judge" and not (type(value) is int and 1 <= value <= 5):
                fail("Choose a rating from 1 to 5, or Cannot judge")
        for field in ({"reason", "meaning"} if condition == "with" else {"reason"}):
            value = answers[field]
            if not isinstance(value, str) or len(value) > 1000 or (field == "meaning" and not value.strip()):
                fail("Use up to 1,000 characters; I do not know is a valid meaning response.")
        if condition == "with" and any(not isinstance(answers[f], str) or answers[f] not in {"yes", "no", "unsure"} for f in ("guarantee", "impossible")):
            fail("Please answer both understanding questions")

    @app.post("/api/action")
    def action(body: Action, authorization: str | None = Header(default=None)):
        with store.connect() as db:
            key, state = get_session(db, authorization)
            if body.revision != state["revision"]:
                fail("This step was already saved or changed. Reload to continue.", 409)
            phase, answers = state["phase"], body.answers
            if body.op == "withdraw":
                if phase == "withdrawn":
                    return public(state)
                # Remove linked answers from active storage; preserve only minimal consent/withdrawal audit.
                for field in ("experience", "practice_response", "feedback"):
                    state.pop(field, None)
                state.update(phase="withdrawn", withdrawn=now(), responses=[], headphone_answers=[], playback={})
            elif body.op == "volume" and phase == "volume":
                if answers != {"headphones": True, "quiet": True, "comfortable": True}:
                    fail("Confirm headphones, a quiet place and comfortable volume")
                listened(state)
                state["phase"] = "headphones"
            elif body.op == "headphone" and phase == "headphones":
                if set(answers) != {"interval"} or type(answers["interval"]) is not int or answers["interval"] not in {1, 2, 3}:
                    fail("Choose the quietest of the three tones")
                listened(state)
                item = bundle["headphones"][len(state["headphone_answers"])]
                state["headphone_answers"].append({"interval": answers["interval"], "correct": answers["interval"] == item["correct_interval"]})
                if len(state["headphone_answers"]) == 6:
                    state["phase"] = "practice" if sum(a["correct"] for a in state["headphone_answers"]) >= 5 else "screen_failed"
            elif body.op == "response" and phase in {"practice", "task"}:
                listened(state)
                case_id, condition = current(state)
                response(answers, condition)
                record = {"case_id": case_id, "condition": condition, "answers": answers,
                          "started": state["stage_started"], "submitted": now()}
                if phase == "practice":
                    state["practice_response"] = record
                    state["phase"] = "instructions"
                else:
                    record["position"] = len(state["responses"]) + 1
                    state["responses"].append(record)
                    state["phase"] = "feedback" if len(state["responses"]) == 8 else ("break" if len(state["responses"]) == 4 else "task")
            elif body.op == "continue" and phase in {"instructions", "break"} and not answers:
                state["phase"] = "task"
            elif body.op == "finish" and phase == "feedback":
                if set(answers) != {"preference", "length", "comment"} or not isinstance(answers["preference"], str) or answers["preference"] not in {"with", "without", "none", "cannot_judge"} or not isinstance(answers["length"], str) or answers["length"] not in {"about_right", "too_long", "could_be_longer"}:
                    fail("Please choose a display preference and session length")
                if not isinstance(answers["comment"], str) or len(answers["comment"]) > 1000:
                    fail("Comments must be at most 1,000 characters")
                state.update(phase="complete", feedback=answers, completed=now())
            else:
                fail("This action is not available at this stage", 409)
            state["revision"] += 1
            state["stage_started"] = now()
            save(db, key, state)
            return public(state)

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    import uvicorn
    print("C2 REHEARSAL ONLY. Research collection is disabled. Existing studies are not connected.", flush=True)
    uvicorn.run(create_app(args.bundle, args.database), host="127.0.0.1", port=args.port, access_log=False)
