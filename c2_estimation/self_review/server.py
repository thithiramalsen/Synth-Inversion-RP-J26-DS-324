"""Reuse the C2 study flow with a separate researcher rehearsal identity and database."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from fastapi import HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from c2_estimation.human_study.server import ASSETS, DEFAULT_BUNDLE, ROOT, create_app as study_app, digest

DEFAULT_DB = ROOT / "data/processed/c2_v4/researcher_self_review_v1/responses.sqlite3"
DEFAULT_PREVIEW_DB = ROOT / "data/processed/c2_v4/participant_preview_v1/responses.sqlite3"
VERSION = "c2-researcher-self-review-v1"
PREVIEW_ASSETS = Path(__file__).with_name("web")


def self_review_html(purpose="researcher_self_review"):
    html = (ASSETS / "index.html").read_text(encoding="utf-8")
    navigation = ('<nav class="review-links" aria-label="C2 study views">'
                  '<a href="http://127.0.0.1:8768/">Participant study preview</a>'
                  '<a href="http://127.0.0.1:8767/">Researcher self-review</a></nav>')
    html = html.replace("</header>", "</header>" + navigation)
    if purpose == "participant_preview":
        html = html.replace('</nav>', '<a href="/walkthrough">Preview an example (no answers saved)</a></nav>')
        html = html.replace("C2 · Listening study rehearsal", "C2 · Participant study preview")
        html = html.replace("LOCAL REHEARSAL · Not collecting research responses",
                            "PARTICIPANT STUDY PREVIEW · Research collection disabled")
        return html.replace("/ Listening study", "/ Participant preview")
    html = html.replace("C2 · Listening study rehearsal", "C2 · Researcher self-review")
    html = html.replace("LOCAL REHEARSAL · Not collecting research responses",
                        "RESEARCHER SELF-REVIEW · Excluded from participant findings")
    html = html.replace("/ Listening study", "/ Researcher self-review")
    html = html.replace("C2 · Frozen model outputs · Rehearsal version 1",
                        "C2 · Researcher rehearsal · Repeated runs are not independent participants")
    return html


def self_review_js(purpose="researcher_self_review"):
    javascript = (ASSETS / "app.js").read_text(encoding="utf-8")
    token_name = VERSION if purpose == "researcher_self_review" else "c2-participant-preview-v1"
    javascript = javascript.replace("c2-human-v1-rehearsal-token", token_name + "-token")
    javascript = javascript.replace("c2-rehearsal-draft-", token_name + "-draft-")
    if purpose == "participant_preview":
        return javascript.replace("Rehearsal / Not a participant invitation", "Participant interface preview / Rehearsal only")
    javascript = javascript.replace("Rehearsal / Not a participant invitation", "Researcher self-review / Developer rehearsal")
    javascript = javascript.replace("How helpful are these controls?", "Rehearse the C2 study")
    javascript = javascript.replace(
        "This is a local test of the study. Research collection is disabled. Don’t recruit participants with this version. Every saved response is marked as rehearsal data.",
        "Use this version yourself to check the instructions, playback, questions and session length. You already know the system, so your judgments are developer observations. Every run is excluded from participant findings. Do not recruit other people with this version.")
    return javascript


def create_app(database=DEFAULT_DB, bundle=DEFAULT_BUNDLE, *, purpose="researcher_self_review"):
    if purpose not in ("researcher_self_review", "participant_preview"):
        raise ValueError("Unknown preview purpose")
    database = Path(database).resolve()
    # This launcher cannot be pointed at the original study or live app database.
    expected_parent = (ROOT / "data/processed/c2_v4").resolve()
    if (not database.is_relative_to(expected_parent)
            or not database.parent.name.startswith(purpose + "_")
            or database.name != "responses.sqlite3"):
        raise ValueError(f"Use data/processed/c2_v4/{purpose}_<version>/responses.sqlite3")
    marker = "self_review_version" if purpose == "researcher_self_review" else "participant_preview_version"
    if database.exists():
        with closing(sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)) as db:
            row = db.execute("SELECT value FROM metadata WHERE key=?", (marker,)).fetchone()
            if row is None or row[0] != VERSION:
                raise ValueError("Preserving an existing non-self-review database. Choose a new self-review folder.")
    app = study_app(bundle, database)
    sources = {p.name: digest(p) for p in Path(__file__).parent.glob("*.py")}
    sources.update({"web/" + p.name: digest(p) for p in PREVIEW_ASSETS.glob("*") if p.is_file()})
    fingerprint = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
    with app.state.store.connect() as db:
        saved = db.execute("SELECT value FROM metadata WHERE key='self_review_sources'").fetchone()
        if saved and saved[0] != fingerprint:
            raise ValueError("Self-review source changed; use a new versioned self-review database.")
        db.execute("INSERT OR IGNORE INTO metadata VALUES (?, ?)", (marker, VERSION))
        db.execute("INSERT OR IGNORE INTO metadata VALUES ('self_review_sources', ?)", (fingerprint,))
    info_route = next(route for route in app.routes if getattr(route, "path", None) == "/api/info")
    base_info = info_route.endpoint

    @app.middleware("http")
    async def researcher_view(request, call_next):
        response = await call_next(request)
        if request.method != "GET" or response.status_code != 200:
            return response
        headers = {key: value for key, value in response.headers.items()
                   if key.lower() not in ("content-length", "content-type", "etag", "last-modified")}
        if request.url.path == "/":
            return HTMLResponse(self_review_html(purpose), headers=headers)
        if request.url.path == "/assets/app.js":
            return Response(self_review_js(purpose), media_type="text/javascript", headers=headers)
        if request.url.path == "/assets/style.css":
            css = (ASSETS / "style.css").read_text(encoding="utf-8")
            css += "\n.review-links{display:flex;flex-wrap:wrap;gap:20px;max-width:1100px;margin:0 auto;padding:10px 24px;font-size:14px}.review-links a{color:#12624e;text-underline-offset:4px}\n"
            css += ".table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:12px 10px;border-bottom:1px solid var(--line)}th{font-size:12px}td select{min-width:150px}#ratings label{display:block;margin:12px 0}#ratings select{display:block;margin-top:6px}\n"
            return Response(css, media_type="text/css", headers=headers)
        if request.url.path == "/api/info":
            return JSONResponse({**base_info(), "purpose": purpose,
                                 "self_review_version": VERSION, "independent_participant_findings": False},
                                headers=headers)
        return response

    app.title = "C2 " + purpose.replace("_", " ")
    if purpose == "participant_preview":
        frozen = json.loads((Path(bundle) / "bundle.json").read_text(encoding="utf-8"))
        practice = next(case for case in frozen["cases"] if case["case_id"] == "practice")

        @app.get("/walkthrough")
        def walkthrough():
            return FileResponse(PREVIEW_ASSETS / "index.html")

        @app.get("/preview.js")
        def preview_script():
            return FileResponse(PREVIEW_ASSETS / "app.js", media_type="text/javascript")

        @app.get("/api/walkthrough")
        def walkthrough_case():
            # Public practice display only: no truth, error labels, answer keys or scored cases.
            return {"case_id": "practice", "responses_saved": False,
                    "parameters": [{k: p[k] for k in ("name", "label", "predicted_z", "q")}
                                   for p in practice["parameters"]]}

        @app.get("/api/walkthrough/audio/{kind}")
        def walkthrough_audio(kind: str):
            if kind not in ("target", "predicted"):
                raise HTTPException(404)
            audio_root = (Path(bundle) / "audio").resolve()
            path = (audio_root / practice["audio"][kind]["file"]).resolve()
            if not path.is_relative_to(audio_root):
                raise HTTPException(404)
            return FileResponse(path, media_type="audio/wav")
    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", choices=("researcher", "participant"), default="researcher")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    purpose = "researcher_self_review" if args.view == "researcher" else "participant_preview"
    args.port = args.port or (8767 if args.view == "researcher" else 8768)
    args.database = args.database or (DEFAULT_DB if args.view == "researcher" else DEFAULT_PREVIEW_DB)
    if not 1024 <= args.port <= 65535 or args.port in (8765, 8766, 8770):
        parser.error("Choose an unused port; 8765, 8766 and 8770 belong to existing C2 apps.")
    print(f"C2 {purpose.upper()}: http://127.0.0.1:{args.port}/", flush=True)
    print(f"Rehearsal database: {args.database.resolve()}", flush=True)
    uvicorn.run(create_app(args.database, purpose=purpose), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
