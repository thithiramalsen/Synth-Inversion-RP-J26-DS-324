"""Real development-only checks for live inference, diagnostics and preset roundtrips."""
import argparse
from pathlib import Path
import time

import numpy as np
import pandas as pd

from .engine import (
    DEFAULT_CALIBRATION, DEFAULT_OUTPUT, DEFAULT_PREPARED, Engine, NAMES,
    load_prepared, read_json, sha, write_json,
)
from c2_estimation.v4.diagnostic_batch import measure


def verify(output, device="auto"):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    engine = Engine(device=device)
    _, manifest = load_prepared(DEFAULT_PREPARED)
    saved = pd.read_parquet(DEFAULT_CALIBRATION.parent / "predictions_reliability-validation/predictions.parquet")
    records = []
    for key, example in engine.examples.items():
        payload, filename = engine.example_bytes(key)
        folder = output / ("example_" + key)
        result = engine.run(payload, filename, folder,
                            progress=lambda *args: print(key, *args, flush=True), example_id=key)
        target, _ = engine.prepare(payload)
        repeated = engine.estimate(target)
        z = np.array([p["predicted_z"] for p in result["parameters"]])
        u = np.array([p["U"] for p in result["parameters"]])
        if not np.array_equal(z, repeated[0]) or not np.array_equal(u, repeated[3]):
            raise AssertionError("Repeated live inference changed")
        reference = saved[saved.sample_id == example["sample_id"]].iloc[0]
        reference_z = reference[[n + "_predicted_z" for n in NAMES]].to_numpy(dtype=float)
        reference_u = reference[[n + "_total_variance_z" for n in NAMES]].to_numpy(dtype=float)
        # Historical inference used a larger batch; CUDA/CPU accumulation can differ.
        np.testing.assert_allclose(z, reference_z, rtol=0, atol=1e-6)
        np.testing.assert_allclose(u, reference_u, rtol=0, atol=1e-6)
        source = manifest[manifest.sample_id == example["sample_id"]].iloc[0].to_dict()
        if source["split"] != "validation" or source["validation_role"] != "reliability":
            raise AssertionError("Non-development example")
        current_prediction = {n + "_predicted_z": z[j] for j, n in enumerate(NAMES)}
        # Compare the new single-clip orchestration with the unchanged research
        # diagnostic implementation using the same newly delivered estimate.
        baseline = measure(source, current_prediction, engine.renderer, audit=True)
        np.testing.assert_allclose(result["R"], baseline["R"], rtol=0, atol=1e-10)
        np.testing.assert_allclose(
            [p["S"] for p in result["parameters"]],
            [p["S"] for p in baseline["sensitivities"]], rtol=0, atol=1e-10)
        if result["input"]["conditioned_samples_sha256"] != baseline["target_sha256"]:
            raise AssertionError("Conditioning differs")
        if result["reconstruction_samples_sha256"] != baseline["rendered_sha256"]:
            raise AssertionError("Reconstruction differs")
        for variant in ("g(U)", "g(U,S)", "g(U,R)", "g(U,S,R)"):
            for p in result["parameters"]:
                model = engine.calibrators["models"][p["name"]][variant]
                raw_values = {"U": p["U"], "S": p["S"], "R": result["R"]}
                x = np.array([np.log(max(raw_values[c], 1e-12)) if c == "U"
                              else np.log1p(raw_values[c]) for c in model["features"]])
                if model["constant_probability"] is None:
                    logit = ((x - model["mean"]) / model["std"]) @ model["weights"] + model["intercept"]
                    q = 1 / (1 + np.exp(-logit))
                else:
                    q = model["constant_probability"]
                np.testing.assert_allclose(p["q"][variant], q, rtol=0, atol=1e-12)
        records.append({
            "sample_id": example["sample_id"], "diagnostic_rank": example["diagnostic_rank"],
            "elapsed_seconds": result["elapsed_seconds"], "R": result["R"],
            "max_z_difference_from_saved_batch": float(np.max(np.abs(z - reference_z))),
            "max_U_difference_from_saved_batch": float(np.max(np.abs(u - reference_u))),
            "repeat_inference_exact": True, "research_diagnostics_match": True,
            "calibrator_math_matches": True, "renderer_audit": baseline["audit"],
            "export_audit": result["export_audit"], "result_sha256": sha(folder / "result.json"),
        })
        print("VERIFIED", example["sample_id"], flush=True)
    summary = {
        "status": "passed", "device": str(engine.device), "cases": records,
        "selection": "first three preassigned reliability-validation ranks, independent of outcomes",
        "tolerances": {"historical_prediction_absolute": 1e-6, "same_estimate_R_S_absolute": 1e-10,
                       "calibrator_math_absolute": 1e-12},
        "test_evaluated": False, "human_study_performed": False,
        "desktop_vital_checked": False, "provenance": engine.provenance,
    }
    write_json(output / "verification.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New verification output directory")
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    args = parser.parse_args()
    verify(args.output, args.device)
