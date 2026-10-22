"""Single-clip inference and verified preset export using the frozen v4 method."""
from __future__ import annotations

import os
for _variable in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ[_variable] = "1"
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

from datetime import datetime, timezone
import hashlib
import io
import json
from functools import lru_cache
from pathlib import Path
import platform
import time
from zipfile import ZipFile

import numpy as np
import pandas as pd
import soundfile as sf
import torch

from c2_estimation.pipeline import (
    choose_device, create_mel_filterbank, extract_log_mel, preprocessing_settings,
    set_deterministic_execution,
)
from c2_estimation.v4.build_viewer import save_playback, spectrograms
from c2_estimation.v4.calibration import VARIANTS, features, predict
from c2_estimation.v4.data import (
    DEFAULT_PREPARED, NAMES, ROOT, bounds, digest_json, from_z, load_prepared, sha,
    to_z, write_json,
)
from c2_estimation.v4.diagnostics import (
    DISTANCE_CONFIG, Renderer, feature_distance, perturbation_pair, representation,
)
from c2_estimation.v4.ensemble import GaussianCNN, combine
from generation.audio_processing import dc_filter
from generation.corpus_audio import canonical_float32, raw_path, sample_digest
from generation.vital_setup import validate_synth

DEFAULT_ENSEMBLE = ROOT / "data/processed/c2_v4/ensemble_full_v1"
DEFAULT_CALIBRATION = ROOT / "data/processed/c2_v4/development_uncertainty_v1/calibration_tau_0.05"
DEFAULT_OUTPUT = ROOT / "data/processed/c2_v4/live_app_v1"
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
VERSION = "c2-live-v1"
LABELS = (
    "Wave shape", "Bend", "Filter cutoff", "Filter resonance", "Filter drive",
    "Amp attack", "Amp decay", "Amp sustain", "Amp release",
    "Filter envelope amount", "Filter envelope attack", "Filter envelope decay",
    "Filter envelope sustain",
)


class InputError(ValueError):
    """An actionable error in the submitted clip."""


class Cancelled(Exception):
    pass


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def decode_wav(payload):
    """Strict v4 input contract. No resampling, trimming or level adjustment."""
    if not payload or len(payload) > MAX_UPLOAD_BYTES:
        raise InputError("Choose a WAV file smaller than 2 MB.")
    try:
        with sf.SoundFile(io.BytesIO(payload)) as handle:
            if handle.format not in ("WAV", "WAVEX"):
                raise InputError("Choose a WAV file.")
            if (handle.samplerate, handle.channels, handle.frames) != (44100, 1, 132300):
                raise InputError("This model needs exactly 3 seconds, mono, at 44,100 Hz.")
            if handle.subtype not in ("PCM_16", "PCM_24", "PCM_32", "FLOAT", "DOUBLE"):
                raise InputError("Use an uncompressed PCM or floating-point WAV.")
            raw = canonical_float32(handle.read(dtype="float32"))
            subtype = handle.subtype
    except InputError:
        raise
    except (RuntimeError, ValueError) as exc:
        raise InputError("This file could not be read as a WAV.") from exc
    if not np.isfinite(raw).all():
        raise InputError("The WAV contains non-finite samples.")
    if np.max(np.abs(raw)) >= 1:
        raise InputError("The WAV reaches full scale. Use the unclipped original.")
    if np.sqrt(np.mean(raw.astype(np.float64) ** 2)) < 1e-8:
        raise InputError("The WAV is silent or too quiet to process.")
    return raw, subtype


def verify_signature(document):
    unsigned = {k: v for k, v in document.items() if k != "signature"}
    if digest_json(unsigned) != document["signature"]:
        raise ValueError("Frozen artifact signature mismatch")


@lru_cache(maxsize=1)
def frozen_source_archive():
    archive = ROOT / "data/processed/team_handoff_v4_131072/team_v4_131072_SHARE.zip"
    expected = "c772f1da490a8d8acd00c452e8dbfc85619e577f024008d6839966c5d5cf24d8"
    if not archive.is_file() or sha(archive) != expected:
        raise ValueError("Mixed-line-ending source verification needs the original, checksummed team share ZIP")
    with ZipFile(archive) as bundle:
        return {name: bundle.read(name) for name in bundle.namelist()
                if name.startswith("generation/") and name.endswith((".py", ".json"))}


