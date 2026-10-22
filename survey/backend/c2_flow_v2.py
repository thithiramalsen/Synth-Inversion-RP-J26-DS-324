"""Versioned C2 rehearsal. Never reads/writes v1, C1 or C4 response tables."""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets

from fastapi import FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from c2_design import VERSION as BUNDLE_VERSION, assignment as frozen_assignment
from c2_design_v2 import CONSENT, CONTRACT, NAMES, PROTOCOL, TARGET, VERSION, assignment, rating
from c2_flow import Action, DEFAULT_BUNDLE, Play, Start, digest, fail, now
from database import get_connection
from security import SESSION_COOKIE, require_admin


class Store:
    def __init__(self, fingerprint):
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS c2_v2_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS c2_v2_sessions (token_hash TEXT PRIMARY KEY, code TEXT UNIQUE NOT NULL, state TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS c2_v2_invites (invite_hash TEXT PRIMARY KEY, slot INTEGER UNIQUE NOT NULL, token_hash TEXT UNIQUE, created_by TEXT NOT NULL, created_at TEXT NOT NULL)")
            row = db.execute("SELECT value FROM c2_v2_metadata WHERE key='fingerprint'").fetchone()
            if row and row[0] != fingerprint:
                raise ValueError("C2 v2 protocol/bundle changed. Preserve these records and use a new protocol version.")
            db.execute("INSERT INTO c2_v2_metadata VALUES ('fingerprint', ?) ON CONFLICT(key) DO NOTHING", (fingerprint,))
            db.execute("INSERT INTO c2_v2_metadata VALUES ('mode', 'rehearsal') ON CONFLICT(key) DO NOTHING")

    @contextmanager
    def connect(self):
        with get_connection() as db:
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
    if bundle["version"] != BUNDLE_VERSION or bundle["test_evaluated"] is not False:
        raise ValueError("Only the frozen development bundle is eligible")
    if bundle["assignments"] != [frozen_assignment(i) for i in range(TARGET)]:
        raise ValueError("Frozen bundle allocation changed")
    cases = {case["case_id"]: case for case in bundle["cases"]}
    if set(cases) != {"practice", *[f"case_{i:02d}" for i in range(1, 9)]}:
        raise ValueError("Need the original eight cases and separate practice")
    for case in cases.values():
        if [p["name"] for p in case["parameters"]] != list(NAMES):
            raise ValueError("The frozen 13-control order changed")
        for p in case["parameters"]:
            if any(type(p[k]) not in (int, float) or not math.isfinite(p[k]) or not 0 <= p[k] <= 1
                   for k in ("predicted_z", "q")):
                raise ValueError("Invalid frozen display value")
    fingerprint = hashlib.sha256(json.dumps({"bundle": digest(bundle_path / "manifest.json"),
        "contract": CONTRACT}, sort_keys=True).encode()).hexdigest()
    store = Store(fingerprint)
    app = FastAPI(title="C2 listening and reliability rehearsal v2", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    app.state.fingerprint = fingerprint

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            return JSONResponse({"detail": "Cross-origin requests are not allowed"}, status_code=403)
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > 16000 or (request.method == "POST" and "content-length" not in request.headers):
            return JSONResponse({"detail": "Request too large"}, status_code=413)
        result = await call_next(request)
        result.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                               "Referrer-Policy": "no-referrer"})
        return result

    def researcher(request):
        return require_admin(authorization=request.headers.get("authorization", ""),
                             researcher_session=request.cookies.get(SESSION_COOKIE))

    def token_hash(authorization):
        if not authorization or not re.fullmatch(r"Bearer [a-f0-9]{64}", authorization):
            fail("Use the same browser to resume this C2 v2 rehearsal.", 401)
        return hashlib.sha256(authorization[7:].encode()).hexdigest()

    def get_session(db, authorization, request):
        key = token_hash(authorization)
        row = db.execute("SELECT state FROM c2_v2_sessions WHERE token_hash=?", (key,)).fetchone()
        if not row:
            fail("No C2 v2 session saved in this browser", 401)
        state = json.loads(row[0])
        if state["purpose"] == "researcher_self_review" and researcher(request) != state["researcher"]:
            fail("This self-review belongs to another researcher", 403)
        return key, state

    def current(state):
        if state["phase"] == "practice":
            return "practice", None
        if state["phase"] == "listening":
            return state["assignment"]["listening"][len(state["listening_responses"])], None
        if state["phase"] == "display":
            task = state["assignment"]["display"][len(state["display_responses"])]
            return task["case_id"], task["condition"]
        return None, None

    def allowed_audio(state):
        if state["phase"] == "volume":
            return {"volume_reference": bundle["volume"]["path"]}
        if state["phase"] == "headphones":
            item = bundle["headphones"][len(state["headphone_answers"])]
            return {item["screen_id"]: item["path"]}
        case_id, _ = current(state)
        if case_id:
            return {f"{case_id}_{label}": info["file"] for label, info in cases[case_id]["audio"].items()}
        return {}

    def public(state):
        result = {k: state[k] for k in ("code", "phase", "revision", "created", "purpose")}
        result.update(mode="rehearsal", version=VERSION, protocol=PROTOCOL,
                      excluded_from_research=True, independent_participants=0,
                      listening_completed=len(state["listening_responses"]),
                      display_completed=len(state["display_responses"]),
                      played=state["playback"], audio_ids=list(allowed_audio(state)))
        if state["phase"] == "headphones":
            result["screen_number"] = len(state["headphone_answers"]) + 1
        case_id, condition = current(state)
        if case_id:
            result["case"] = {"case_id": case_id}
            # No parameters, q, errors, truth or display allocation before ALL listening ratings are saved.
            if state["phase"] == "display":
                fields = ("name", "label", "predicted_z", "q") if condition == "with" else ("name", "label", "predicted_z")
                result["case"].update(condition=condition,
                    parameters=[{k: p[k] for k in fields} for p in cases[case_id]["parameters"]])
        return result

    def save(db, key, state):
        state["updated"] = now()
        db.execute("UPDATE c2_v2_sessions SET state=? WHERE token_hash=?", (json.dumps(state), key))

    def listened(state):
        if any(state["playback"].get(a, {}).get("end", 0) < 1 for a in allowed_audio(state)):
            fail("Listen to both clips all the way through before saving. Replays are welcome.")

    def comment(value):
        if not isinstance(value, str) or len(value) > 1000:
            fail("Use up to 1,000 characters and leave out personal details")

    @app.get("/")
    def index():
        return RedirectResponse("/c2/rehearsal-v2")

    @app.get("/api/info")
    def info():
        return dict(mode="rehearsal", version=VERSION, protocol=PROTOCOL, target=TARGET,
                    research_collection_enabled=False, independent_participants=0,
                    listening_cases=8, display_cases=8, practice_cases=1, fingerprint=fingerprint)

    @app.post("/api/start")
    def start(body: Start, request: Request, authorization: str | None = Header(default=None)):
        if body.purpose not in {"participant_preview", "researcher_self_review"}:
            fail("Unknown C2 view")
        actor = researcher(request) if body.purpose == "researcher_self_review" else None
        if (os.environ.get("SURVEY_C2_RESEARCHER_ONLY") == "1") != (actor is not None):
            fail("Use the matching C2 view on this deployment", 403)
        if set(body.consent) != set(CONSENT) or not all(body.consent.values()):
            fail("Please read and confirm all eligibility and consent statements, or stop here.")
        if body.experience not in {"under_1", "1_to_3", "over_3"}:
            fail("Choose an experience range")
        key = token_hash(authorization)
        with store.connect() as db:
            if db.execute("SELECT state FROM c2_v2_sessions WHERE token_hash=?", (key,)).fetchone():
                return public(get_session(db, authorization, request)[1])
            if actor is None:
                checksum = hashlib.sha256(body.invitation.strip().encode()).hexdigest()
                invite = db.execute("SELECT slot FROM c2_v2_invites WHERE invite_hash=? AND token_hash IS NULL", (checksum,)).fetchone()
                if not invite:
                    fail("Use a new C2 v2 preview code, or resume on the original browser. V1/C1/C4 codes do not work here.", 403)
                slot = invite[0]
                claimed = db.execute("UPDATE c2_v2_invites SET token_hash=? WHERE invite_hash=? AND token_hash IS NULL", (key, checksum))
                if claimed.rowcount != 1:
                    fail("Invitation already used", 409)
            else:
                own = [json.loads(r[0]) for r in db.execute("SELECT state FROM c2_v2_sessions")]
                own = [s for s in own if s.get("researcher") == actor]
                if len(own) >= 48:
                    fail("Self-review rehearsal limit reached", 409)
                slot = len(own) % TARGET
            state = dict(code="C2V2-R-" + secrets.token_hex(5).upper(), created=now(), updated=now(),
                         consent_version=VERSION, consent=body.consent, experience=body.experience,
                         mode="rehearsal", protocol=PROTOCOL, fingerprint=fingerprint,
                         slot=slot, assignment=assignment(slot), purpose=body.purpose, researcher=actor,
                         phase="volume", revision=0, listening_responses=[], display_responses=[],
                         headphone_answers=[], playback={}, excluded_from_research=True, stage_started=now())
            db.execute("INSERT INTO c2_v2_sessions VALUES (?, ?, ?)", (key, state["code"], json.dumps(state)))
            return public(state)

    @app.get("/api/session")
    def session(request: Request, authorization: str | None = Header(default=None)):
        with store.connect() as db:
            return public(get_session(db, authorization, request)[1])

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
                for field in ("experience", "practice_response", "feedback"):
                    state.pop(field, None)
                state.update(phase="withdrawn", withdrawn=now(), listening_responses=[], display_responses=[],
                             headphone_answers=[], playback={})
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
            elif body.op == "listening" and phase in {"practice", "listening"}:
                if set(answers) != {"similarity", "comment"} or not rating(answers["similarity"]):
                    fail("Rate overall sound similarity from 1 to 5, or choose Cannot judge")
                comment(answers["comment"])
                listened(state)
                case_id, _ = current(state)
                record = dict(case_id=case_id, answers=answers, started=state["stage_started"], submitted=now())
                if phase == "practice":
                    state["practice_response"] = record
                    state["phase"] = "listening_intro"
                else:
                    record["position"] = len(state["listening_responses"]) + 1
                    state["listening_responses"].append(record)
                    count = len(state["listening_responses"])
                    state["phase"] = "display_intro" if count == 8 else ("listening_break" if count == 4 else "listening")
            elif body.op == "display" and phase == "display":
                if set(answers) != {"clarity", "usefulness"} or not all(rating(answers[f]) for f in answers):
                    fail("Rate clarity and usefulness from 1 to 5, or choose Cannot judge")
                case_id, condition = current(state)
                state["display_responses"].append(dict(case_id=case_id, condition=condition, answers=answers,
                    position=len(state["display_responses"]) + 1, started=state["stage_started"], submitted=now()))
                count = len(state["display_responses"])
                state["phase"] = "feedback" if count == 8 else ("display_break" if count == 4 else "display")
            elif body.op == "continue" and not answers and phase in {"listening_intro", "listening_break", "display_intro", "display_break"}:
                state["phase"] = "listening" if phase.startswith("listening") else "display"
            elif body.op == "finish" and phase == "feedback":
                if set(answers) != {"meaning", "guarantee", "impossible", "preference", "length", "comment"}:
                    fail("Please complete the final questions")
                for field in ("meaning", "comment"):
                    comment(answers[field])
                if not answers["meaning"].strip():
                    fail("Explain what the estimate means, or write I do not know")
                if any(answers[f] not in ("yes", "no", "unsure") for f in ("guarantee", "impossible")):
                    fail("Answer both understanding questions")
                if answers["preference"] not in ("with", "without", "none", "cannot_judge") or answers["length"] not in ("about_right", "too_long", "could_be_longer"):
                    fail("Choose a display preference and session length")
                state.update(phase="complete", feedback=answers, completed=now())
            else:
                fail("This action is not available at this stage", 409)
            state["revision"] += 1
            state["stage_started"] = now()
            save(db, key, state)
            return public(state)

    return app
