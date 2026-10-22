"""Loopback-only C3 study rehearsal server with an isolated SQLite database.

Deliberately not a public research deployment; research collection is disabled in code.
Never mount the bundle directory: it holds sample IDs, which set came from which method,
and the headphone answer keys. Participants only ever see "Set A" and "Set B".

Usage (repository root):
    python -B -m c3_recommendation.human_study.server        then open http://127.0.0.1:8767/
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .design import (
    CAP, CLOSENESS, CONSENT, MAX_SCREEN_ATTEMPTS, N_SCORED, OPERATING_POINT, SET_CHOICES, SET_QUESTIONS, TARGET,
    VERSION, assignment,
)

ROOT = Path(__file__).resolve().parents[2]
ASSETS = Path(__file__).with_name("web")
DEFAULT_BUNDLE = ROOT / "data/processed/c3_v4/human_study_bundle_v2"
DEFAULT_DB = ROOT / "data/processed/c3_v4/human_study_rehearsal_v2/responses.sqlite3"
PRACTICE_SET_A = "topk"
EXPERIENCE = {"under_1", "1_to_3", "over_3"}


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


def screen_attempt(state):
    """1-based number of the current (or last) headphone-check attempt."""
    return len(state.get("screen_history", [])) + 1


def protocol():
    """The participant-facing study rules from design.py, as values (not file bytes)."""
    return {"version": VERSION, "target": TARGET, "cap": CAP, "n_scored": N_SCORED, "consent": list(CONSENT),
            "closeness": list(CLOSENESS), "set_choices": list(SET_CHOICES), "set_questions": list(SET_QUESTIONS),
            "operating_point": OPERATING_POINT, "max_screen_attempts": MAX_SCREEN_ATTEMPTS, "assignments": [assignment(i) for i in range(TARGET)]}


def membership(case):
    """Private per-sound label for analysis: in both sets, top-k only or C3 only."""
    top, mmr = set(case["sets"]["topk"]), set(case["sets"]["mmr"])
    return {str(s["number"]): "both" if s["number"] in top and s["number"] in mmr
            else ("topk_only" if s["number"] in top else "mmr_only") for s in case["sounds"]}


def create_app(bundle_path=DEFAULT_BUNDLE, database=DEFAULT_DB):
    bundle_path = Path(bundle_path).resolve()
    manifest = json.loads((bundle_path / "manifest.json").read_text(encoding="utf-8"))
    for name, checksum in manifest["files"].items():
        candidate = (bundle_path / name).resolve()
        if not candidate.is_relative_to(bundle_path) or digest(candidate) != checksum:
            raise ValueError("Study bundle changed: " + name)
    bundle = json.loads((bundle_path / "bundle.json").read_text(encoding="utf-8"))
    if bundle["version"] != VERSION or bundle["test_evaluated"] is not False:
        raise ValueError("Wrong study bundle")
    cases = {case["case_id"]: case for case in bundle["cases"]}
    if set(cases) != {"practice", *[f"case_{i:02d}" for i in range(1, N_SCORED + 1)]}:
        raise ValueError("Need exactly eight scored cases and a separate practice case")
    if bundle["assignments"] != [assignment(i) for i in range(TARGET)]:
        raise ValueError("Counterbalancing changed after bundle freeze")
    # Fingerprint only what participants experience: this server, the web page, the frozen
    # bundle and the study protocol. Analysis/export code can change without a new database.
    source_hashes = {"server.py": digest(__file__)}
    source_hashes.update({p.name: digest(p) for p in sorted(ASSETS.glob("*")) if p.is_file()})
    fingerprint = hashlib.sha256(json.dumps({"bundle": digest(bundle_path / "manifest.json"),
                                             "source": source_hashes, "protocol": protocol()},
                                            sort_keys=True).encode()).hexdigest()
    store = Store(database, fingerprint)
    app = FastAPI(title="C3 study rehearsal", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store

    @app.middleware("http")
    async def local_guard(request: Request, call_next):
        # No CORS; validate Host as protection against DNS rebinding of local services.
        if request.url.hostname not in {"127.0.0.1", "localhost", "testserver"}:
            return JSONResponse({"detail": "Local rehearsal only"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Cross-origin requests are not allowed"}, status_code=403)
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > 16000:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        result = await call_next(request)
        result.headers["Cache-Control"] = "no-store"
        result.headers["X-Content-Type-Options"] = "nosniff"
        result.headers["Referrer-Policy"] = "no-referrer"
        result.headers["Content-Security-Policy"] = (
            "default-src 'self'; media-src 'self' blob:; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
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
            return "practice", PRACTICE_SET_A
        task = state["assignment"][len(state["responses"])]
        return task["case_id"], task["set_a"]

    def allowed_audio(state):
        phase = state["phase"]
        if phase == "volume":
            return {"volume_reference": bundle["volume"]["path"]}
        if phase == "headphones":
            item = bundle["headphones"][len(state["headphone_answers"])]
            return {item["screen_id"]: item["path"]}
        if phase in {"practice", "task"}:
            case_id, _ = current(state)
            case = cases[case_id]
            permitted = {f"{case_id}_target": case["target_audio"]["file"]}
            permitted.update({s["sound_id"]: s["audio"]["file"] for s in case["sounds"]})
            return permitted
        return {}

    def public(state):
        result = {k: state[k] for k in ("code", "phase", "revision", "created")}
        result.update(mode="rehearsal", version=VERSION, scored_completed=len(state["responses"]),
                      total_cases=N_SCORED, excluded_from_research=True, played=state["playback"],
                      audio_ids=list(allowed_audio(state)), parameter_labels=bundle["parameter_labels"])
        if state["phase"] == "headphones":
            result["screen_number"] = len(state["headphone_answers"]) + 1
        result["screen_attempt"] = screen_attempt(state)
        result["screen_attempts_left"] = MAX_SCREEN_ATTEMPTS - screen_attempt(state)
        if state["phase"] in {"practice", "task"}:
            case_id, set_a = current(state)
            case = cases[case_id]
            set_b = "mmr" if set_a == "topk" else "topk"
            # Allowlist: never reveal methods, sample IDs, relevance, ranks or target settings.
            result["case"] = {
                "case_id": case_id, "target_audio_id": f"{case_id}_target",
                "sounds": [{"sound_id": s["sound_id"], "number": s["number"], "params": s["params"]}
                           for s in case["sounds"]],
                "sets": {"A": case["sets"][set_a], "B": case["sets"][set_b]},
            }
        return result

    def listened(state):
        if any(state["playback"].get(a, {}).get("end", 0) < 1 for a in allowed_audio(state)):
            fail("Please listen to each sound all the way through once. Replays are welcome.")

    def rating_ok(value):
        return value == "cannot_judge" or (type(value) is int and value in CLOSENESS)

    def check_response(answers, case):
        required = {"closeness", *SET_QUESTIONS, "confidence", "reason"}
        if set(answers) != required:
            fail("The response fields do not match this case")
        numbers = {str(s["number"]) for s in case["sounds"]}
        closeness = answers["closeness"]
        if not isinstance(closeness, dict) or set(closeness) != numbers or not all(rating_ok(v) for v in closeness.values()):
            fail("Please rate how close every sound is to the target; Cannot judge is a valid answer.")
        for question in SET_QUESTIONS:
            if not isinstance(answers[question], str) or answers[question] not in SET_CHOICES:
                fail("Please answer all three Set A / Set B questions; No difference and Cannot judge are valid.")
        if not rating_ok(answers["confidence"]):
            fail("Choose a confidence from 1 to 5, or Cannot judge")
        if not isinstance(answers["reason"], str) or len(answers["reason"]) > 1000:
            fail("Use up to 1,000 characters")

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
                "research_collection_enabled": False, "operating_point": bundle["operating_point"]["status"],
                "fingerprint": fingerprint}

    @app.post("/api/start")
    def start(body: Start, authorization: str | None = Header(default=None)):
        if set(body.consent) != set(CONSENT) or not all(body.consent.values()):
            fail("All eligibility and consent statements must be confirmed; otherwise please stop.")
        if body.experience not in EXPERIENCE:
            fail("Choose an experience range")
        key = token_hash(authorization)
        with store.connect() as db:
            existing = db.execute("SELECT state FROM sessions WHERE token_hash=?", (key,)).fetchone()
            if existing:
                return public(json.loads(existing[0]))
            sessions = [json.loads(r[0]) for r in db.execute("SELECT state FROM sessions")]
            if len(sessions) >= CAP:
                fail(f"This rehearsal has reached its {CAP}-enrolment cap. Start a new rehearsal database.", 409)
            # A failed setup check keeps its slot while it may still retry.
            occupied = {s["slot"] for s in sessions if s["phase"] != "withdrawn"
                        and not (s["phase"] == "screen_failed" and screen_attempt(s) >= MAX_SCREEN_ATTEMPTS)}
            slots = [i for i in range(TARGET) if i not in occupied]
            if not slots:
                fail(f"All {TARGET} assignment slots are in use", 409)
            slot = slots[0]
            state = {"code": "C3-R-" + secrets.token_hex(5).upper(), "created": now(), "updated": now(),
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
                fail("Audio is not part of the current step", 403)
            return FileResponse(bundle_path / "audio" / permitted[audio_id], media_type="audio/wav")

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
                # Remove linked answers from active storage; keep only a minimal consent/withdrawal audit.
                for field in ("experience", "practice_response", "feedback"):
                    state.pop(field, None)
                state.update(phase="withdrawn", withdrawn=now(), responses=[], headphone_answers=[], playback={},
                             screen_history=[])
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
                state["headphone_answers"].append({"interval": answers["interval"],
                                                   "correct": answers["interval"] == item["correct_interval"]})
                if len(state["headphone_answers"]) == 6:
                    passed = sum(a["correct"] for a in state["headphone_answers"]) >= 5
                    state["phase"] = "practice" if passed else "screen_failed"
            elif body.op == "retry_screen" and phase == "screen_failed" and not answers:
                if screen_attempt(state) >= MAX_SCREEN_ATTEMPTS:
                    fail(f"The setup check can be tried at most {MAX_SCREEN_ATTEMPTS} times", 409)
                # Keep the failed attempt for the record; replay is required again from the volume step.
                state.setdefault("screen_history", []).append(
                    {"attempt": screen_attempt(state), "answers": state["headphone_answers"], "ended": now()})
                state.update(phase="volume", headphone_answers=[], playback={})
            elif body.op == "response" and phase in {"practice", "task"}:
                listened(state)
                case_id, set_a = current(state)
                check_response(answers, cases[case_id])
                record = {"case_id": case_id, "set_a": set_a, "membership": membership(cases[case_id]),
                          "answers": answers, "started": state["stage_started"], "submitted": now()}
                if phase == "practice":
                    state["practice_response"] = record
                    state["phase"] = "instructions"
                else:
                    record["position"] = len(state["responses"]) + 1
                    state["responses"].append(record)
                    done = len(state["responses"])
                    state["phase"] = "feedback" if done == N_SCORED else ("break" if done == N_SCORED // 2 else "task")
            elif body.op == "continue" and phase in {"instructions", "break"} and not answers:
                state["phase"] = "task"
            elif body.op == "finish" and phase == "feedback":
                if set(answers) != {"knob_bars", "length", "comment"} or not rating_ok(answers["knob_bars"]) \
                        or not isinstance(answers["length"], str) or answers["length"] not in {"about_right", "too_long", "could_be_longer"}:
                    fail("Please rate the knob bars and choose a session length")
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
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    import uvicorn
    print("C3 REHEARSAL ONLY. Research collection is disabled. Existing studies are not connected.", flush=True)
    print(f"Open http://127.0.0.1:{args.port}/  (Ctrl+C to stop)", flush=True)
    uvicorn.run(create_app(args.bundle, args.database), host="127.0.0.1", port=args.port, access_log=False)
