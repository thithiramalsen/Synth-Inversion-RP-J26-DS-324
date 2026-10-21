"""Loopback C2 app: one inference worker, bounded WAV upload, isolated result folders."""
from __future__ import annotations

import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import json
from pathlib import Path
import re
import threading
import traceback
from urllib.parse import unquote
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict

from .engine import (
    Cancelled, DEFAULT_OUTPUT, Engine, InputError, MAX_UPLOAD_BYTES,
    VERSION, decode_wav, read_json, sha, write_json,
)

ASSETS = Path(__file__).with_name("web")
JOB_ID = re.compile(r"^[0-9a-f]{32}$")
ASSET_TYPES = {"index.html": "text/html", "app.js": "text/javascript", "style.css": "text/css"}


class ExampleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    example_id: str


class Jobs:
    def __init__(self, output, engine, executor):
        self.output, self.engine, self.executor = Path(output), engine, executor
        (self.output / "jobs").mkdir(parents=True, exist_ok=True)
        (self.output / "status").mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.current = {}
        self.active = None
        self.cancel_events = {}

    def status_path(self, job):
        if not JOB_ID.fullmatch(job):
            raise HTTPException(404, "Result not found.")
        return self.output / "status" / (job + ".json")

    def update(self, job, **fields):
        with self.lock:
            self.current[job].update(fields)
            write_json(self.status_path(job), self.current[job])

    def get(self, job):
        path = self.status_path(job)
        with self.lock:
            value = self.current.get(job)
            if value is None:
                if not path.is_file():
                    raise HTTPException(404, "Result not found.")
                value = read_json(path)
                if value["state"] in ("queued", "running", "cancelling"):
                    value = {**value, "state": "interrupted",
                             "detail": "The server stopped before this run finished. Start a new run."}
            return dict(value)

    def submit(self, payload, filename, example_id=None):
        with self.lock:
            if self.active is not None:
                raise HTTPException(409, "Another clip is being processed. Wait for it to finish or cancel it.")
            job = uuid.uuid4().hex
            self.active = job
            event = self.cancel_events[job] = threading.Event()
            self.current[job] = {"id": job, "state": "queued", "stage": "queued",
                                 "detail": "Waiting for the worker", "completed": 0, "total": 20,
                                 "filename": filename}
            self.update(job)
            self.executor.submit(self.work, job, payload, filename, example_id, event)
            return self.get(job)

    def work(self, job, payload, filename, example_id, event):
        try:
            def progress(stage, detail, completed):
                self.update(job, state="running", stage=stage, detail=detail, completed=completed)
            self.engine.run(payload, filename, self.output / "jobs" / job,
                            progress=progress, cancelled=event.is_set, example_id=example_id)
            self.update(job, state="complete", stage="complete", completed=20, detail="Your patch is ready.")
        except Cancelled:
            self.update(job, state="cancelled", detail="Cancelled. Partial files stay local and are not served.")
        except Exception as exc:
            (self.output / "status" / (job + ".log")).write_text(traceback.format_exc(), encoding="utf-8")
            self.update(job, state="failed", detail=str(exc)[:800])
        finally:
            with self.lock:
                self.active = None
                self.cancel_events.pop(job, None)

    def cancel(self, job):
        with self.lock:
            value = self.get(job)
            if job in self.cancel_events:
                self.cancel_events[job].set()
                self.update(job, state="cancelling", detail="Stopping after the current operation.")
                value = self.get(job)
            return value

    def file(self, job, name):
        if self.get(job)["state"] != "complete":
            raise HTTPException(409, "This result is not complete.")
        folder = self.output / "jobs" / job
        manifest = read_json(folder / "manifest.json")
        if name not in manifest["files"] or Path(name).name != name:
            raise HTTPException(404, "File not found.")
        path = folder / name
        if not path.is_file() or sha(path) != manifest["files"][name]:
            raise HTTPException(409, "The saved file has changed. Start a new run.")
        return path


