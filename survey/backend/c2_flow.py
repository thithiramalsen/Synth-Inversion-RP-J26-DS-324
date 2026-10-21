"""Hosted C2 rehearsal flow, adapted from the frozen local human-study server.

Never mount the private bundle directory. C1/C4 source and records are untouched.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from c2_design import CAP, CONSENT, NAMES, TARGET, VERSION, assignment
from database import get_connection
from security import require_admin, SESSION_COOKIE

ROOT = Path(__file__).resolve().parents[2]
ASSETS = Path(__file__).with_name("c2_web")
DEFAULT_BUNDLE = ROOT / "survey/deploy/study/c2_rehearsal_v1"


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
    invitation: str = Field(default="", max_length=150)
    purpose: str = "participant_preview"


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
    def __init__(self, fingerprint):
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL, state TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS c2_v1_invites (invite_hash TEXT PRIMARY KEY, slot INTEGER UNIQUE NOT NULL, token_hash TEXT UNIQUE, created_by TEXT NOT NULL, created_at TEXT NOT NULL)")
            previous = db.execute("SELECT value FROM metadata WHERE key='fingerprint'").fetchone()
            if previous and previous[0] != fingerprint:
                raise ValueError("Study source/bundle changed. Use a fresh versioned rehearsal database; preserve previous data.")
            db.execute("INSERT INTO metadata VALUES ('fingerprint', ?) ON CONFLICT(key) DO NOTHING", (fingerprint,))
            db.execute("INSERT INTO metadata VALUES ('mode', 'rehearsal') ON CONFLICT(key) DO NOTHING")

    @contextmanager
    def connect(self):
        with get_connection() as shared:
            # SQL is owned by this module, not supplied by the caller. Namespacing
            # prevents even accidental access to the historical/C1/C4 tables.
            class Scoped:
                def execute(self, sql, parameters=()):
                    sql = re.sub(r"\bmetadata\b", "c2_v1_metadata", sql)
                    sql = re.sub(r"\bsessions\b", "c2_v1_sessions", sql)
                    return shared.execute(sql, parameters)
            db = Scoped()
            db.execute("BEGIN IMMEDIATE")
            yield db


def create_app(bundle_path=DEFAULT_BUNDLE):
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
    # Explicit hosted protocol identity: cosmetic UI updates do not invalidate
    # saved sessions. Changes to selection, questions or flow require v2 tables.
    fingerprint = hashlib.sha256(json.dumps({"bundle": digest(bundle_path / "manifest.json"),
        "protocol": "c2-hosted-rehearsal-v1"}, sort_keys=True).encode()).hexdigest()
    store = Store(fingerprint)
    app = FastAPI(title="C2 study rehearsal", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store

    @app.middleware("http")
    async def same_origin_guard(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Cross-origin requests are not allowed"}, status_code=403)
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > 16000 or (request.method == "POST" and "content-length" not in request.headers):
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

    def get_session(db, authorization, request):
        key = token_hash(authorization)
        row = db.execute("SELECT state FROM sessions WHERE token_hash=?", (key,)).fetchone()
        if not row:
            fail("No saved session in this browser", 401)
        state = json.loads(row[0])
        if state["purpose"] == "researcher_self_review" and researcher(request) != state["researcher"]:
            fail("This self-review belongs to another researcher", 403)
        return key, state

    def researcher(request):
        return require_admin(authorization=request.headers.get("authorization", ""),
                             researcher_session=request.cookies.get(SESSION_COOKIE))

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
                      excluded_from_research=True, purpose=state["purpose"], played=state["playback"], audio_ids=list(allowed_audio(state)))
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
    def index(request: Request, view: str = "participant"):
        if view == "researcher":
            researcher(request)
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        if view == "researcher":
            html = html.replace("PARTICIPANT PREVIEW · Research collection disabled", "RESEARCHER SELF-REVIEW · Excluded from participant findings")
        return HTMLResponse(html)

    @app.get("/assets/{name}")
    def static(name: str):
        if name not in {"app.js", "style.css", "preview.js"}:
            fail("Not found", 404)
        return FileResponse(ASSETS / name)

    @app.get("/api/info")
    def info():
        return {"mode": "rehearsal", "version": VERSION, "target": TARGET, "cap": CAP,
                "research_collection_enabled": False, "fingerprint": fingerprint}

    @app.post("/api/start")
    def start(body: Start, request: Request, authorization: str | None = Header(default=None)):
        if body.purpose not in {"participant_preview", "researcher_self_review"}:
            fail("Unknown C2 view")
        actor = researcher(request) if body.purpose == "researcher_self_review" else None
        only_researchers = os.environ.get("SURVEY_C2_RESEARCHER_ONLY") == "1"
        if only_researchers != (actor is not None):
            fail("Use the matching C2 view on this deployment", 403)
        if set(body.consent) != set(CONSENT) or not all(body.consent.values()):
            fail("All eligibility and consent statements must be confirmed; otherwise please stop.")
        if body.experience not in {"under_1", "1_to_3", "over_3"}:
            fail("Choose an experience range")
        key = token_hash(authorization)
        with store.connect() as db:
            existing = db.execute("SELECT state FROM sessions WHERE token_hash=?", (key,)).fetchone()
            if existing:
                _, state = get_session(db, authorization, request)
                return public(state)
            sessions = [json.loads(r[0]) for r in db.execute("SELECT state FROM sessions")]
            if actor is None:
                checksum = hashlib.sha256(body.invitation.strip().encode()).hexdigest()
                invite = db.execute("SELECT slot FROM c2_v1_invites WHERE invite_hash=? AND token_hash IS NULL", (checksum,)).fetchone()
                if not invite:
                    fail("This C2 invitation is invalid or already used. Resume on the original browser.", 403)
                slot = invite[0]
                claimed = db.execute("UPDATE c2_v1_invites SET token_hash=? WHERE invite_hash=? AND token_hash IS NULL", (key, checksum))
                if claimed.rowcount != 1:
                    fail("Invitation already used", 409)
            else:
                own = [s for s in sessions if s.get("researcher") == actor]
                if len(own) >= 48:
                    fail("Self-review rehearsal limit reached", 409)
                slot = len(own) % TARGET
            state = {"code": "C2-R-" + secrets.token_hex(5).upper(), "created": now(), "updated": now(),
                     "consent_version": VERSION, "consent": body.consent, "experience": body.experience,
                     "mode": "rehearsal", "fingerprint": fingerprint, "slot": slot, "assignment": assignment(slot),
                     "phase": "volume", "revision": 0, "responses": [], "headphone_answers": [], "playback": {},
                     "excluded_from_research": True, "stage_started": now()}
            state.update(purpose=body.purpose, researcher=actor)
            db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (key, state["code"], json.dumps(state)))
            return public(state)

    @app.get("/api/session")
    def session(request: Request, authorization: str | None = Header(default=None)):
        with store.connect() as db:
            _, state = get_session(db, authorization, request)
            return public(state)

    @app.get("/api/audio/{audio_id}")
    def audio(audio_id: str, request: Request, authorization: str | None = Header(default=None)):
        with store.connect() as db:
            _, state = get_session(db, authorization, request)
            permitted = allowed_audio(state)
            if audio_id not in permitted:
                fail("Audio is not part of the current task", 403)
            path = bundle_path / "audio" / permitted[audio_id]
            return FileResponse(path, media_type="audio/wav")

    @app.post("/api/play")
    def play(body: Play, request: Request, authorization: str | None = Header(default=None)):
        with store.connect() as db:
            key, state = get_session(db, authorization, request)
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
    def action(body: Action, request: Request, authorization: str | None = Header(default=None)):
        with store.connect() as db:
            key, state = get_session(db, authorization, request)
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

    practice = cases["practice"]

    @app.get("/walkthrough")
    def walkthrough():
        return FileResponse(ASSETS / "walkthrough.html")

    @app.get("/api/walkthrough")
    def practice_case():
        return {"responses_saved": False, "parameters": [{k: p[k] for k in ("name", "label", "predicted_z", "q")} for p in practice["parameters"]]}

    @app.get("/api/walkthrough/audio/{kind}")
    def practice_audio(kind: str):
        if kind not in {"target", "predicted"}:
            fail("Not found", 404)
        return FileResponse(bundle_path / "audio" / practice["audio"][kind]["file"], media_type="audio/wav")

    app.state.fingerprint = fingerprint
    return app
