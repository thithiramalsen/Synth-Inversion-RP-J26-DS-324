"""C2 entry points on the existing participant/researcher study deployments."""
import hashlib
import json
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from c2_flow import create_app, now
from c2_flow_v2 import create_app as create_v2_app
from c2_analysis_v2 import summarize as summarize_v2
from c2_design_v2 import PROTOCOL as V2_PROTOCOL
from database import get_connection
from invitation_codes import remember_code, recover_code
from security import require_admin

router = APIRouter(prefix="/api/c2-pilot")


class Flow:
    app = None

    async def __call__(self, scope, receive, send):
        if self.app is None:
            return await JSONResponse({"detail": "C2 is not ready"}, status_code=503)(scope, receive, send)
        return await self.app(scope, receive, send)


flow = Flow()
flow_v2 = Flow()


def researcher_only():
    return os.environ.get("SURVEY_C2_RESEARCHER_ONLY") == "1"


def initialize_c2_database():
    flow.app = create_app()
    flow_v2.app = create_v2_app()


@router.get("/status")
def status():
    return dict(ready=flow.app is not None, rehearsal=True,
                researcher_only=researcher_only(), research_collection_enabled=False,
                protocol="c2-hosted-rehearsal-v1", independent_participants=0,
                scored_cases=8, practice_cases=1)


@router.get("/admin/summary")
def summary(actor=Depends(require_admin)):
    with get_connection() as db:
        states = [json.loads(row[0]) for row in db.execute("SELECT state FROM c2_v1_sessions").fetchall()]
        invites = db.execute("SELECT i.slot,i.invite_hash,i.token_hash,v.encrypted_code FROM c2_v1_invites i LEFT JOIN invitation_code_vault v ON v.component='c2' AND v.invite_hash=i.invite_hash ORDER BY i.slot").fetchall()
    return {**status(), "researcher": actor,
            "sessions": [{k: s[k] for k in ("code", "purpose", "phase", "created", "excluded_from_research")} | {"saved_cases": len(s["responses"])} for s in states],
            "invitations": [{"assignment_id": f"C2-{r['slot']+1:02d}",
                             "invitation": recover_code("c2", r["invite_hash"], r["encrypted_code"])[0],
                             "used": r["token_hash"] is not None} for r in invites]}


@router.post("/admin/invitations")
def invitations(actor=Depends(require_admin)):
    if researcher_only():
        raise HTTPException(409, "Use Start self-review on the researcher service; no participant invitations are issued here")
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        occupied = {r[0] for r in db.execute("SELECT slot FROM c2_v1_invites").fetchall()}
        for slot in range(12):
            if slot in occupied:
                continue
            code = "C2-PREVIEW-" + secrets.token_urlsafe(24)
            checksum = hashlib.sha256(code.encode()).hexdigest()
            db.execute("INSERT INTO c2_v1_invites VALUES (?,?,NULL,?,?)", (checksum, slot, actor, now()))
            remember_code(db, "c2", code)
    return summary(actor)


@router.get("/admin/export")
def export(actor=Depends(require_admin)):
    with get_connection() as db:
        states = [json.loads(r[0]) for r in db.execute("SELECT state FROM c2_v1_sessions").fetchall()]
    # No invitation/session credentials, names, screening keys or private bundle.
    records = [{k: s[k] for k in ("code", "purpose", "created", "completed", "responses", "feedback")} |
               dict(mode="rehearsal", excluded_from_research=True, analysis_include=False)
               for s in states if s["phase"] == "complete"]
    return JSONResponse(dict(protocol="c2-hosted-rehearsal-v1", independent_participants=0,
                             completed_rehearsal_runs=len(records), records=records),
                        headers={"Content-Disposition": 'attachment; filename="c2-rehearsal-only.json"',
                                 "Cache-Control": "private, no-store"})


@router.get("/v2/status")
def status_v2():
    return dict(ready=flow_v2.app is not None, rehearsal=True,
                researcher_only=researcher_only(), research_collection_enabled=False,
                protocol=V2_PROTOCOL, independent_participants=0,
                listening_cases=8, display_cases=8, practice_cases=1)


@router.get("/v2/admin/summary")
def summary_v2(actor=Depends(require_admin)):
    with get_connection() as db:
        states = [json.loads(r[0]) for r in db.execute("SELECT state FROM c2_v2_sessions")]
        invites = db.execute("SELECT i.slot,i.invite_hash,i.token_hash,v.encrypted_code FROM c2_v2_invites i LEFT JOIN invitation_code_vault v ON v.component='c2_v2' AND v.invite_hash=i.invite_hash ORDER BY i.slot").fetchall()
    return {**status_v2(), "researcher": actor,
            "sessions": [{k: s[k] for k in ("code", "purpose", "phase", "created", "excluded_from_research")} |
                         dict(saved_listening=len(s["listening_responses"]), saved_display=len(s["display_responses"])) for s in states],
            "invitations": [dict(assignment_id=f"C2V2-{r['slot']+1:02d}",
                                 invitation=recover_code("c2_v2", r["invite_hash"], r["encrypted_code"])[0],
                                 used=r["token_hash"] is not None) for r in invites]}


@router.post("/v2/admin/invitations")
def invitations_v2(actor=Depends(require_admin)):
    if researcher_only():
        raise HTTPException(409, "Start self-review on the researcher service; no participant invitations are issued here")
    with get_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        occupied = {r[0] for r in db.execute("SELECT slot FROM c2_v2_invites")}
        for slot in range(12):
            if slot in occupied:
                continue
            code = "C2V2-PREVIEW-" + secrets.token_urlsafe(24)
            checksum = hashlib.sha256(code.encode()).hexdigest()
            db.execute("INSERT INTO c2_v2_invites VALUES (?,?,NULL,?,?)", (checksum, slot, actor, now()))
            remember_code(db, "c2_v2", code)
    return summary_v2(actor)


@router.get("/v2/admin/export")
def export_v2(actor=Depends(require_admin)):
    with get_connection() as db:
        states = [json.loads(r[0]) for r in db.execute("SELECT state FROM c2_v2_sessions")]
    records = [{k: s[k] for k in ("code", "purpose", "created", "completed", "slot", "assignment",
                                  "listening_responses", "display_responses", "feedback", "fingerprint", "consent_version")} |
               dict(mode="rehearsal", protocol=V2_PROTOCOL, excluded_from_research=True, analysis_include=False)
               for s in states if s["phase"] == "complete"]
    return JSONResponse(dict(protocol=V2_PROTOCOL, independent_participants=0,
                             completed_rehearsal_runs=len(records), records=records, summary=summarize_v2(states),
                             meaning_coding=[dict(code=s["code"], response=s["feedback"]["meaning"],
                                 coder_1=None, coder_2=None, agreed_score=None, rationale="") for s in states if s["phase"] == "complete"]),
                        headers={"Content-Disposition": 'attachment; filename="c2-v2-rehearsal-only.json"',
                                 "Cache-Control": "private, no-store"})