def verify_sources(sources):
    checked = {}
    for relative, expected in sources.items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError("Source outside repository")
        actual = sha(path)
        # Git autocrlf is the only accepted byte-level variation. No whitespace,
        # syntax, JSON value, preset or binary-model changes are ignored.
        normalized = path.read_bytes().replace(b"\r\n", b"\n")
        lf = hashlib.sha256(normalized).hexdigest()
        if actual != expected:
            if path.suffix not in (".py", ".json"):
                raise ValueError("Frozen binary changed: " + relative)
            if lf != expected:
                # The historical generator contains mixed CRLF/LF. Compare against
                # verified original bytes, not a guessed replacement fingerprint.
                original = frozen_source_archive().get(relative, b"")
                if (hashlib.sha256(original).hexdigest() != expected
                        or original.replace(b"\r\n", b"\n") != normalized):
                    raise ValueError("Frozen research source changed: " + relative)
        checked[relative] = {"actual_sha256": actual, "frozen_sha256": expected,
                             "line_endings_only": actual != expected}
    return checked


class FrozenRenderer(Renderer):
    """Reuse Renderer.render unchanged, allowing verified Git CRLF conversion at setup."""

    def __init__(self, recipe):
        from generation.generate_corpus import generator
        self.generator = g = generator()
        g.validate_configuration()
        current = g.build_dataset_config(131072, list(g.PARAMS))
        current = {k: v for k, v in current.items() if k not in ("sample_count", "created_utc")}
        expected = recipe["synthesis"]
        source_fields = {
            "generation/scripts/05_generate_pilot_dataset.py": expected["generator_sha256"],
            "generation/audio_processing.py": expected["audio_processing"]["implementation_sha256"],
            "generation/audio_policies/dc_highpass_10hz_v1.json": expected["audio_processing"]["sha256"],
            **recipe["runner_sources"],
        }
        self.source_checks = verify_sources(source_fields)
        current["generator_sha256"] = expected["generator_sha256"]
        for key in ("implementation_sha256", "sha256"):
            current["audio_processing"][key] = expected["audio_processing"][key]
        if current != expected:
            changed = [k for k in current.keys() | expected.keys() if current.get(k) != expected.get(k)]
            raise ValueError("Synthesis recipe changed: " + ", ".join(changed))
        self.lower, self.upper = bounds(recipe)


