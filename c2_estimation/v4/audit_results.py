"""Post-hoc development audit of frozen C2 probabilities; no fitting or test access."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from c2_estimation.v4.calibration import load_diagnostics, labels, probability_metrics, VARIANTS
from c2_estimation.v4.data import NAMES, ROOT, SEED, sha, write_json

DEFAULT_DEVELOPMENT = ROOT / "data/processed/c2_v4/development_uncertainty_v1"


def verify_folder(folder):
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    if not summary["status"].startswith("complete") or summary.get("test_evaluated", True):
        raise ValueError("Expected completed non-test results")
    for name, checksum in summary["files"].items():
        if sha(folder / name) != checksum:
            raise ValueError("Saved artifact changed: " + name)
    return summary


def read_results(development, tau=.05):
    folder = development / f"calibration_tau_{tau:g}"
    summary = verify_folder(folder)
    config, diagnostic_summary, frame = load_diagnostics(development / "diagnostics_reliability-validation", "reliability-validation")
    calibrators = json.loads((folder / "calibrators.json").read_text(encoding="utf-8"))
    if calibrators["validation_summary_sha256"] != sha(development / "diagnostics_reliability-validation/summary.json"):
        raise ValueError("Probabilities and diagnostics are from different runs")
    if calibrators["tau_z"] != tau or summary["validation_count"] != len(frame):
        raise ValueError("Wrong tolerance or cohort size")
    saved = pd.read_parquet(folder / "validation_probabilities.parquet").sort_values("diagnostic_rank").reset_index(drop=True)
    if saved.sample_id.duplicated().any() or saved.sample_id.tolist() != frame.sample_id.tolist():
        raise ValueError("Probability identities do not match diagnostics")
    y = np.column_stack([labels(frame, n, tau)[0] for n in NAMES])
    if not np.array_equal(y, saved[[n + "_correct" for n in NAMES]].to_numpy()):
        raise ValueError("Stored correctness differs from frozen parameter errors")
    probabilities = {v: saved[[n + "_" + v for n in NAMES]].to_numpy(dtype=float) for v in ("g0", *VARIANTS)}
    for variant, q in probabilities.items():
        if not np.isfinite(q).all() or np.any((q < 0) | (q > 1)):
            raise ValueError("Invalid probabilities")
        if not np.isclose(np.square(q-y).mean(), summary["macro_validation_brier"][variant], rtol=0, atol=1e-12):
            raise ValueError("Recomputed Brier differs from saved result")
    return frame, y, probabilities, summary, calibrators


def paired_interval(difference, indices):
    difference = np.asarray(difference, dtype=float)
    if difference.ndim != 1 or not np.isfinite(difference).all() or indices.ndim != 2:
        raise ValueError("Expected finite per-audio paired losses and bootstrap indices")
    draws = difference[indices].mean(axis=1)
    return {"point_difference": float(difference.mean()), "ci95_low": float(np.quantile(draws, .025)),
            "ci95_high": float(np.quantile(draws, .975))}


def comparisons(y, probabilities, replicates=2000):
    if replicates < 1 or y.ndim != 2 or y.shape[1] != 13:
        raise ValueError("Positive bootstrap count and 13-control labels required")
    indices = np.random.default_rng(SEED).integers(0, len(y), size=(replicates, len(y)))
    full_loss = np.square(probabilities["g(U,S,R)"] - y)
    macro, controls = [], []
    for reference in ("g(U)", "g(U,R)"):
        difference = full_loss - np.square(probabilities[reference] - y)
        for group, columns in (("all_13", np.arange(13)), ("excluding_wave_frame_exploratory", np.arange(1, 13))):
            macro.append({"variant": "g(U,S,R)", "reference": reference, "group": group,
                          **paired_interval(difference[:, columns].mean(axis=1), indices),
                          "replicates": replicates, "bootstrap_unit": "whole audio", "seed": SEED})
        for j, name in enumerate(NAMES):
            controls.append({"parameter": name, "variant": "g(U,S,R)", "reference": reference,
                             **paired_interval(difference[:, j], indices), "inference": "exploratory; intervals not multiplicity-adjusted"})
    return pd.DataFrame(macro), pd.DataFrame(controls)


def run(args):
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Audit output must be new; preserve previous evidence")
    frame, y, probabilities, original, _ = read_results(args.development)
    macro, controls = comparisons(y, probabilities, args.bootstrap)
    metrics = []
    for j, name in enumerate(NAMES):
        actual, predicted = frame[name + "_actual_z"].to_numpy(), frame[name + "_predicted_z"].to_numpy()
        error = np.abs(predicted - actual)
        denominator = np.square(actual - actual.mean()).sum()
        for variant, q in probabilities.items():
            values, _, _ = probability_metrics(y[:, j], q[:, j], error)
            metrics.append({"parameter": name, "variant": variant, "mae_z": float(error.mean()),
                            "rmse_z": float(np.sqrt(np.square(error).mean())),
                            "r2_z": float(1-np.square(error).sum()/denominator) if denominator else None,
                            **values})
    metrics = pd.DataFrame(metrics)
    args.output.mkdir(parents=True, exist_ok=True)
    macro.to_csv(args.output / "macro_paired_comparisons.csv", index=False)
    controls.to_csv(args.output / "per_parameter_paired_comparisons.csv", index=False)
    metrics.to_csv(args.output / "per_parameter_audit.csv", index=False)
    # The same score table also supports the local, saved-results viewer.
    scores = pd.DataFrame([{"variant": v, "macro_brier": float(np.square(q-y).mean()),
                           "macro_ece": float(metrics[metrics.variant == v].ece_10_equal_frequency.mean()),
                           "macro_aurc": float(metrics[metrics.variant == v].aurc_discrete.mean())}
                          for v, q in probabilities.items()])
    scores.to_csv(args.output / "macro_scores.csv", index=False)
    figure, axes = plt.subplots(1, 2, figsize=(13, 7), constrained_layout=True)
    for ax, reference in zip(axes, ("g(U)", "g(U,R)"), strict=True):
        part = controls[controls.reference == reference].set_index("parameter").loc[list(NAMES)]
        point = part.point_difference.to_numpy()
        ax.errorbar(point, np.arange(13), xerr=np.vstack((point-part.ci95_low, part.ci95_high-point)),
                    fmt="o", capsize=3, color="#247c74")
        ax.axvline(0, color="gray", linestyle="--")
        ax.set(yticks=range(13), yticklabels=NAMES, title="Full method minus " + reference,
               xlabel="Brier difference (negative favours full method)")
        ax.invert_yaxis()
    figure.suptitle("Paired whole-audio 95% bootstrap intervals; exploratory development evidence")
    figure.savefig(args.output / "per_parameter_brier_differences.png", dpi=150)
    plt.close(figure)
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.8), constrained_layout=True)
    coverages = (.25, .5, .75, 1.)
    coverage_rows = []
    for variant in probabilities:
        part = metrics[metrics.variant == variant]
        risk = [float(part[f"risk_at_coverage_{c:g}"].mean()) for c in coverages]
        mae = [float(part[f"mae_z_at_coverage_{c:g}"].mean()) for c in coverages]
        axes[0].plot(coverages, risk, "o-", label=variant)
        axes[1].plot(coverages, mae, "o-", label=variant)
        coverage_rows.extend({"variant": variant, "coverage": c, "macro_failure_risk": r, "macro_mae_z": e}
                             for c, r, e in zip(coverages, risk, mae, strict=True))
    axes[0].set(xlabel="Retained fraction per parameter", ylabel="Macro failure risk", title="Correctness tolerance = .05")
    axes[1].set(xlabel="Retained fraction per parameter", ylabel="Macro parameter MAE (z)", title="Same coverage, same delivered predictions")
    axes[0].legend(fontsize=8)
    figure.suptitle("Reliability-validation selection performance; not final test")
    figure.savefig(args.output / "matched_coverage_audit.png", dpi=150)
    plt.close(figure)
    pd.DataFrame(coverage_rows).to_csv(args.output / "matched_coverage_audit.csv", index=False)
    primary = macro[(macro.reference == "g(U)") & (macro.group == "all_13")].iloc[0]
    sensitivity = macro[(macro.reference == "g(U,R)") & (macro.group == "all_13")].iloc[0]
    without_wave = macro[(macro.reference == "g(U)") & (macro.group != "all_13")].iloc[0]
    lines = ["# C2 development results audit", "", "No fitting, patch refinement or test evaluation was performed.",
             "512 reliability-validation clips; calibrators were fitted on 2,048 separate calibration clips.",
             "Reliability-validation also selected regularization, so these scores and intervals are descriptive development evidence.", "",
             "## Probability quality", "", "| Variant | Macro Brier |", "|---|---:|"]
    lines.extend(f"| {r.variant} | {r.macro_brier:.6f} |" for r in scores.itertuples())
    lines.extend(["", "Brier measures overall probabilistic quality, not calibration alone. Lower is better.", "",
                  "## Paired comparisons", "", "Differences are full method minus reference; negative favours the full method.", "",
                  f"- Full versus U: {primary.point_difference:.7f}; 95% interval [{primary.ci95_low:.7f}, {primary.ci95_high:.7f}].",
                  f"- Sensitivity beyond U+R: {sensitivity.point_difference:.7f}; 95% interval [{sensitivity.ci95_low:.7f}, {sensitivity.ci95_high:.7f}].",
                  f"- Excluding wave_frame (post-hoc exploration only), full versus U: {without_wave.point_difference:.7f}; interval [{without_wave.ci95_low:.7f}, {without_wave.ci95_high:.7f}].", "",
                  "Intervals resample whole clips, preserving dependence across the 13 controls. They are conditional on the trained models, not training-seed uncertainty.",
                  "Per-control intervals are exploratory and not multiplicity-adjusted. The original 13-control primary endpoint is unchanged.", "",
                  "## Per-control recovery and class counts", "", "| Parameter | MAE z | RMSE z | R2 z | Success / 512 |", "|---|---:|---:|---:|---:|"])
    for r in metrics[metrics.variant == "g(U,S,R)"].itertuples():
        lines.append(f"| {r.parameter} | {r.mae_z:.5f} | {r.rmse_z:.5f} | {r.r2_z:.4f} | {r.success_count} |")
    lines.extend(["", "Rare failures make ranking estimates unstable; inspect class counts before interpreting AUROC/AP.",
                  "The point-error table uses the 512 reliability-validation clips, not the 4,096 inverse-validation cohort.",
                  "The ensemble's inverse-validation MAE (.127991) did not improve over the deterministic baseline (.126112).",
                  "The existing reliability diagrams and raw-uncertainty ranking baseline remain in the source calibration folder.",
                  "Matched-coverage curves average per-control retained subsets; they do not define whole-patch acceptance.", "",
                  "No universal perceptual threshold, Accept/Abstain threshold or final-test claim is established here.", ""])
    (args.output / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
    result = {"status": "complete_development_audit", "test_evaluated": False, "count": len(frame), "tau_z": .05,
              "bootstrap_replicates": args.bootstrap, "macro_brier": original["macro_validation_brier"],
              "comparisons": macro.to_dict("records"), "source_sha256": sha(Path(__file__)),
              "source_calibration_summary_sha256": sha(args.development / "calibration_tau_0.05/summary.json"),
              "files": {p.name: sha(p) for p in args.output.iterdir() if p.is_file()}}
    write_json(args.output / "summary.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development", type=Path, default=DEFAULT_DEVELOPMENT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap", type=int, default=2000)
    run(parser.parse_args())
