"""Start a local drag-and-drop audio similarity page."""
from __future__ import annotations

import argparse
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
import json
from pathlib import Path
import sys

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from c4_metric.c3_adapter import AdaptedScorer
from c4_metric.score_pair import similarity_index_0_to_100
from c4_metric.similarity import score_similarity

PAGE_PATH = Path(__file__).with_name("audio_similarity.html")
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_REQUEST_BYTES = 2 * MAX_FILE_BYTES * 4 // 3 + 1_000_000
METHODS = {"c4", "clap", "mfcc", "stft", "ms_stft"}


def load_audio(payload: str, label: str) -> tuple[np.ndarray, int]:
    try:
        content = base64.b64decode(payload, validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError(f"Could not decode {label} audio upload") from error
    if not content:
        raise ValueError(f"{label} audio file is empty")
    if len(content) > MAX_FILE_BYTES:
        raise ValueError(f"{label} audio file exceeds the 20 MB limit")
    try:
        audio, sample_rate = sf.read(BytesIO(content), dtype="float64", always_2d=True)
    except Exception as error:
        raise ValueError(f"Could not read {label} audio. Try a WAV, FLAC, or OGG file.") from error
    mono = np.asarray(audio.mean(axis=1), dtype=np.float32)
    return mono, int(sample_rate)


class SimilarityHandler(BaseHTTPRequestHandler):
    scorer: AdaptedScorer
    synthetic_checkpoint: bool

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: dict) -> None:
        self._send(status, json.dumps(value).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        if self.path not in {"/", "/index.html"}:
            self._json(404, {"error": "Not found"})
            return
        try:
            page = PAGE_PATH.read_bytes()
        except OSError as error:
            self._json(500, {"error": f"Could not load the interface: {error}"})
            return
        self._send(200, page, "text/html; charset=utf-8")

    def do_POST(self) -> None:
        if self.path != "/score":
            self._json(404, {"error": "Not found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > MAX_REQUEST_BYTES:
                raise ValueError("Upload is empty or too large. Each audio file must be at most 20 MB.")
            payload = json.loads(self.rfile.read(size))
            method = str(payload.get("method", "c4")).casefold()
            if method not in METHODS:
                raise ValueError(f"Unknown method '{method}'")
            reference, reference_rate = load_audio(payload.get("reference_audio", ""), "Reference")
            candidate, candidate_rate = load_audio(payload.get("candidate_audio", ""), "Candidate")

            reference_source = (reference, reference_rate)
            candidate_source = (candidate, candidate_rate)
            if method == "c4":
                score = self.scorer.score(reference_source, candidate_source)
            else:
                score = score_similarity(
                    reference_source,
                    candidate_source,
                    method,
                    clap_local_files_only=True,
                )

            index = similarity_index_0_to_100(score.similarity, method)
            result = {
                "method": method,
                "similarity": score.similarity,
                "similarity_index_0_to_100": round(index, 2),
                "similarity_display": f"{index:.1f}/100 (rescaled index, not a true percentage)",
                "distance": score.distance,
                "score_direction": "higher similarity means more similar; lower distance means more similar",
                "reference_name": str(payload.get("reference_name", "Reference audio")),
                "candidate_name": str(payload.get("candidate_name", "Candidate audio")),
                "note": (
                    "The current C4 checkpoint uses synthetic preferences. This is a software "
                    "demonstration, not a validated human-perceptual score."
                    if method == "c4" and self.synthetic_checkpoint else
                    "The 0-100 display is a rescaled model score, not a literal percentage of perceptual similarity."
                ),
            }
            self._json(200, result)
        except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as error:
            self._json(400, {"error": str(error)})
        except Exception as error:
            self._json(500, {"error": f"Scoring failed: {error}"})

    def log_message(self, format: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="Local bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--checkpoint", type=Path,
                        default=ROOT / "c4_metric/outputs/synthetic_training/best_model.pt")
    parser.add_argument("--allow-synthetic-checkpoint", action="store_true",
                        help="Allow the current synthetic-label checkpoint for software demonstration only")
    args = parser.parse_args()

    scorer = AdaptedScorer(
        args.checkpoint,
        clap_local_files_only=True,
        allow_synthetic_checkpoint=args.allow_synthetic_checkpoint,
    )
    SimilarityHandler.scorer = scorer
    SimilarityHandler.synthetic_checkpoint = args.allow_synthetic_checkpoint
    server = HTTPServer((args.host, args.port), SimilarityHandler)
    print(f"Audio similarity app listening at http://{args.host}:{args.port}")
    print("This server only listens locally. Press Ctrl+C to stop it.")
    if args.allow_synthetic_checkpoint:
        print("C4 uses synthetic labels here; scores are software demonstrations only.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping local audio similarity app.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
