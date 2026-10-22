"""Local C1 results dashboard with upload-and-predict (no external hosting).

    .\\venv\\Scripts\\python.exe -B -m c1_timbre.dashboard.serve_dashboard
    .\\venv\\Scripts\\python.exe -B -m c1_timbre.dashboard.serve_dashboard --model-run c1_timbre/models/<real run> --port 8800

Opens http://localhost:8800 in the browser. Tabs show the saved results of a model
run (held-out test, validity evaluation, learning curve, control effects, and the
CLAP comparison when train_c1_clap.py has been run); "Try a sound" plays held-out
test sounds and predicts any uploaded WAV with the same Predictor and
c1_features_v2 code as predict_c1.py. Nothing is written to the project; uploads
are read in memory only.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

import numpy as np
import pandas as pd
import soundfile as sf
from scipy.signal import resample_poly

from c1_timbre.features_v2 import FEATURE_NAMES, SR, extract
from c1_timbre.predict_c1 import DEFAULT_RUN, RENDER_FRAMES, TRAITS, Predictor

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
MAX_UPLOAD = 50 * 1024 * 1024
GROUPS = dict(spectral=FEATURE_NAMES[:8], temporal=FEATURE_NAMES[8:17], modulation=FEATURE_NAMES[17:])


def clean(x):
    """JSON-safe copy (NaN/inf become null, numpy scalars become Python numbers)."""
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if not math.isfinite(float(x)) else float(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def comparison(run: Path):
    clap_run = run.parent / run.name.replace("ridge", "clap_ridge", 1)
    path = clap_run / "metrics.json"
    if clap_run == run or not path.exists():
        return None
    m = json.loads(path.read_text(encoding="utf-8"))
    rows = {t: {v: dict(cv_r2=d[v]["cv"]["r2"], test_mae=d[v]["test"]["mae"], baseline_mae=d[v]["test"]["baseline_mae"],
                        ceiling_share=d[v]["ceiling_share"], inputs=d[v]["inputs"])
                for v in ("features19", "clap512", "combined")} for t, d in m["descriptors"].items()}
    paired = {t: {v: d[f"{v}_vs_features19"] for v in ("clap512", "combined")} for t, d in m["descriptors"].items()}
    perm = {t: d["clap512"]["permutation"]["p_value"] for t, d in m["descriptors"].items()}
    return dict(run=clap_run.name, clap=m["clap"], design=m["design"], rows=rows, paired=paired, clap_p=perm)


def summary(run: Path) -> dict:
    metrics = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
    evaluation = json.loads((run / "evaluation/evaluation.json").read_text(encoding="utf-8"))
    tests = pd.read_csv(run / "test_predictions.csv")
    bundle_path = ROOT / metrics["bundle"]
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))["samples"]

    descriptors = {}
    for t in TRAITS:
        m, e = metrics["descriptors"][t], evaluation["descriptors"][t]
        cv, lis, fg = e["repeated_cv"], e["listeners"], e["feature_groups"]
        descriptors[t] = dict(
            test=m["test"], test_ci=m["test_uncertainty"], alpha=m["alpha"],
            cv=dict(mae=cv["mae"], baseline_mae=cv["baseline_mae"], r2=cv["r2"], spearman=cv["spearman"],
                    share_beating_baseline=cv["share_beating_baseline"]),
            permutation=e["permutation"],
            ceiling=dict(noise_ceiling_r=lis["noise_ceiling_r"], model_cv_r=lis["model_cv_r"],
                         share=lis["model_share_of_ceiling"], new_listeners=lis["new_listeners"]),
            groups=dict(values=fg["groups"], strongest=fg["strongest_group"], expected=fg["expected_group"],
                        matches=fg["matches_expectation"]),
            learning=e["learning_curve"]["points"], calibration_slope=e["calibration"]["observed_on_predicted_slope"],
            points=tests[tests.descriptor == t][["sample_id", "observed_mean", "predicted"]].to_dict("records"))

    wide = tests.pivot(index="sample_id", columns="descriptor", values=["observed_mean", "predicted"])
    test_sounds = [dict(sample_id=sid, role=bundle.get(sid, {}).get("role", ""),
                        source=bundle.get(sid, {}).get("source_sample_id", ""),
                        observed={t: wide.loc[sid, ("observed_mean", t)] for t in TRAITS},
                        predicted={t: wide.loc[sid, ("predicted", t)] for t in TRAITS})
                   for sid in wide.index if (bundle_path.parent / "audio" / f"{sid}.wav").exists()]

    effects_dir = ROOT / "c1_timbre/control_effects" / run.name
    effects = None
    if (effects_dir / "effect_summary.csv").exists():
        info = json.loads((effects_dir / "run_info.json").read_text(encoding="utf-8"))
        effects = dict(summary=pd.read_csv(effects_dir / "effect_summary.csv").to_dict("records"),
                       inactive=pd.read_csv(effects_dir / "inactive_context_check.csv").to_dict("records"),
                       bases=len(info["bases"]), renders=info["renders"], steps=info["steps"])

    return clean(dict(run=run.name, simulated=metrics["simulated"], warning=metrics.get("warning"),
                      sounds=metrics["sounds"], design=evaluation["design"], traits=list(TRAITS),
                      descriptors=descriptors, test_sounds=test_sounds, effects=effects,
                      comparison=comparison(run))), bundle_path.parent / "audio"


class App:
    def __init__(self, run: Path):
        self.predictor = Predictor(run)
        self.summary, self.audio_dir = summary(run)
        self.test_ids = {s["sample_id"] for s in self.summary["test_sounds"]}
        self.page = (HERE / "dashboard.html").read_bytes()

    def predict(self, data: bytes, name: str) -> dict:
        try:
            audio, sr = sf.read(io.BytesIO(data), dtype="float64", always_2d=True)
        except Exception as exc:  # unreadable or not audio
            raise ValueError(f"Cannot read '{name}' as audio. Upload a WAV file.") from exc
        notes = []
        if audio.shape[1] > 1:
            notes.append(f"{audio.shape[1]} channels averaged to mono")
        audio = audio.mean(1)
        if sr != SR:
            g = math.gcd(int(sr), SR)
            audio = resample_poly(audio, SR // g, int(sr) // g)
            notes.append(f"resampled from {sr} Hz to {SR} Hz")
        if len(audio) != RENDER_FRAMES:
            notes.append(f"length {len(audio) / SR:.2f} s differs from the 3 s study render")
        if not np.any(np.abs(audio) > 0):
            raise ValueError("The audio is silent.")
        feats = pd.DataFrame([extract(audio, SR)], index=[name])
        out = self.predictor.predict_features(feats).iloc[0]
        x = feats[FEATURE_NAMES].to_numpy(float)[0]
        contributions = {}
        for t in TRAITS:
            m = self.predictor.models[t]
            c = ((x - m.mean) / m.sd) * m.coef
            contributions[t] = dict(intercept=m.intercept, **{g: float(c[[FEATURE_NAMES.index(f) for f in fs]].sum())
                                                               for g, fs in GROUPS.items()})
        return clean(dict(name=name, duration_s=len(audio) / SR, notes=notes,
                          scores={t: out[t] for t in TRAITS}, raw={t: out[f"{t}_raw"] for t in TRAITS},
                          support_distance=out.support_distance, support_threshold=self.predictor.threshold,
                          weak_support=bool(out.weak_support), contributions=contributions))


def handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body: bytes, kind: str):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                return self._send(200, app.page, "text/html; charset=utf-8")
            if path == "/api/summary":
                return self._json(200, app.summary)
            if path.startswith("/audio/"):
                name = Path(path).name
                if name.endswith(".wav") and name[:-4] in app.test_ids:   # only the listed test sounds
                    return self._send(200, (app.audio_dir / name).read_bytes(), "audio/wav")
            self._send(404, b"Not found", "text/plain")

        def do_POST(self):
            if self.path.split("?")[0] != "/api/predict":
                return self._send(404, b"Not found", "text/plain")
            size = int(self.headers.get("Content-Length") or 0)
            if not 0 < size <= MAX_UPLOAD:
                return self._json(400, dict(error="Upload a WAV file under 50 MB."))
            name = Path(unquote(self.headers.get("X-Filename") or "upload.wav")).name
            try:
                self._json(200, app.predict(self.rfile.read(size), name))
            except ValueError as exc:
                self._json(400, dict(error=str(exc)))

        def log_message(self, fmt, *args):
            pass

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-run", type=Path, default=DEFAULT_RUN)
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    app = App(args.model_run.resolve())
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(app))
    url = f"http://localhost:{args.port}"
    print(f"C1 dashboard for {app.summary['run']} at {url}  (Ctrl+C to stop)")
    if app.summary["simulated"]:
        print("NOTE: this model was trained on SIMULATED ratings.")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
