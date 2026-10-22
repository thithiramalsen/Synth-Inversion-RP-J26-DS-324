"""Build an offline saved-results viewer from verified non-test C2 evidence.

Rendering is performed at build time with the existing Vital/Vita adapter. The
browser never pretends to run inference or a synthesizer.
"""
from __future__ import annotations

import os
for _name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ[_name] = "1"

import argparse
import json
from pathlib import Path
import shutil

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import soundfile as sf

from c2_estimation.pipeline import create_mel_filterbank, extract_log_mel, preprocessing_settings
from c2_estimation.v4.audit_results import DEFAULT_DEVELOPMENT, read_results, verify_folder
from c2_estimation.v4.data import DEFAULT_PREPARED, NAMES, ROOT, from_z, load_prepared, sha, write_json
from c2_estimation.v4.diagnostics import Renderer, distance, perturbation_pair
from c2_estimation.v4.stability import checked_case
from generation.corpus_audio import load_audio, sample_digest

ASSETS = ROOT / "c2_estimation/viewer"
UI_FILES = ("index.html", "app.js", "style.css")


def select_examples(frame, count=6):
    if not 1 <= count <= 8 or frame.sample_id.duplicated().any():
        raise ValueError("Use one to eight unique examples")
    if not (frame.split == "validation").all() or not (frame.validation_role == "reliability").all():
        raise ValueError("Viewer accepts reliability-validation only")
    selected = frame.sort_values("diagnostic_rank").head(count)
    if selected.diagnostic_rank.tolist() != list(range(count)):
        raise ValueError("Expected first fixed diagnostic ranks")
    return selected


def save_playback(path, audio):
    if audio.shape != (132300,) or not np.isfinite(audio).all() or np.max(np.abs(audio)) >= 1:
        raise ValueError("Playback would require clipping/normalization; refusing")
    sf.write(path, audio, 44100, subtype="PCM_16")
    return {"file": path.name, "canonical_float32_sha256": sample_digest(audio),
            "playback_file_sha256": sha(path), "peak": float(np.max(np.abs(audio)))}


def spectrograms(target, predicted, settings, output):
    window = np.hanning(settings["n_fft"]).astype(np.float32)
    bank = create_mel_filterbank(44100, settings["n_fft"], settings["n_mels"], 20., 20000.)
    figure, axes = plt.subplots(1, 2, figsize=(11, 3.4), constrained_layout=True)
    for ax, audio, title in zip(axes, (target, predicted), ("Target", "Frozen ensemble reconstruction"), strict=True):
        mel = extract_log_mel(audio, window, bank, settings["n_fft"], settings["hop_length"], settings["top_db"])
        im = ax.imshow(mel, origin="lower", aspect="auto", extent=(0, 3, 0, 64), cmap="magma", vmin=-80, vmax=0)
        ax.set(title=title, xlabel="Time (s)", ylabel="Mel band (20 Hz–20 kHz)")
    figure.colorbar(im, ax=axes, label="Power (dBFS; fixed reference)", shrink=.85)
    figure.savefig(output, dpi=130)
    plt.close(figure)


def refresh_ui(output):
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, checksum in manifest["files"].items():
        if sha(output / name) != checksum:
            raise ValueError("Viewer artifact changed before UI refresh: " + name)
    for name in UI_FILES:
        shutil.copyfile(ASSETS / name, output / name)
        manifest["files"][name] = sha(output / name)
    manifest["ui_sources"] = {name: sha(ASSETS / name) for name in UI_FILES}
    write_json(manifest_path, manifest)
    print("Refreshed viewer UI only; measured data/audio unchanged", flush=True)


