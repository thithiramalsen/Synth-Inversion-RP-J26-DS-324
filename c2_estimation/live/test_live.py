"""Contract and HTTP tests; synthetic fixtures never touch a participant database."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import numpy as np
import soundfile as sf

from .engine import (
    Cancelled, DEFAULT_OUTPUT, Engine, InputError, MAX_UPLOAD_BYTES, ROOT,
    decode_wav, sample_digest, sha, verify_sources, write_json,
)
from .server import Jobs, create_app


def wav(audio=None, rate=44100, subtype="FLOAT", format="WAV"):
    if audio is None:
        audio = .1 * np.sin(np.arange(132300) * 2 * np.pi * 220 / 44100)
    stream = io.BytesIO()
    sf.write(stream, audio, rate, format=format, subtype=subtype)
    return stream.getvalue()


class FakeEngine:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.examples = {}

    def metadata(self):
        return {"version": "test", "device": "fixture", "examples": [], "evidence": {}}

    def example_bytes(self, key):
        if key != "1":
            raise InputError("Unknown example.")
        return wav(), "fixture.wav"

    def run(self, payload, filename, folder, progress, cancelled, example_id):
        self.started.set()
        progress("sensitivity", "Fixture waits", 4)
        if not self.release.wait(timeout=5):
            raise TimeoutError("Test fixture was not released")
        if cancelled():
            raise Cancelled()
        folder.mkdir(parents=True)
        result = {"filename": filename, "mode": "test_fixture", "ground_truth_used": False}
        write_json(folder / "result.json", result)
        (folder / "predicted.vital").write_text('{"fixture":true}', encoding="utf-8")
        write_json(folder / "manifest.json", {
            "files": {p.name: sha(p) for p in folder.iterdir() if p.is_file()}})
        return result


def wait_state(client, job, states):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        value = client.get("/api/jobs/" + job).json()
        if value["state"] in states:
            return value
        time.sleep(.01)
    raise AssertionError("Job did not reach expected state")


class InputTests(unittest.TestCase):
    def test_wav_contract_and_invalid_audio(self):
        for subtype in ("PCM_16", "PCM_24", "FLOAT"):
            audio, _ = decode_wav(wav(subtype=subtype))
            self.assertEqual(audio.shape, (132300,))
        bad = [
            b"not audio", b"x" * (MAX_UPLOAD_BYTES + 1),
            wav(rate=48000), wav(np.zeros(400)), wav(np.zeros((132300, 2))),
            wav(np.zeros(132300)), wav(np.ones(132300)),
            wav(np.full(132300, np.nan)), wav(np.full(132300, np.inf)),
            wav(format="AIFF", subtype="PCM_16"),
        ]
        for payload in bad:
            with self.subTest(size=len(payload)), self.assertRaises(InputError):
                decode_wav(payload)

    def test_preprocessing_test_safeguard_and_double_filter(self):
        engine = Engine.__new__(Engine)
        engine.test_hashes = set()
        engine.processed_hashes = set()
        payload = wav()
        target, info = engine.prepare(payload)
        self.assertEqual(sample_digest(target), info["conditioned_samples_sha256"])
        engine.test_hashes = {info["raw_samples_sha256"]}
        with self.assertRaisesRegex(InputError, "reserved"):
            engine.prepare(payload)
        engine.test_hashes = {info["conditioned_samples_sha256"]}
        with self.assertRaisesRegex(InputError, "reserved"):
            engine.prepare(payload)
        engine.test_hashes = set()
        engine.processed_hashes = {info["raw_samples_sha256"]}
        with self.assertRaisesRegex(InputError, "already conditioned"):
            engine.prepare(payload)

    def test_line_ending_verification_rejects_content_changes(self):
        with tempfile.TemporaryDirectory(dir=DEFAULT_OUTPUT.parent, prefix="live_source_test_") as tmp:
            root = Path(tmp)
            source = root / "example.py"
            source.write_bytes(b"x = 1\n")
            expected = sha(source)
            source.write_bytes(b"x = 1\r\n")
            with patch("c2_estimation.live.engine.ROOT", root):
                self.assertTrue(verify_sources({"example.py": expected})["example.py"]["line_endings_only"])
                source.write_bytes(b"x = 2\r\n")
                with patch("c2_estimation.live.engine.frozen_source_archive", return_value={}):
                    with self.assertRaisesRegex(ValueError, "source changed"):
                        verify_sources({"example.py": expected})


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=DEFAULT_OUTPUT.parent, prefix="live_http_test_")
        self.output = Path(self.tmp.name)
        self.fake = FakeEngine()
        self.headers = {"X-C2-Request": "1", "Content-Type": "audio/wav"}

    def tearDown(self):
        self.fake.release.set()
        self.tmp.cleanup()

    def client(self):
        return TestClient(create_app(self.output, engine_factory=lambda: self.fake),
                          base_url="http://127.0.0.1:8770")

    def test_upload_busy_results_reopen_and_tamper(self):
        with self.client() as client:
            self.assertEqual(client.get("/").status_code, 200)
            self.assertIn("frame-ancestors", client.get("/").headers["content-security-policy"])
            response = client.post("/api/jobs", content=wav(), headers={
                **self.headers, "X-C2-Filename": "..%2F..%2Fuploaded.wav"})
            self.assertEqual(response.status_code, 202)
            job = response.json()["id"]
            self.assertTrue(self.fake.started.wait(2))
            self.assertEqual(client.post("/api/jobs", content=wav(), headers=self.headers).status_code, 409)
            self.assertEqual(client.get(f"/api/jobs/{job}/files/predicted.vital").status_code, 409)
            self.fake.release.set()
            self.assertEqual(wait_state(client, job, {"complete", "failed"})["state"], "complete")
            result = client.get(f"/api/jobs/{job}/result").json()
            self.assertEqual(result["filename"], "uploaded.wav")
            response = client.get(f"/api/jobs/{job}/files/predicted.vital?attachment=true")
            self.assertEqual(response.status_code, 200)
            self.assertIn("attachment", response.headers["content-disposition"])
            self.assertEqual(client.get(f"/api/jobs/{job}/files/manifest.json").status_code, 404)
            self.assertEqual(client.get("/api/jobs/" + "f" * 32).status_code, 404)
            self.assertEqual(client.get("/api/jobs/not-an-id").status_code, 404)
        with self.client() as client:
            self.assertEqual(client.get(f"/api/jobs/{job}/result").status_code, 200)
            (self.output / "jobs" / job / "predicted.vital").write_text("tampered")
            self.assertEqual(client.get(f"/api/jobs/{job}/files/predicted.vital").status_code, 409)

    def test_origin_format_size_cancel_and_interrupted_run(self):
        with self.client() as client:
            self.assertEqual(client.post("/api/jobs", content=wav()).status_code, 403)
            self.assertEqual(client.get("/api/info", headers={"Host": "evil.example"}).status_code, 403)
            self.assertEqual(client.post("/api/jobs", content=wav(), headers={
                **self.headers, "Origin": "https://evil.example"}).status_code, 403)
            self.assertEqual(client.post("/api/jobs", content=b"bad", headers=self.headers).status_code, 422)
            self.assertEqual(client.post("/api/jobs", content=b"x" * (MAX_UPLOAD_BYTES + 1),
                                         headers=self.headers).status_code, 413)
            self.assertEqual(client.post("/api/jobs", content=wav(), headers={
                **self.headers, "Content-Type": "text/plain"}).status_code, 415)
            response = client.post("/api/examples", json={"example_id": "1"}, headers={"X-C2-Request": "1"})
            job = response.json()["id"]
            self.assertTrue(self.fake.started.wait(2))
            self.assertEqual(client.post(f"/api/jobs/{job}/cancel", headers=self.headers).status_code, 200)
            self.fake.release.set()
            self.assertEqual(wait_state(client, job, {"cancelled", "failed"})["state"], "cancelled")
            self.assertEqual(client.get(f"/api/jobs/{job}/result").status_code, 409)
        job = "b" * 32
        write_json(self.output / "status" / (job + ".json"),
                   {"id": job, "state": "running", "detail": "incomplete"})
        with self.client() as client:
            self.assertEqual(client.get("/api/jobs/" + job).json()["state"], "interrupted")


if __name__ == "__main__":
    unittest.main()
