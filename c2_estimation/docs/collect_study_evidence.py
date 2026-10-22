"""Print read-only documentation evidence from saved non-test C2 results.

No audio is loaded, rendered or evaluated. No model is trained and no file is
written. The resulting JSON supplies measured tables and exact source excerpts
for the study guide. Run from the repository root with the existing environment.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RUNS = ROOT / "data/processed/c2_v4"
INPUTS = {}


def path(relative):
    target = ROOT / relative
    INPUTS[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
    return target


def read_json(relative):
    return json.loads(path(relative).read_text(encoding="utf-8"))


def read_csv(relative):
    return pd.read_csv(path(relative))


def cell(value):
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "undefined"
    if isinstance(value, (float, np.floating)):
        return f"{value:.6f}"
    return str(value).replace("|", "\\|")


def table(headers, rows):
    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *("| " + " | ".join(cell(v) for v in row) + " |" for row in rows),
    ])


def snippet(relative, name):
    source = path(relative).read_text(encoding="utf-8")
    node = next(n for n in ast.parse(source).body
                if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name)
    lines = source.splitlines()[node.lineno-1:node.end_lineno]
    return {"path": relative, "start": node.lineno, "end": node.end_lineno,
            "text": "\n".join(lines),
            "markdown": f"[{relative}:{node.lineno}]({ROOT.as_posix()}/{relative}:{node.lineno})\n\n```python\n" + "\n".join(lines) + "\n```"}


def main():
    base = "data/processed/c2_v4/"
    protocol = read_json(base + "protocol_v1/protocol.json")
    baseline = read_json(base + "baseline_full_v1/summary.json")
    ensemble = read_json(base + "ensemble_full_v1/summary.json")
    audit = read_json(base + "results_audit_v1/summary.json")
    step = read_json(base + "step_stability_v1/summary.json")
    development = read_json(base + "development_uncertainty_v1/status.json")
    viewer = read_json(base + "viewer_v1/data.json")
    full = read_csv(base + "baseline_full_v1/validation_metrics.csv")
    ens = read_csv(base + "ensemble_full_v1/parameter_metrics.csv")
    metrics = read_csv(base + "results_audit_v1/per_parameter_audit.csv")
    macro = read_csv(base + "results_audit_v1/macro_scores.csv")
    raw = read_csv(base + "development_uncertainty_v1/calibration_tau_0.05/raw_uncertainty_ranking.csv")
    agreement = read_csv(base + "step_stability_v1/step_size_agreement.csv")
    verification = read_json(base + "verification_validation_viewer_v1/verification.json")
    corpus = read_json("data/processed/team_handoff_v4_131072/verification.json")
    names = protocol["parameter_names"]
    for result in (baseline, ensemble, audit, step, development):
        if result.get("test_evaluated") is not False:
            raise ValueError("Expected saved non-test evidence")
    if len(names) != 13 or len(metrics) != 65 or sum(protocol["split_counts"].values()) != 131072:
        raise ValueError("Unexpected evidence dimensions")
    full = full[full.coordinate == "research_z"].set_index("parameter").loc[names]
    ens = ens[ens.coordinate == "research_z"].set_index("parameter").loc[names]
    actual = metrics[metrics.variant == "g(U,S,R)"].set_index("parameter").loc[names]
    variants = ["g0", "g(U)", "g(U,S)", "g(U,R)", "g(U,S,R)"]
    tables = {}
    tables["inverse"] = table(["Parameter", "Single MAE", "Single RMSE", "Single R2", "Ensemble MAE", "Ensemble RMSE", "Ensemble R2"],
        [[n, *[full.loc[n, c] for c in ("mae", "rmse", "r_squared")],
          *[ens.loc[n, c] for c in ("mae", "rmse", "r_squared")]] for n in names])
    tables["macro"] = table(["Model", "Macro Brier", "Macro ECE", "Macro AURC"],
        [[r.variant, r.macro_brier, r.macro_ece, r.macro_aurc] for r in macro.itertuples()])
    tables["recovery512"] = table(["Parameter", "MAE z", "RMSE z", "R2", "Successes / 512", "Failures"],
        [[n, actual.loc[n, "mae_z"], actual.loc[n, "rmse_z"], actual.loc[n, "r2_z"],
          int(actual.loc[n, "success_count"]), int(actual.loc[n, "failure_count"])] for n in names])
    tables["full_reliability"] = table(["Parameter", "Brier", "ECE", "Failure AUROC", "Failure AP", "AURC"],
        [[n, *[actual.loc[n, c] for c in ("brier", "ece_10_equal_frequency", "failure_auroc", "failure_average_precision", "aurc_discrete")]] for n in names])
    pivot = metrics.pivot(index="parameter", columns="variant", values="brier")
    tables["all_brier"] = table(["Parameter", *variants], [[n, *[pivot.loc[n, v] for v in variants]] for n in names])
    raw = raw.set_index("parameter").loc[names]
    tables["raw_ranking"] = table(["Parameter", "Failure AUROC", "Failure AP", "AURC"],
        [[n, *[raw.loc[n, c] for c in ("failure_auroc", "failure_average_precision", "aurc_discrete")]] for n in names])
    u = metrics[metrics.variant == "g(U)"].set_index("parameter").loc[names]
    tables["coverage50"] = table(["Parameter", "Raw-U risk", "U risk", "U+S+R risk", "Raw-U MAE", "U MAE", "U+S+R MAE"],
        [[n, *[d.loc[n, "risk_at_coverage_0.5"] for d in (raw, u, actual)],
          *[d.loc[n, "mae_z_at_coverage_0.5"] for d in (raw, u, actual)]] for n in names])
    tolerance_rows = []
    for tolerance in ("0.025", "0.05", "0.1"):
        summary = read_json(base + f"development_uncertainty_v1/calibration_tau_{tolerance}/summary.json")
        tolerance_rows.append([float(tolerance), *[summary["macro_validation_brier"][v] for v in variants]])
    tables["tolerances"] = table(["Tolerance z", *variants], tolerance_rows)
    tables["steps"] = table(["Parameter", "rho .01/.02", "rho .02/.05", "p95 abs log1p difference .02/.05"],
        [[n,
          agreement[(agreement.parameter == n) & (agreement.group == "all") & (agreement.first_delta == .01) & (agreement.second_delta == .02)].iloc[0].spearman,
          agreement[(agreement.parameter == n) & (agreement.group == "all") & (agreement.first_delta == .02) & (agreement.second_delta == .05)].iloc[0].spearman,
          agreement[(agreement.parameter == n) & (agreement.group == "all") & (agreement.first_delta == .02) & (agreement.second_delta == .05)].iloc[0].p95_abs_log1p_difference] for n in names])
    example = viewer["examples"][0]
    tables["example_parameters"] = table(["Parameter", "Original z", "Predicted z", "Abs error", "Correct at .05?"],
        [[p["name"], p["actual_z"], p["predicted_z"], p["error_z"], "yes" if p["correct"] else "no"] for p in example["parameters"]])
    tables["example_diagnostics"] = table(["Parameter", "U in z squared", "S", "q: U only", "q: U+S+R"],
        [[p["name"], p["U"], p["S"], p["q"]["g(U)"], p["q"]["g(U,S,R)"]] for p in example["parameters"]])
    reconstruction = []
    for partition in ("calibration", "reliability-validation"):
        relative = base + f"development_uncertainty_v1/diagnostics_{partition}/diagnostics.parquet"
        frame = pd.read_parquet(path(relative), columns=["R", "split"])
        if (frame.split == "test").any():
            raise ValueError("Unexpected test diagnostic")
        values = frame.R.to_numpy()
        reconstruction.append([partition, len(values), values.mean(), np.median(values), np.quantile(values,.9), values.min(), values.max()])
    tables["reconstruction"] = table(["Partition", "Clips", "Mean R", "Median R", "90th percentile R", "Min R", "Max R"], reconstruction)
    excerpts = {}
    targets = {
        "sobol": ("generation/scripts/05_generate_pilot_dataset.py", "create_sobol_samples"),
        "set_labels": ("generation/scripts/05_generate_pilot_dataset.py", "apply_sampled_parameters"),
        "dc": ("generation/audio_processing.py", "dc_filter"),
        "audio_loader": ("generation/corpus_audio.py", "load_audio"),
        "coordinates": ("c2_estimation/v4/data.py", "to_z"),
        "split": ("c2_estimation/v4/data.py", "assignments"),
        "mel": ("c2_estimation/pipeline.py", "extract_log_mel"),
        "normalization": ("c2_estimation/v4/features.py", "training_statistics"),
        "cnn": ("c2_estimation/pipeline.py", "ParameterCNN"),
        "gaussian": ("c2_estimation/v4/ensemble.py", "GaussianCNN"),
        "nll": ("c2_estimation/v4/ensemble.py", "gaussian_nll"),
        "combine": ("c2_estimation/v4/ensemble.py", "combine"),
        "select": ("c2_estimation/v4/predict_subsets.py", "select"),
        "perturb": ("c2_estimation/v4/diagnostics.py", "perturbation_pair"),
        "distance": ("c2_estimation/v4/diagnostics.py", "feature_distance"),
        "labels": ("c2_estimation/v4/calibration.py", "labels"),
        "logistic": ("c2_estimation/v4/calibration.py", "fit"),
        "probability": ("c2_estimation/v4/calibration.py", "probability_metrics"),
        "bootstrap": ("c2_estimation/v4/calibration.py", "paired_brier_bootstrap"),
    }
    for key, (relative, name) in targets.items():
        excerpts[key] = snippet(relative, name)
    # Counts are obtained from the actual architecture, without checkpoint loading.
    from c2_estimation.v4.baseline import build_model
    from c2_estimation.v4.ensemble import GaussianCNN
    import torch
    parameter_counts = {"single_cnn": sum(p.numel() for p in build_model(torch.device("cpu")).parameters()),
                        "gaussian_member": sum(p.numel() for p in GaussianCNN(torch.device("cpu")).parameters())}
    print(json.dumps({"tables": tables, "snippets": excerpts, "example": example,
                      "baseline": baseline, "ensemble": ensemble, "audit": audit,
                      "development": development, "corpus": corpus, "verification": verification,
                      "parameter_counts": parameter_counts, "inputs_sha256": INPUTS}, allow_nan=False))


if __name__ == "__main__":
    main()
