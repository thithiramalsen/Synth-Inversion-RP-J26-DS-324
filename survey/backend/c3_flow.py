"""Hosted C3 rehearsal (blinded top-k vs C3 set comparison), mounted at /c3 on the shared service.

Adapted from c3_recommendation/human_study/server.py using the hosted C2 patterns:
- own tables (c3_v2_*) in the shared database; C1/C2/C4 tables are never touched;
- participant previews need a C3 invitation code (stored in the shared encrypted vault);
- signed-in researchers may run self-reviews, and only they may skip the headphone check
  (marked and excluded from analysis);
- research collection is disabled: every record is rehearsal data.
Never mount the bundle directory: bundle.json holds sample IDs, which set is which, and
headphone answer keys.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from c3_design import (
    CAP, CLOSENESS, CONSENT, MAX_SCREEN_ATTEMPTS, N_SCORED, OPERATING_POINT, SET_CHOICES, SET_QUESTIONS, TARGET,
    VERSION, assignment,
)
from database import get_connection
from invitation_codes import recover_code, remember_code
from security import SESSION_COOKIE, require_admin

ROOT = Path(__file__).resolve().parents[2]
ASSETS = Path(__file__).with_name("c3_web")
DEFAULT_BUNDLE = ROOT / "survey/deploy/study/c3_rehearsal_v2"
PROTOCOL = "c3-hosted-rehearsal-v2"
PRACTICE_SET_A = "topk"
EXPERIENCE = {"under_1", "1_to_3", "over_3"}
SELF_REVIEW_LIMIT = 48
TABLES = {"metadata": "c3_v2_metadata", "sessions": "c3_v2_sessions"}


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
            db.execute("CREATE TABLE IF NOT EXISTS c3_v2_invites (invite_hash TEXT PRIMARY KEY, slot INTEGER UNIQUE NOT NULL, "
                       "token_hash TEXT UNIQUE, created_by TEXT NOT NULL, created_at TEXT NOT NULL)")
            previous = db.execute("SELECT value FROM metadata WHERE key='fingerprint'").fetchone()
            if previous and previous[0] != fingerprint:
                raise ValueError("C3 study source/bundle changed. Use new versioned tables; preserve previous data.")
            db.execute("INSERT INTO metadata VALUES ('fingerprint', ?) ON CONFLICT(key) DO NOTHING", (fingerprint,))
            db.execute("INSERT INTO metadata VALUES ('mode', 'rehearsal') ON CONFLICT(key) DO NOTHING")

    @contextmanager
    def connect(self):
        with get_connection() as shared:
            # SQL is owned by this module. Namespacing keeps C3 away from every other table.
            class Scoped:
                def execute(self, sql, parameters=()):
                    for plain, scoped in TABLES.items():
                        sql = re.sub(rf"\b{plain}\b", scoped, sql)
                    return shared.execute(sql, parameters)
            db = Scoped()
            db.execute("BEGIN IMMEDIATE")
            yield db


def protocol():
    return {"version": VERSION, "target": TARGET, "cap": CAP, "n_scored": N_SCORED, "consent": list(CONSENT),
            "closeness": list(CLOSENESS), "set_choices": list(SET_CHOICES), "set_questions": list(SET_QUESTIONS),
            "operating_point": OPERATING_POINT, "max_screen_attempts": MAX_SCREEN_ATTEMPTS,
            "assignments": [assignment(i) for i in range(TARGET)], "hosted": PROTOCOL}


def screen_attempt(state):
    return len(state.get("screen_history", [])) + 1


def membership(case):
    top, mmr = set(case["sets"]["topk"]), set(case["sets"]["mmr"])
    return {str(s["number"]): "both" if s["number"] in top and s["number"] in mmr
            else ("topk_only" if s["number"] in top else "mmr_only") for s in case["sounds"]}


def create_app(bundle_path=DEFAULT_BUNDLE):
    bundle_path = Path(bundle_path).resolve()
    manifest = json.loads((bundle_path / "manifest.json").read_text(encoding="utf-8"))
    for name, checksum in manifest["files"].items():
        candidate = (bundle_path / name).resolve()
        if not candidate.is_relative_to(bundle_path) or digest(candidate) != checksum:
            raise ValueError("C3 study bundle changed: " + name)
    bundle = json.loads((bundle_path / "bundle.json").read_text(encoding="utf-8"))
    if bundle["version"] != VERSION or bundle["test_evaluated"] is not False:
        raise ValueError("Wrong C3 study bundle")
    cases = {case["case_id"]: case for case in bundle["cases"]}
    if set(cases) != {"practice", *[f"case_{i:02d}" for i in range(1, N_SCORED + 1)]}:
        raise ValueError("Need exactly eight scored C3 cases and a separate practice case")
    if bundle["assignments"] != [assignment(i) for i in range(TARGET)]:
        raise ValueError("C3 counterbalancing changed after bundle freeze")
    # Protocol identity, not file bytes: page/text fixes do not invalidate saved runs; changes to
    # stimuli, questions, counterbalancing or the operating point do.
    fingerprint = hashlib.sha256(json.dumps({"bundle": digest(bundle_path / "manifest.json"), "protocol": protocol()},
                                            sort_keys=True).encode()).hexdigest()
    store = Store(fingerprint)
    app = FastAPI(title="C3 study rehearsal", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.fingerprint = fingerprint

    @app.middleware("http")
    async def same_origin_guard(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            return JSONResponse({"detail": "Cross-origin requests are not allowed"}, status_code=403)
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > 16000 or (request.method == "POST" and "content-length" not in request.headers):
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        result = await call_next(request)
        result.headers["Cache-Control"] = "no-store"
        result.headers["X-Content-Type-Options"] = "nosniff"
        result.headers["Referrer-Policy"] = "no-referrer"
        result.headers["Content-Security-Policy"] = (
            "default-src 'self'; media-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        return result

    def researcher(request):
        return require_admin(authorization=request.headers.get("authorization", ""),
                             researcher_session=request.cookies.get(SESSION_COOKIE))

    def signed_in(request):
        try:
            return researcher(request)
        except HTTPException:
            return None

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
        if state["purpose"] == "researcher_self_review" and signed_in(request) != state["researcher"]:
            fail("This self-review belongs to another researcher", 403)
        return key, state

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
                      total_cases=N_SCORED, excluded_from_research=True, purpose=state["purpose"],
                      played=state["playback"], audio_ids=list(allowed_audio(state)),
                      parameter_labels=bundle["parameter_labels"],
                      demo=state["purpose"] == "researcher_self_review",
                      screen_attempt=screen_attempt(state),
                      screen_attempts_left=MAX_SCREEN_ATTEMPTS - screen_attempt(state))
        if state["phase"] == "headphones":
            result["screen_number"] = len(state["headphone_answers"]) + 1
        if state["phase"] in {"practice", "task"}:
            case_id, set_a = current(state)
            case = cases[case_id]
            set_b = "mmr" if set_a == "topk" else "topk"
            # Allowlist: never reveal methods, sample IDs, relevance, ranks or target settings.
            result["case"] = {
                "case_id": case_id, "target_audio_id": f"{case_id}_target",
                "sounds": [{"sound_id": s["sound_id"], "number": s["number"], "params": s["params"]} for s in case["sounds"]],
                "sets": {"A": case["sets"][set_a], "B": case["sets"][set_b]},
            }
        return result

    def listened(state):
        if any(state["playback"].get(a, {}).get("end", 0) < 1 for a in allowed_audio(state)):
            fail("Please listen to each sound all the way through once. Replays are welcome.")

    def rating_ok(value):
        return value == "cannot_judge" or (type(value) is int and value in CLOSENESS)

    def check_response(answers, case):
        if set(answers) != {"closeness", *SET_QUESTIONS, "confidence", "reason"}:
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

    # ------------------------------------------------------------------ pages
    @app.get("/")
    def index(request: Request, view: str = "participant"):
        if view == "researcher":
            researcher(request)
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        if view == "researcher":
            html = html.replace("PARTICIPANT PREVIEW · Research collection disabled",
                                "RESEARCHER SELF-REVIEW · Excluded from participant findings")
        return HTMLResponse(html)

    @app.get("/admin")
    def admin_page():
        return FileResponse(ASSETS / "admin.html")

    @app.get("/assets/{name}")
    def static(name: str):
        if name not in {"app.js", "style.css", "admin.js"}:
            fail("Not found", 404)
        return FileResponse(ASSETS / name)

    # ------------------------------------------------------------------ participant API
    @app.get("/api/info")
    def info():
        return {"mode": "rehearsal", "version": VERSION, "protocol": PROTOCOL, "target": TARGET, "cap": CAP,
                "research_collection_enabled": False, "operating_point": OPERATING_POINT["status"]}

    @app.post("/api/start")
    def start(body: Start, request: Request, authorization: str | None = Header(default=None)):
        if body.purpose not in {"participant_preview", "researcher_self_review"}:
            fail("Unknown C3 view")
        actor = researcher(request) if body.purpose == "researcher_self_review" else None
        if set(body.consent) != set(CONSENT) or not all(body.consent.values()):
            fail("All eligibility and consent statements must be confirmed; otherwise please stop.")
        if body.experience not in EXPERIENCE:
            fail("Choose an experience range")
        key = token_hash(authorization)
        with store.connect() as db:
            if db.execute("SELECT state FROM sessions WHERE token_hash=?", (key,)).fetchone():
                _, state = get_session(db, authorization, request)
                return public(state)
            sessions = [json.loads(r[0]) for r in db.execute("SELECT state FROM sessions").fetchall()]
            if actor is None:
                checksum = hashlib.sha256(body.invitation.strip().encode()).hexdigest()
                invite = db.execute("SELECT slot FROM c3_v2_invites WHERE invite_hash=? AND token_hash IS NULL",
                                    (checksum,)).fetchone()
                if not invite:
                    fail("This C3 invitation is invalid or already used. Resume on the original browser.", 403)
                slot = invite[0]
                claimed = db.execute("UPDATE c3_v2_invites SET token_hash=? WHERE invite_hash=? AND token_hash IS NULL",
                                     (key, checksum))
                if claimed.rowcount != 1:
                    fail("Invitation already used", 409)
            else:
                own = [s for s in sessions if s.get("researcher") == actor]
                if len(own) >= SELF_REVIEW_LIMIT:
                    fail("Self-review rehearsal limit reached", 409)
                slot = len(own) % TARGET
            state = {"code": "C3-R-" + secrets.token_hex(5).upper(), "created": now(), "updated": now(),
                     "consent_version": VERSION, "consent": body.consent, "experience": body.experience,
                     "mode": "rehearsal", "fingerprint": fingerprint, "slot": slot, "assignment": assignment(slot),
                     "phase": "volume", "revision": 0, "responses": [], "headphone_answers": [], "playback": {},
                     "excluded_from_research": True, "stage_started": now(), "purpose": body.purpose, "researcher": actor}
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
                fail("Audio is not part of the current step", 403)
            return FileResponse(bundle_path / "audio" / permitted[audio_id], media_type="audio/wav")

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
                state.setdefault("screen_history", []).append(
                    {"attempt": screen_attempt(state), "answers": state["headphone_answers"], "ended": now()})
                state.update(phase="volume", headphone_answers=[], playback={})
            elif body.op == "skip_screen" and not answers:
                # Researcher self-review only (presentations); never for participant previews.
                if state["purpose"] != "researcher_self_review":
                    fail("Skipping the setup check is only available in researcher self-review", 403)
                if phase not in {"volume", "headphones", "screen_failed"}:
                    fail("This action is not available at this stage", 409)
                state.update(phase="practice", screen_skipped=True, playback={})
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

    # ------------------------------------------------------------------ researcher API
    def summary_payload(actor):
        with store.connect() as db:
            states = [json.loads(r[0]) for r in db.execute("SELECT state FROM sessions").fetchall()]
            invites = db.execute(
                "SELECT i.slot,i.invite_hash,i.token_hash,v.encrypted_code FROM c3_v2_invites i "
                "LEFT JOIN invitation_code_vault v ON v.component='c3' AND v.invite_hash=i.invite_hash ORDER BY i.slot").fetchall()
        return {**info(), "researcher": actor, "independent_participants": 0,
                "sessions": [{"code": s["code"], "purpose": s["purpose"], "phase": s["phase"], "created": s["created"],
                              "saved_cases": len(s["responses"]), "screen_skipped": bool(s.get("screen_skipped"))}
                             for s in states],
                "invitations": [{"assignment_id": f"C3-{r[0] + 1:02d}",
                                 "invitation": recover_code("c3", r[1], r[3])[0], "used": r[2] is not None}
                                for r in invites]}

    @app.get("/api/admin/summary")
    def summary(request: Request):
        return summary_payload(researcher(request))

    @app.post("/api/admin/invitations")
    def invitations(request: Request):
        actor = researcher(request)
        with store.connect() as db:
            occupied = {r[0] for r in db.execute("SELECT slot FROM c3_v2_invites").fetchall()}
            for slot in range(TARGET):
                if slot in occupied:
                    continue
                code = "C3-PREVIEW-" + secrets.token_urlsafe(24)
                db.execute("INSERT INTO c3_v2_invites VALUES (?,?,NULL,?,?)",
                           (hashlib.sha256(code.encode()).hexdigest(), slot, actor, now()))
                remember_code(db, "c3", code)
        return summary_payload(actor)

    @app.get("/api/admin/export")
    def export(request: Request):
        researcher(request)
        with store.connect() as db:
            states = [json.loads(r[0]) for r in db.execute("SELECT state FROM sessions").fetchall()]
        fields = ("code", "purpose", "slot", "assignment", "created", "completed", "responses", "feedback")
        # No session tokens, invitation codes, researcher names, sample IDs or answer keys.
        records = [{k: s[k] for k in fields} | {"screen_skipped": bool(s.get("screen_skipped")),
                                                "screen_attempts": screen_attempt(s), "mode": "rehearsal",
                                                "excluded_from_research": True, "analysis_include": False}
                   for s in states if s["phase"] == "complete"]
        return JSONResponse({"protocol": PROTOCOL, "version": VERSION, "independent_participants": 0,
                             "completed_rehearsal_runs": len(records), "records": records},
                            headers={"Content-Disposition": 'attachment; filename="c3-rehearsal-only.json"',
                                     "Cache-Control": "private, no-store"})

    return app


class Flow:
    """ASGI wrapper so main.py can mount C3 before its tables exist (created at start-up)."""
    app = None

    async def __call__(self, scope, receive, send):
        if self.app is None:
            return await JSONResponse({"detail": "C3 is not ready"}, status_code=503)(scope, receive, send)
        return await self.app(scope, receive, send)


flow = Flow()


def initialize_c3_database():
    flow.app = create_app()