class Engine:
    """Owned by one worker: no concurrent Torch/Vita/Matplotlib calls."""

    def __init__(self, device="auto", prepared=DEFAULT_PREPARED,
                 ensemble=DEFAULT_ENSEMBLE, calibration=DEFAULT_CALIBRATION):
        prepared, ensemble, calibration = map(Path, (prepared, ensemble, calibration))
        self.protocol, frame = load_prepared(prepared)
        self.config = read_json(ensemble / "run_config.json")
        ensemble_summary = read_json(ensemble / "summary.json")
        calibration_summary = read_json(calibration / "summary.json")
        self.calibrators = read_json(calibration / "calibrators.json")
        verify_signature(self.config)
        verify_signature(self.calibrators)
        if sha(calibration / "calibrators.json") != calibration_summary["files"]["calibrators.json"]:
            raise ValueError("Calibrator checksum mismatch")
        diagnostic = self.calibrators["diagnostic_config"]
        if (self.config["protocol_sha256"] != sha(prepared / "protocol.json")
                or diagnostic["protocol_sha256"] != self.config["protocol_sha256"]
                or diagnostic["ensemble_config_sha256"] != sha(ensemble / "run_config.json")
                or diagnostic["distance_config"] != DISTANCE_CONFIG
                or diagnostic["delta_z"] != self.protocol["delta_z"]
                or self.calibrators["tau_z"] != .05
                or self.calibrators["primary_variant"] != "g(U,S,R)"
                or self.calibrators["test_evaluated"]
                or self.calibrators["test_method_locked"]
                or ensemble_summary["status"] != "completed_probabilistic_ensemble"
                or len(ensemble_summary["members"]) != 3
                or tuple(self.config["parameter_names"]) != NAMES):
            raise ValueError("Frozen model, diagnostic and calibration settings do not agree")
        source_checks = verify_sources({
            **self.config["sources"], **diagnostic["sources"],
            "c2_estimation/v4/calibration.py": self.calibrators["source_sha256"],
        })
        self.lower, self.upper = np.array(self.protocol["lower"]), np.array(self.protocol["upper"])
        if not (np.array_equal(self.lower, self.config["lower"])
                and np.array_equal(self.upper, self.config["upper"])):
            raise ValueError("Control ranges differ")
        set_deterministic_execution(self.config["seed"], 4)
        self.device = choose_device(device)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        self.models = []
        for member, expected in zip(ensemble_summary["members"], diagnostic["member_checkpoints"], strict=True):
            checkpoint = ensemble / f"member_{member['member']:02d}/best_model.pt"
            if sha(checkpoint) != member["checkpoint_sha256"] or expected != member["checkpoint_sha256"]:
                raise ValueError("Frozen checkpoint changed")
            saved = torch.load(checkpoint, map_location=self.device, weights_only=True)
            if saved["signature"] != self.config["signature"]:
                raise ValueError("Checkpoint/config mismatch")
            model = GaussianCNN(self.device, self.config["variance_floor_z_squared"]).to(self.device)
            model.load_state_dict(saved["model"])
            self.models.append(model.eval())
        self.settings = preprocessing_settings(self.protocol["recipe"]["synthesis"])
        self.window = np.hanning(self.settings["n_fft"]).astype(np.float32)
        self.bank = create_mel_filterbank(44100, self.settings["n_fft"], 64, 20., 20000.)
        self.renderer = FrozenRenderer(self.protocol["recipe"])
        # Only metadata is read for the test safeguard. No test WAV is opened.
        test = frame[frame.split == "test"]
        self.test_hashes = set(test.raw_samples_sha256) | set(test.processed_samples_sha256)
        self.processed_hashes = set(frame.processed_samples_sha256)
        selected = frame[(frame.split == "validation") & (frame.validation_role == "reliability")
                         & frame.diagnostic_rank.between(0, 2)].sort_values("diagnostic_rank")
        if selected.diagnostic_rank.tolist() != [0, 1, 2]:
            raise ValueError("Predetermined demonstration examples are missing")
        # Retain audio provenance only, never generating controls as inference inputs.
        columns = ["sample_id", "diagnostic_rank", "raw_audio_path",
                   "raw_samples_sha256", "processed_samples_sha256"]
        self.examples = {str(i): row for i, row in enumerate(selected[columns].to_dict("records"), 1)}
        self.provenance = {
            "protocol_sha256": sha(prepared / "protocol.json"),
            "ensemble_config_sha256": sha(ensemble / "run_config.json"),
            "member_checkpoints": diagnostic["member_checkpoints"],
            "calibrators_sha256": sha(calibration / "calibrators.json"),
            "app_sources": {p.name: sha(p) for p in Path(__file__).parent.glob("*.py")},
            "device": str(self.device), "torch": str(torch.__version__),
            "python": platform.python_version(), "numpy": np.__version__,
            "inference_batch_size": 1,
            "frozen_source_checks": {**source_checks, **self.renderer.source_checks},
        }
        # This is already measured development evidence, not a new evaluation.
        self.evidence = {
            "inverse_validation_count": self.config["validation_count"],
            "reliability_validation_count": calibration_summary["validation_count"],
            "macro_brier": calibration_summary["macro_validation_brier"],
            "regression": pd.read_csv(ensemble / "parameter_metrics.csv").query(
                "coordinate == 'research_z'").to_dict("records"),
            "note": "Development results. Reliability validation selected regularization; final test remains reserved.",
            "sensitivity_note": "The development comparison does not establish extra benefit from S beyond U+R.",
        }

    def metadata(self):
        return {
            "version": VERSION, "device": str(self.device), "max_bytes": MAX_UPLOAD_BYTES,
            "examples": [{"id": key, "label": f"Example {key}", "sample_id": row["sample_id"]}
                         for key, row in self.examples.items()],
            "example_selection": "First three preassigned reliability-validation ranks; selected before looking at quality.",
            "evidence": self.evidence,
        }

    def example_bytes(self, key):
        if key not in self.examples:
            raise InputError("Unknown example.")
        row = self.examples[key]
        payload = raw_path(row, ROOT).read_bytes()
        raw, _ = decode_wav(payload)
        if sample_digest(raw) != row["raw_samples_sha256"]:
            raise ValueError("Example raw audio changed")
        return payload, row["sample_id"] + ".wav"

    def prepare(self, payload):
        raw, subtype = decode_wav(payload)
        raw_hash = sample_digest(raw)
        if raw_hash in self.test_hashes:
            raise InputError("This clip belongs to the reserved test set. Use a development example.")
        if raw_hash in self.processed_hashes:
            raise InputError("This is an already conditioned corpus clip. Upload its raw master to avoid filtering twice.")
        target = canonical_float32(dc_filter(raw, 44100))
        if sample_digest(target) in self.test_hashes:
            raise InputError("This clip belongs to the reserved test set.")
        if not np.isfinite(target).all() or np.max(np.abs(target)) >= 1:
            raise InputError("Conditioning would produce an invalid or clipped playback copy.")
        return target, {
            "subtype": subtype, "sample_rate": 44100, "channels": 1, "seconds": 3,
            "raw_samples_sha256": raw_hash,
            "conditioned_samples_sha256": sample_digest(target),
            "file_sha256": hashlib.sha256(payload).hexdigest(),
            "conditioning": "dc_highpass_10hz_v1, once; no resampling, trimming or loudness normalization",
        }

    def estimate(self, target):
        mel = extract_log_mel(target, self.window, self.bank, self.settings["n_fft"],
                              self.settings["hop_length"], self.settings["top_db"])
        if mel.shape != (64, 259) or not np.isfinite(mel).all():
            raise ValueError("Invalid log-mel input")
        features_array = ((mel - self.config["feature_mean_train_only"])
                          / self.config["feature_std_train_only"])
        x = torch.from_numpy(features_array[None, None]).to(self.device)
        means, variances = [], []
        with torch.inference_mode():
            for model in self.models:
                mu, var = model(x)
                means.append(mu.cpu().numpy())
                variances.append(var.cpu().numpy())
        return tuple(values[0] for values in combine(np.stack(means), np.stack(variances)))

    def export_patch(self, z, expected_audio, expected_readback, path):
        """Write real Vita serialization, reload from disk and audit without reapplying controls."""
        g = self.renderer.generator
        synth = g.create_synth()
        if not synth.load_preset(str(g.BASE_PRESET)):
            raise ValueError("Cannot load base preset")
        g.apply_fixed_controls(synth)
        controls = synth.get_controls()
        values = from_z(z, self.lower, self.upper)
        for j, name in enumerate(NAMES):
            controls[g.PARAMS[name]["control"]].set_normalized(float(values[j]))
        payload = synth.to_json()
        json.loads(payload)  # Fail before making a downloadable file if serialization is invalid.
        path.write_text(payload, encoding="utf-8")
        loaded = g.create_synth()
        if not loaded.load_preset(str(path)):
            raise ValueError("Exported Vital preset could not be reloaded")
        validate_synth(loaded, g.PROFILE)
        readback = np.array([loaded.get_controls()[g.PARAMS[n]["control"]].get_normalized() for n in NAMES])
        if not np.array_equal(to_z(readback, self.lower, self.upper), expected_readback):
            raise ValueError("Exported preset changed predicted controls")
        display = [loaded.get_control_text(g.PARAMS[n]["control"]) for n in NAMES]
        stereo = g.render_sample(loaded)
        if np.max(np.abs(stereo[0] - stereo[1])) > 1e-10:
            raise ValueError("Exported preset changed channel behavior")
        audio = canonical_float32(dc_filter(stereo[0].copy(), 44100))
        if not np.array_equal(audio, expected_audio):
            raise ValueError("Exported preset does not reproduce the delivered reconstruction")
        return display, {
            "reload_via": "Vita load_preset", "controls_exact": True,
            "conditioned_audio_exact": True, "patch_sha256": sha(path),
            "desktop_vital_checked": False,
        }

    def run(self, payload, filename, folder, progress=lambda *a: None, cancelled=lambda: False,
            example_id=None):
        folder = Path(folder)
        start = time.perf_counter()
        timings = {}

        def stage(name, detail, completed):
            if cancelled():
                raise Cancelled()
            progress(name, detail, completed)

        stage("input", "Checking the WAV", 1)
        target, input_info = self.prepare(payload)
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "input.wav").write_bytes(payload)
        stage("prediction", "Predicting the 13 controls", 2)
        tick = time.perf_counter()
        z, within, between, total = self.estimate(target)
        frozen = z.copy()
        timings["prediction"] = time.perf_counter() - tick
        stage("reconstruction", "Rendering the predicted patch", 3)
        tick = time.perf_counter()
        base, readback = self.renderer.render(z)
        target_features, base_features = representation(target), representation(base)
        residual = feature_distance(target_features, base_features)
        save_playback(folder / "target.wav", target)
        save_playback(folder / "reconstruction.wav", base)
        # Canonical diagnostic audio is also available independently of browser PCM16 copies.
        sf.write(folder / "reconstruction_float.wav", base, 44100, subtype="FLOAT")
        timings["reconstruction"] = time.perf_counter() - tick
        tick = time.perf_counter()
        rows = []
        diagnostics = {"R": residual["distance"]}
        for j, name in enumerate(NAMES):
            stage("sensitivity", f"Checking {LABELS[j].lower()} ({j + 1}/13)", 4 + j)
            minus, plus, mode = perturbation_pair(z, j, self.protocol["delta_z"])
            a, actual_a = self.renderer.render(minus)
            b, actual_b = self.renderer.render(plus)
            other = np.arange(13) != j
            if not (np.array_equal(actual_a[other], readback[other])
                    and np.array_equal(actual_b[other], readback[other])):
                raise ValueError("Perturbation changed another control")
            step = float(actual_b[j] - actual_a[j])
            if step <= 0:
                raise ValueError("Perturbation has no positive engine readback span")
            sensitivity = feature_distance(representation(a), representation(b))["distance"] / step
            save_playback(folder / f"{name}_minus.wav", a)
            save_playback(folder / f"{name}_plus.wav", b)
            diagnostics[name + "_total_variance_z"] = float(total[j])
            diagnostics[name + "_S"] = sensitivity
            rows.append({
                "name": name, "label": LABELS[j], "predicted_z": float(z[j]),
                "vital_normalized": float(from_z(z, self.lower, self.upper)[j]),
                "engine_readback_z": float(readback[j]), "U": float(total[j]),
                "within_variance_z": float(within[j]), "between_variance_z": float(between[j]),
                "S": sensitivity, "minus_z": float(actual_a[j]), "plus_z": float(actual_b[j]),
                "actual_step_z": step, "perturbation_mode": mode,
            })
        timings["sensitivity"] = time.perf_counter() - tick
        stage("reliability", "Estimating reliability for each control", 17)
        frame = pd.DataFrame([diagnostics])
        for row in rows:
            models = self.calibrators["models"][row["name"]]
            row["q"] = {variant: float(predict(models[variant], features(frame, row["name"], columns))[0])
                        for variant, columns in VARIANTS.items()}
            if not all(np.isfinite(q) and 0 <= q <= 1 for q in row["q"].values()):
                raise ValueError("Invalid reliability estimate")
        stage("export", "Checking the exported patch", 18)
        tick = time.perf_counter()
        display, export_audit = self.export_patch(z, base, readback, folder / "predicted.vital")
        for row, value in zip(rows, display, strict=True):
            row["vital_display"] = value
        timings["export_check"] = time.perf_counter() - tick
        stage("plots", "Preparing the comparison", 19)
        spectrograms(target, base, self.settings, folder / "spectrograms.png")
        if not np.array_equal(z, frozen):
            raise ValueError("Diagnostics changed the delivered prediction")
        stage("saving", "Saving the result", 20)
        result = {
            "version": VERSION, "created_utc": datetime.now(timezone.utc).isoformat(),
            "mode": "live_inference", "filename": filename, "example_id": example_id,
            "input": input_info, "parameters": rows, "R": residual["distance"],
            "R_resolutions": residual["resolutions"], "tau_z": .05, "delta_z": .02,
            "primary_calibrator": "g(U,S,R)", "export_audit": export_audit,
            "reconstruction_samples_sha256": sample_digest(base),
            "prediction_unchanged": True, "ground_truth_used": False,
            "test_evaluated": False, "test_method_locked": False,
            "provenance": self.provenance, "timings_seconds": timings,
            "elapsed_seconds": time.perf_counter() - start,
            "scope": "Restricted Vital v4 family; MIDI 60, velocity 0.8, note held 1.5 s, 3 s render.",
            "reliability_note": "Development estimate of generating-control correctness within +/-0.05 of its research interval. Not sound similarity. Arbitrary recordings are outside the validated scope.",
        }
        write_json(folder / "result.json", result)
        manifest = {"version": VERSION, "files": {p.name: sha(p) for p in folder.iterdir() if p.is_file()}}
        write_json(folder / "manifest.json", manifest)
        return result