def create_app(output=DEFAULT_OUTPUT, device="auto", engine_factory=None):
    @asynccontextmanager
    async def lifespan(app):
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="c2-inference")
        try:
            factory = engine_factory or (lambda: Engine(device=device))
            engine = await asyncio.get_running_loop().run_in_executor(executor, factory)
            app.state.jobs = Jobs(output, engine, executor)
            app.state.engine = engine
            yield
        finally:
            if hasattr(app.state, "jobs"):
                for event in list(app.state.jobs.cancel_events.values()):
                    event.set()
            executor.shutdown(wait=True, cancel_futures=True)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def local_only(request, call_next):
        host = request.headers.get("host", "")
        if not re.fullmatch(r"(127\.0\.0\.1|localhost)(:\d+)?", host):
            return JSONResponse({"detail": "Use the local address printed by the server."}, status_code=403)
        if request.method not in ("GET", "HEAD"):
            origin = request.headers.get("origin")
            if ((origin and origin != "http://" + host)
                    or request.headers.get("sec-fetch-site") == "cross-site"
                    or request.headers.get("x-c2-request") != "1"):
                return JSONResponse({"detail": "Open this request from the C2 page."}, status_code=403)
        response = await call_next(request)
        response.headers.update({
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
                "media-src 'self' blob:; connect-src 'self'; object-src 'none'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            ),
        })
        return response

    @app.get("/")
    def index():
        return FileResponse(ASSETS / "index.html", media_type="text/html")

    @app.get("/assets/{name}")
    def asset(name: str):
        if name not in ASSET_TYPES or name == "index.html":
            raise HTTPException(404)
        return FileResponse(ASSETS / name, media_type=ASSET_TYPES[name])

    @app.get("/api/info")
    def info():
        return {**app.state.engine.metadata(), "active_job": app.state.jobs.active}

    @app.get("/api/examples/{example_id}/raw")
    def example_file(example_id: str):
        engine = app.state.engine
        if example_id not in engine.examples:
            raise HTTPException(404, "Example not found.")
        # Verify bytes before serving an original development master.
        engine.example_bytes(example_id)
        from generation.corpus_audio import raw_path
        return FileResponse(raw_path(engine.examples[example_id]), media_type="audio/wav",
                            filename=engine.examples[example_id]["sample_id"] + ".wav")

    @app.post("/api/examples", status_code=202)
    def start_example(body: ExampleRequest):
        try:
            payload, filename = app.state.engine.example_bytes(body.example_id)
        except InputError as exc:
            raise HTTPException(422, str(exc)) from exc
        return app.state.jobs.submit(payload, filename, body.example_id)

    @app.post("/api/jobs", status_code=202)
    async def upload(request: Request):
        if request.headers.get("content-type", "").split(";")[0] not in (
                "audio/wav", "audio/x-wav", "audio/wave", "application/octet-stream"):
            raise HTTPException(415, "Send the WAV file as the request body.")
        size, blocks = 0, []
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "Choose a WAV smaller than 2 MB.")
            blocks.append(chunk)
        payload = b"".join(blocks)
        try:
            decode_wav(payload)
        except InputError as exc:
            raise HTTPException(422, str(exc)) from exc
        filename = unquote(request.headers.get("x-c2-filename", "uploaded.wav"))
        filename = re.split(r"[/\\]", filename)[-1]
        filename = "".join(c for c in filename if c.isprintable())[:160] or "uploaded.wav"
        return app.state.jobs.submit(payload, filename)

    @app.get("/api/jobs/{job}")
    def status(job: str):
        return app.state.jobs.get(job)

    @app.post("/api/jobs/{job}/cancel")
    def cancel(job: str):
        return app.state.jobs.cancel(job)

    @app.get("/api/jobs/{job}/result")
    def result(job: str):
        return read_json(app.state.jobs.file(job, "result.json"))

    @app.get("/api/jobs/{job}/files/{name}")
    def download(job: str, name: str, attachment: bool = False):
        path = app.state.jobs.file(job, name)
        media = {".wav": "audio/wav", ".png": "image/png", ".vital": "application/json",
                 ".json": "application/json"}.get(path.suffix, "application/octet-stream")
        return FileResponse(path, media_type=media, filename=name if attachment else None)

    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port between 1024 and 65535.")
    print(f"C2 live app: http://127.0.0.1:{args.port}/", flush=True)
    print(f"Local results: {args.output.resolve()}", flush=True)
    uvicorn.run(create_app(args.output, args.device), host="127.0.0.1", port=args.port,
                access_log=False, workers=1)


if __name__ == "__main__":
    main()
