"""Black-box R/S measurements and one reproducible development worked example.

This module never optimizes a patch, consumes test clips, or fabricates confidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import soundfile as sf

from c2_estimation.v4.data import (DEFAULT_PREPARED, NAMES, ROOT, bounds, from_z,
                                  load_prepared, sha, to_z, write_json)
from generation.corpus_audio import canonical_float32, load_audio, sample_digest
from generation.audio_processing import dc_filter

DISTANCE_CONFIG = {
    "name": "symmetric_mrstft_v1", "sample_rate": 44100,
    "fft_sizes": [512, 1024, 2048], "hop_sizes": [128, 256, 512],
    "window": "numpy.hanning_symmetric", "center_padding": "reflect",
    "magnitude_scaling": "abs(rfft)/sum(window)*2", "magnitude_floor_dbfs": -80,
    "spectral_convergence": "norm(A-B)/(0.5*(norm(A)+norm(B))+1e-12)",
    "log_difference": "mean(abs(ln(max(A,1e-4))-ln(max(B,1e-4))))",
    "resolution_aggregation": "mean(SC+LM)", "loudness_normalization": "none",
    "status": "development definition; no perceptual threshold validated",
}


def representation(audio):
    audio = np.asarray(audio, dtype=np.float64)
    if audio.ndim != 1 or len(audio) != 132300 or not np.isfinite(audio).all():
        raise ValueError("Expected finite mono three-second 44.1 kHz audio")
    result = []
    for size, hop in zip(DISTANCE_CONFIG["fft_sizes"], DISTANCE_CONFIG["hop_sizes"], strict=True):
        window = np.hanning(size)
        frames = np.lib.stride_tricks.sliding_window_view(np.pad(audio, size//2, mode="reflect"), size)[::hop]
        result.append(np.abs(np.fft.rfft(frames * window, axis=1)) / (window.sum()/2))
    return result


def feature_distance(a, b):
    if len(a) != 3 or len(b) != 3:
        raise ValueError("Expected three STFT resolutions")
    terms = []
    for first, second in zip(a, b, strict=True):
        if first.shape != second.shape or not np.isfinite(first).all() or not np.isfinite(second).all():
            raise ValueError("Incompatible or nonfinite STFT representations")
        sc = np.linalg.norm(first-second) / (.5*(np.linalg.norm(first)+np.linalg.norm(second)) + 1e-12)
        log_difference = np.abs(np.log(np.maximum(first, 1e-4)) - np.log(np.maximum(second, 1e-4))).mean()
        terms.append({"spectral_convergence": float(sc), "log_magnitude": float(log_difference)})
    return {"distance": float(np.mean([t["spectral_convergence"]+t["log_magnitude"] for t in terms])),
            "resolutions": terms}


def distance(a, b):
    return feature_distance(representation(a), representation(b))["distance"]


def perturbation_pair(z, parameter, delta=.02):
    z = np.asarray(z, dtype=np.float64)
    if z.shape != (13,) or not np.isfinite(z).all() or np.any(z < 0) or np.any(z > 1):
        raise ValueError("Expected 13 bounded research coordinates")
    if not 0 < delta <= .5 or not 0 <= parameter < 13:
        raise ValueError("Invalid step or parameter")
    minus, plus = z.copy(), z.copy()
    if z[parameter] < delta:
        plus[parameter] += delta
        mode = "forward"
    elif z[parameter] > 1-delta:
        minus[parameter] -= delta
        mode = "backward"
    else:
        minus[parameter] -= delta
        plus[parameter] += delta
        mode = "central"
    return minus, plus, mode


class Renderer:
    def __init__(self, recipe):
        from generation.generate_corpus import generator, recipe as current_recipe
        if current_recipe(131072) != recipe:
            raise ValueError("Current synthesis runtime differs from the frozen corpus recipe")
        self.generator = generator()
        self.lower, self.upper = bounds(recipe)

    def render(self, z):
        values = from_z(z, self.lower, self.upper)
        g = self.generator
        synth = g.create_synth()
        if not synth.load_preset(str(g.BASE_PRESET)):
            raise ValueError("Cannot load frozen preset")
        g.apply_fixed_controls(synth)
        controls = synth.get_controls()
        for j, name in enumerate(NAMES):
            controls[g.PARAMS[name]["control"]].set_normalized(float(values[j]))
        actual = np.array([controls[g.PARAMS[name]["control"]].get_normalized() for name in NAMES])
        if not np.allclose(actual, values, rtol=0, atol=2e-6):
            raise ValueError("Unexpected engine readback")
        stereo = g.render_sample(synth)
        if np.max(np.abs(stereo[0] - stereo[1])) > 1e-10:
            raise ValueError("Unexpected stereo difference")
        audio = canonical_float32(dc_filter(stereo[0].copy(), 44100))
        return audio, to_z(actual, self.lower, self.upper)


def worked_example(prepared: Path, run: Path, output: Path, sample_id: str | None = None):
    protocol, frame = load_prepared(prepared)
    config = json.loads((run / "run_config.json").read_text(encoding="utf-8"))
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    if config["protocol_sha256"] != sha(prepared / "protocol.json"):
        raise ValueError("Model and diagnostic protocol differ")
    if summary["predictions_sha256"] != sha(run / "validation_predictions.csv"):
        raise ValueError("Frozen validation predictions changed")
    predictions = pd.read_csv(run / "validation_predictions.csv")
    if sample_id is None:
        # Lowest-index inverse-validation prediction: selected without inspecting its quality.
        row = predictions.sort_values("sample_index").iloc[0]
        selection = "lowest-index inverse-validation prediction"
    else:
        selected = predictions[predictions.sample_id == sample_id]
        if len(selected) != 1:
            raise ValueError("Requested clip must occur once in inverse-validation predictions")
        row = selected.iloc[0]
        selection = "specified inverse-validation clip for development comparison"
    source = frame[frame.sample_id == row.sample_id].iloc[0]
    if source.split != "validation" or source.validation_role != "inverse":
        raise ValueError("Worked example must be inverse-validation, never test")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Worked-example output must be new; existing audio is preserved")
    renderer = Renderer(protocol["recipe"])
    target, _ = load_audio(source.to_dict(), ROOT, verify=True)
    predicted_z = np.array([row[n + "_predicted_z"] for n in NAMES])
    true_z = source[[n + "_z" for n in NAMES]].to_numpy(dtype=np.float64)
    frozen = predicted_z.copy()
    prediction, actual_base = renderer.render(predicted_z)
    repeated, _ = renderer.render(predicted_z)
    if not np.array_equal(prediction, repeated):
        raise ValueError("Repeated predicted-patch renders are not deterministic")
    true_reconstruction, _ = renderer.render(true_z)
    midpoint, _ = renderer.render(np.full(13, .5))
    target_features, prediction_features = representation(target), representation(prediction)
    output.mkdir(parents=True, exist_ok=True)
    for name, audio in (("target", target), ("predicted", prediction),
                        ("true_parameter_roundtrip", true_reconstruction), ("midpoint_patch", midpoint)):
        sf.write(output / f"{name}.wav", audio, 44100, subtype="FLOAT")
    diagnostic_rows = []
    for j, name in enumerate(NAMES):
        minus, plus, mode = perturbation_pair(predicted_z, j, protocol["delta_z"])
        minus_audio, actual_minus = renderer.render(minus)
        plus_audio, actual_plus = renderer.render(plus)
        other = np.arange(13) != j
        if not np.array_equal(actual_minus[other], actual_base[other]) or not np.array_equal(actual_plus[other], actual_base[other]):
            raise ValueError("Perturbation changed another control")
        step = float(actual_plus[j]-actual_minus[j])
        if step <= 0:
            raise ValueError("Perturbation disappeared in engine readback")
        minus_features, plus_features = representation(minus_audio), representation(plus_audio)
        change = feature_distance(minus_features, plus_features)["distance"]
        diagnostic_rows.append({"parameter": name, "predicted_z": float(predicted_z[j]),
            "true_z": float(true_z[j]), "error_z": float(abs(predicted_z[j]-true_z[j])),
            "correct_at_tau_005": bool(abs(predicted_z[j]-true_z[j]) <= .05),
            "mode": mode, "actual_step_z": step, "minus_plus_distance": change, "sensitivity": change/step,
            "target_minus_distance": feature_distance(target_features, minus_features)["distance"],
            "target_plus_distance": feature_distance(target_features, plus_features)["distance"]})
        if name == "filter_cutoff":
            sf.write(output / "cutoff_minus.wav", minus_audio, 44100, subtype="FLOAT")
            sf.write(output / "cutoff_plus.wav", plus_audio, 44100, subtype="FLOAT")
        print(f"Diagnostic {name}: S={change/step:.6f}", flush=True)
    # Positive control independent of the chosen target: ENV2 attack must be inactive at zero depth.
    inactive = np.full(13, .5)
    inactive[NAMES.index("filter_env_amount")] = 0.
    a, b, _ = perturbation_pair(inactive, NAMES.index("filter_env_attack"))
    inactive_a, _ = renderer.render(a)
    inactive_b, _ = renderer.render(b)
    inactive_distance = distance(inactive_a, inactive_b)
    if inactive_distance > 1e-8:
        raise ValueError("Zero-depth filter-envelope activity control failed")
    if not np.array_equal(predicted_z, frozen) or sha(run / "validation_predictions.csv") != summary["predictions_sha256"]:
        raise ValueError("Diagnostic stage modified the frozen prediction")
    pd.DataFrame(diagnostic_rows).to_csv(output / "parameter_diagnostics.csv", index=False)
    result = {"sample_id": str(row.sample_id), "selection": selection,
        "model_status": summary["status"], "distance_config": DISTANCE_CONFIG,
        "R": feature_distance(target_features, prediction_features),
        "target_midpoint_distance": distance(target, midpoint),
        "target_true_parameter_roundtrip_distance": distance(target, true_reconstruction),
        "true_roundtrip_max_absolute_sample_error": float(np.max(np.abs(target-true_reconstruction))),
        "repeated_prediction_exact": True, "prediction_unchanged": True,
        "inactive_filter_envelope_attack_distance": inactive_distance,
        "target_samples_sha256": sample_digest(target), "prediction_samples_sha256": sample_digest(prediction),
        "checkpoint_sha256": summary["checkpoint_sha256"],
        "diagnostics_source_sha256": sha(Path(__file__)),
        "predictions_sha256": summary["predictions_sha256"],
        "delta_z": protocol["delta_z"], "tau_z": .05, "test_evaluated": False,
        "q": None, "q_note": "No ensemble/calibrator trained; no confidence probability claimed",
        "perceptual_similarity_threshold": None,
        "audio_peak": {"target": float(np.max(np.abs(target))), "prediction": float(np.max(np.abs(prediction)))}}
    write_json(output / "example.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, default=DEFAULT_PREPARED)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-id", help="Explicit inverse-validation ID, e.g. to compare the same earlier development clip")
    args = parser.parse_args()
    worked_example(args.prepared, args.run, args.output, args.sample_id)