def build(args):
    if args.refresh_ui:
        refresh_ui(args.output)
        return
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Viewer output must be new; use --refresh-ui only for UI changes")
    protocol, source = load_prepared(args.prepared)
    frame, _, probabilities, summary, calibrators = read_results(args.development)
    if calibrators["diagnostic_config"]["protocol_sha256"] != sha(args.prepared / "protocol.json"):
        raise ValueError("Viewer protocol differs from frozen predictions")
    for path, checksum in calibrators["diagnostic_config"]["sources"].items():
        if sha(ROOT / path) != checksum:
            raise ValueError("Renderer source changed: " + path)
    selected = select_examples(frame, args.examples)
    diagnostic_dir = args.development / "diagnostics_reliability-validation"
    diagnostic_config = json.loads((diagnostic_dir / "run_config.json").read_text(encoding="utf-8"))
    diagnostic_summary = json.loads((diagnostic_dir / "summary.json").read_text(encoding="utf-8"))
    audit = verify_folder(args.audit)
    if audit["source_calibration_summary_sha256"] != sha(args.development / "calibration_tau_0.05/summary.json"):
        raise ValueError("Audit belongs to a different calibration run")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "examples").mkdir()
    (args.output / "figures").mkdir()
    renderer = Renderer(protocol["recipe"])
    lower, upper = np.array(protocol["lower"]), np.array(protocol["upper"])
    settings = preprocessing_settings(protocol["recipe"]["synthesis"])
    examples = []
    for row in selected.itertuples(index=False):
        sample_id = row.sample_id
        original = source[source.sample_id == sample_id].iloc[0].to_dict()
        if original["split"] != "validation" or original["validation_role"] != "reliability":
            raise ValueError("Viewer attempted to access an unapproved partition")
        case = checked_case(diagnostic_dir / "cases" / (sample_id + ".json"), diagnostic_config["signature"],
                            sample_id, diagnostic_summary["case_checksums"][sample_id + ".json"])
        folder = args.output / "examples" / sample_id
        folder.mkdir()
        target, rate = load_audio(original, ROOT, verify=True)
        z = np.array([getattr(row, n + "_predicted_z") for n in NAMES])
        actual = np.array([getattr(row, n + "_actual_z") for n in NAMES])
        predicted, readback = renderer.render(z)
        truth, _ = renderer.render(actual)
        if sample_digest(target) != case["target_sha256"] or sample_digest(predicted) != case["rendered_sha256"]:
            raise ValueError("Viewer render differs from measured diagnostic audio")
        if not np.array_equal(target, truth) or not np.isclose(distance(target, predicted), row.R, rtol=0, atol=1e-10):
            raise ValueError("Viewer reconstruction/roundtrip audit failed")
        audio_files = {label: save_playback(folder / (label + ".wav"), audio)
                       for label, audio in (("target", target), ("predicted", predicted), ("true_roundtrip", truth))}
        parameters = []
        probability_index = frame.index[frame.sample_id == sample_id][0]
        for j, name in enumerate(NAMES):
            minus, plus, mode = perturbation_pair(z, j, .02)
            a, actual_a = renderer.render(minus)
            b, actual_b = renderer.render(plus)
            others = np.arange(13) != j
            if not np.array_equal(actual_a[others], readback[others]) or not np.array_equal(actual_b[others], readback[others]):
                raise ValueError("Viewer perturbation changed another control")
            step = float(actual_b[j] - actual_a[j])
            if step <= 0 or not np.isclose(distance(a, b)/step, getattr(row, name + "_S"), rtol=0, atol=1e-10):
                raise ValueError("Viewer sensitivity differs from saved result")
            audio_files[name + "_minus"] = save_playback(folder / (name + "_minus.wav"), a)
            audio_files[name + "_plus"] = save_playback(folder / (name + "_plus.wav"), b)
            parameters.append({"name": name, "predicted_z": float(z[j]), "actual_z": float(actual[j]),
                               "vital_normalized": float(from_z(z, lower, upper)[j]),
                               "error_z": float(abs(z[j]-actual[j])), "correct": bool(abs(z[j]-actual[j]) <= .05),
                               "q": {v: float(q[probability_index, j]) for v, q in probabilities.items()},
                               "U": float(getattr(row, name + "_total_variance_z")),
                               "S": float(getattr(row, name + "_S")), "mode": mode,
                               "minus_z": float(actual_a[j]), "plus_z": float(actual_b[j]), "actual_step_z": step})
        spectrograms(target, predicted, settings, folder / "spectrograms.png")
        example = {"sample_id": sample_id, "diagnostic_rank": int(row.diagnostic_rank), "R": float(row.R),
                   "base_path": "examples/" + sample_id + "/", "parameters": parameters,
                   "audio": audio_files, "roundtrip_exact": True, "predictions_unchanged": True}
        examples.append(example)
        write_json(folder / "example.json", example)
        print(f"Verified and exported saved example {len(examples)}/{args.examples}: {sample_id}", flush=True)
    figure_sources = {
        "per_parameter_brier_differences.png": args.audit / "per_parameter_brier_differences.png",
        "matched_coverage_audit.png": args.audit / "matched_coverage_audit.png",
        "reliability_diagrams.png": args.development / "calibration_tau_0.05/reliability_diagrams.png",
        "risk_coverage.png": args.development / "calibration_tau_0.05/risk_coverage.png",
    }
    for name, path in figure_sources.items():
        shutil.copyfile(path, args.output / "figures" / name)
    payload = {"title": "C2 · Audio to controls", "mode": "saved_results_demo", "test_evaluated": False,
               "dataset_count": 131072, "training_count": 98304, "calibration_count": 2048, "validation_count": 512,
               "parameter_count": 13, "members": 3, "tau_z": .05, "delta_z": .02,
               "example_selection": "First six preassigned reliability-validation diagnostic ranks; no quality selection" if args.examples == 6 else "First preassigned reliability-validation diagnostic ranks; no quality selection",
               "coordinate": "z = (Vital normalized value - research lower bound) / research interval width",
               "audio_note": "PCM16 playback copies, no loudness normalization. Numeric diagnostics use canonical float32 audio before playback quantization.",
               "scope_note": "Fixed Vital preset family, MIDI 60, velocity 0.8, 1.5 s note, 3 s mono render at 44.1 kHz.",
               "probability_note": "Estimated probability of recovering the generating control within ±0.05 of its research range. Not sound similarity or a uniqueness guarantee.",
               "macro_brier": summary["macro_validation_brier"], "comparisons": audit["comparisons"], "examples": examples}
    write_json(args.output / "data.json", payload)
    # Escaped JSON prevents data from terminating script markup if ever embedded later.
    encoded = json.dumps(payload, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    (args.output / "data.js").write_text("window.C2_DATA = " + encoded + ";\n", encoding="utf-8")
    for name in UI_FILES:
        shutil.copyfile(ASSETS / name, args.output / name)
    manifest = {"status": "complete_saved_results_viewer", "test_evaluated": False,
                "example_count": len(examples), "sample_ids": [e["sample_id"] for e in examples],
                "source_sha256": sha(Path(__file__)), "ui_sources": {name: sha(ASSETS / name) for name in UI_FILES},
                "source_audit_summary_sha256": sha(args.audit / "summary.json"),
                "source_calibration_summary_sha256": sha(args.development / "calibration_tau_0.05/summary.json"),
                "files": {str(p.relative_to(args.output)).replace("\\", "/"): sha(p) for p in args.output.rglob("*") if p.is_file()}}
    write_json(args.output / "manifest.json", manifest)
    print("Built local saved-results viewer: " + str(args.output / "index.html"), flush=True)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, default=DEFAULT_PREPARED)
    parser.add_argument("--development", type=Path, default=DEFAULT_DEVELOPMENT)
    parser.add_argument("--audit", type=Path, default=ROOT / "data/processed/c2_v4/results_audit_v1")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--examples", type=int, default=6)
    parser.add_argument("--refresh-ui", action="store_true")
    build(parser.parse_args())
