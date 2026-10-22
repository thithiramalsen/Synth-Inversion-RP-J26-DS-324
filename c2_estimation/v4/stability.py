"""Bounded, resumable step-size robustness study; calibration clips only.

Reuses the frozen .02 diagnostic cases. Does not refit a model, choose a step,
change a delivered patch, or evaluate held-out audio.
"""
from __future__ import annotations

import os
for _name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ[_name] = "1"

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import time
import traceback

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from c2_estimation.v4.calibration import load_diagnostics
from c2_estimation.v4.data import DEFAULT_PREPARED, NAMES, ROOT, digest_json, sha, write_json
from c2_estimation.v4.diagnostic_batch import initialize, validate_input, worker
from c2_estimation.v4.diagnostics import DISTANCE_CONFIG

COUNT = 256
STEPS = (.01, .02, .05)
PAIRS = ((.01, .02), (.02, .05), (.01, .05))
DEFAULT_DEVELOPMENT = ROOT / "data/processed/c2_v4/development_uncertainty_v1"


def select_pilot(source, prediction, count=COUNT):
    """Use preassigned rank, never labels, errors, R, S or uncertainty."""
    if count < 1 or len(source) < count or len(prediction) != len(source):
        raise ValueError("Insufficient/mismatched pilot input")
    if not (source.split == "calibration").all() or not (prediction.split == "calibration").all():
        raise ValueError("Pilot must use calibration only")
    if source.sample_id.duplicated().any() or prediction.sample_id.duplicated().any():
        raise ValueError("Duplicate pilot identities")
    if source.sample_id.tolist() != prediction.sample_id.tolist():
        raise ValueError("Prediction/source identity mismatch")
    ordered = prediction.sort_values("diagnostic_rank").head(count)
    if ordered.diagnostic_rank.tolist() != list(range(count)):
        raise ValueError("Expected contiguous preassigned diagnostic ranks")
    selected = source.set_index("sample_id", drop=False).loc[ordered.sample_id]
    return selected.reset_index(drop=True), ordered.reset_index(drop=True)


def checked_case(path, signature, sample_id, expected_sha=None):
    if expected_sha is not None and sha(path) != expected_sha:
        raise ValueError("Reference case hash changed: " + str(path))
    record = json.loads(path.read_text(encoding="utf-8"))
    checksum = record.pop("content_sha256")
    if digest_json(record) != checksum or record["signature"] != signature or record["sample_id"] != sample_id:
        raise ValueError("Invalid saved diagnostic case: " + str(path))
    record["content_sha256"] = checksum
    return record


def check_measurement(record, reference):
    if not record["prediction_unchanged"] or record["sample_id"] != reference["sample_id"]:
        raise ValueError("Delivered prediction identity changed")
    for key in ("target_sha256", "rendered_sha256"):
        if record[key] != reference[key]:
            raise ValueError("Unperturbed waveform changed: " + key)
    if not np.isclose(record["R"], reference["R"], rtol=0, atol=1e-10):
        raise ValueError("Unperturbed residual changed")
    if [r["parameter"] for r in record["sensitivities"]] != list(NAMES):
        raise ValueError("Wrong control order")
    for row in record["sensitivities"]:
        if not np.isfinite([row["S"], row["actual_step_z"]]).all() or row["S"] < 0 or row["actual_step_z"] <= 0:
            raise ValueError("Invalid local sensitivity")


def agreement(first, second):
    first, second = np.asarray(first), np.asarray(second)
    if first.shape != second.shape or first.ndim != 1:
        raise ValueError("Agreement requires paired vectors")
    if not np.isfinite([first, second]).all() or np.any(first < 0) or np.any(second < 0):
        raise ValueError("Sensitivity must be finite and nonnegative")
    defined = len(first) > 1 and np.unique(first).size > 1 and np.unique(second).size > 1
    difference = np.log1p(second) - np.log1p(first)
    return {"count": len(first),
            "spearman": float(spearmanr(first, second).statistic) if defined else None,
            "rank_status": "defined" if defined else "too_few_or_constant",
            "median_abs_log1p_difference": float(np.median(np.abs(difference))) if len(first) else None,
            "p95_abs_log1p_difference": float(np.quantile(np.abs(difference), .95)) if len(first) else None,
            "median_signed_log1p_difference": float(np.median(difference)) if len(first) else None,
            "exact_zero_first": int(np.sum(first == 0)), "exact_zero_second": int(np.sum(second == 0))}


def summarize(long, output):
    rows = []
    figures, axes = plt.subplots(4, 4, figsize=(15, 12), constrained_layout=True)
    for ax in axes.flat[13:]:
        ax.set_visible(False)
    for j, name in enumerate(NAMES):
        part = long[long.parameter == name]
        values = part.pivot(index="sample_id", columns="delta_z", values="S")
        modes = part.pivot(index="sample_id", columns="delta_z", values="mode").loc[values.index]
        if values.isna().any().any() or list(values.columns) != list(STEPS):
            raise ValueError("Incomplete paired step-size measurements")
        interior = (modes == "central").all(axis=1).to_numpy()
        for a, b in PAIRS:
            x, y = values[a].to_numpy(), values[b].to_numpy()
            axes.flat[j].scatter(np.log1p(x), np.log1p(y), s=6, alpha=.5, label=f"{a:g} vs {b:g}")
            for group, mask in (("all", np.ones(len(values), dtype=bool)),
                                ("common_interior", interior), ("boundary_affected", ~interior)):
                rows.append({"parameter": name, "first_delta": a, "second_delta": b, "group": group,
                             **agreement(x[mask], y[mask]),
                             "mode_switch_count": int((modes[a].to_numpy()[mask] != modes[b].to_numpy()[mask]).sum())})
        maximum = float(np.log1p(values.to_numpy()).max())
        axes.flat[j].plot([0, maximum], [0, maximum], "--", color="gray", lw=1)
        axes.flat[j].set(title=name, xlabel="log(1 + S), first step", ylabel="log(1 + S), second step")
    axes.flat[0].legend(fontsize=7)
    figures.suptitle("Step-size magnitude agreement: fixed calibration subset; not a derivative-convergence proof")
    figures.savefig(output / "step_size_magnitude_agreement.png", dpi=150)
    plt.close(figures)
    table = pd.DataFrame(rows)
    table.to_csv(output / "step_size_agreement.csv", index=False)
    figure, panels = plt.subplots(1, 3, figsize=(13, 7), constrained_layout=True)
    for ax, group in zip(panels, ("all", "common_interior", "boundary_affected"), strict=True):
        grid = np.array([[table[(table.parameter == name) & (table.group == group) &
                              (table.first_delta == a) & (table.second_delta == b)].iloc[0].spearman
                          for a, b in PAIRS] for name in NAMES], dtype=float)
        display = ax.imshow(np.ma.masked_invalid(grid), vmin=-1, vmax=1, cmap="coolwarm", aspect="auto")
        ax.set(title=group.replace("_", " "), xticks=range(3),
               xticklabels=[f"{a:g}/{b:g}" for a, b in PAIRS], yticks=range(13), yticklabels=NAMES)
        for i in range(13):
            for k in range(3):
                ax.text(k, i, f"{grid[i,k]:.2f}" if np.isfinite(grid[i,k]) else "n/a", ha="center", va="center", fontsize=8)
    figure.colorbar(display, ax=panels, label="Spearman rank correlation")
    figure.suptitle("Rank agreement across clips, per control; constant/insufficient groups are undefined")
    figure.savefig(output / "step_size_rank_agreement.png", dpi=150)
    plt.close(figure)
    return table


def run(args):
    if not 1 <= args.workers <= 4:
        raise ValueError("Use one to four rendering workers")
    predictions = args.development / "predictions_calibration"
    reference = args.development / "diagnostics_calibration"
    protocol, metadata, source, prediction = validate_input(args.prepared, predictions)
    config, reference_summary, _ = load_diagnostics(reference, "calibration")
    if config["delta_z"] != .02 or config["distance_config"] != DISTANCE_CONFIG:
        raise ValueError("Reference distance/step mismatch")
    for key in ("protocol_sha256", "ensemble_config_sha256", "member_checkpoints"):
        if config[key] != metadata[key]:
            raise ValueError("Reference predictions mismatch: " + key)
    if config["prediction_metadata_sha256"] != sha(predictions / "predictions.json"):
        raise ValueError("Reference belongs to different frozen predictions")
    for path, checksum in config["sources"].items():
        if sha(ROOT / path) != checksum:
            raise ValueError("Frozen renderer source changed: " + path)
    source, prediction = select_pilot(source, prediction)
    source_paths = ("stability", "diagnostic_batch", "diagnostics", "data", "calibration", "predict_subsets")
    settings = {"count": COUNT, "steps": list(STEPS), "workers": args.workers,
                "selection": "first 256 preassigned calibration diagnostic ranks; no error selection",
                "sample_ids": source.sample_id.tolist(), "reference_summary_sha256": sha(reference / "summary.json"),
                "reference_config_sha256": sha(reference / "run_config.json"),
                "predictions_metadata_sha256": sha(predictions / "predictions.json"),
                "sources": {f"c2_estimation/v4/{p}.py": sha(ROOT / f"c2_estimation/v4/{p}.py") for p in source_paths},
                "test_evaluated": False, "prediction_refinement": False, "calibrator_refit": False,
                "default_delta_unchanged": .02, "automatic_pass_threshold": None}
    signature = digest_json(settings)
    path = args.output / "run_config.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8"))["signature"] != signature:
            raise ValueError("Stability configuration changed; use a new output")
    else:
        if args.output.exists() and any(args.output.iterdir()):
            raise ValueError("Nonempty output without matching configuration")
        args.output.mkdir(parents=True, exist_ok=True)
        write_json(path, {"signature": signature, **settings})
    if (args.output / "summary.json").exists():
        saved = json.loads((args.output / "summary.json").read_text(encoding="utf-8"))
        if saved["signature"] != signature or saved["status"] != "complete":
            raise ValueError("Invalid completed study")
        for name, checksum in saved["files"].items():
            if sha(args.output / name) != checksum:
                raise ValueError("Completed study artifact changed: " + name)
        print("Verified completed step-size study; no rendering needed", flush=True)
        return saved
    started = time.perf_counter()
    baseline = {}
    for sample_id in source.sample_id:
        name = sample_id + ".json"
        baseline[sample_id] = checked_case(reference / "cases" / name, config["signature"], sample_id,
                                          reference_summary["case_checksums"][name])
        check_measurement(baseline[sample_id], baseline[sample_id])
    def status(state, delta, completed, **extra):
        write_json(args.output / "status.json", {"status": state, "delta_z": delta,
                   "new_cases_completed": completed, "new_cases_total": 2 * COUNT, "baseline_cases_reused": COUNT,
                   "updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "signature": signature, "test_evaluated": False, **extra})
    measurements = {.02: baseline}
    completed = 0
    try:
        for delta in (.01, .05):
            folder = args.output / f"delta_{delta:g}" / "cases"
            folder.mkdir(parents=True, exist_ok=True)
            records, tasks = {}, []
            for i, (s, p) in enumerate(zip(source.to_dict("records"), prediction.to_dict("records"), strict=True)):
                case_path = folder / (s["sample_id"] + ".json")
                if case_path.exists():
                    record = checked_case(case_path, signature, s["sample_id"])
                    if record["delta_z"] != delta:
                        raise ValueError("Resumed case uses different step")
                    check_measurement(record, baseline[s["sample_id"]])
                    records[s["sample_id"]] = record
                    completed += 1
                else:
                    tasks.append((s, p, delta, i < 4))
            status("running", delta, completed)
            if tasks:
                with ProcessPoolExecutor(max_workers=args.workers, initializer=initialize,
                                         initargs=(protocol["recipe"],)) as executor:
                    for record in executor.map(worker, tasks, chunksize=1):
                        check_measurement(record, baseline[record["sample_id"]])
                        record.update(signature=signature, delta_z=delta)
                        record["content_sha256"] = digest_json(record)
                        write_json(folder / (record["sample_id"] + ".json"), record)
                        records[record["sample_id"]] = record
                        completed += 1
                        status("running", delta, completed)
                        print(f"Step {delta:g}: {len(records)}/{COUNT}; total new cases {completed}/{2*COUNT}; elapsed={time.perf_counter()-started:.1f}s", flush=True)
            if len(records) != COUNT or sum(r["audit"] is not None for r in records.values()) != 4:
                raise ValueError("Missing step-size cases/audits")
            measurements[delta] = records
        rows = []
        for delta in STEPS:
            for sample_id in source.sample_id:
                record = measurements[delta][sample_id]
                rows.extend({"sample_id": sample_id, "delta_z": delta, "R": record["R"], **r} for r in record["sensitivities"])
        long = pd.DataFrame(rows)
        long.to_csv(args.output / "step_size_measurements.csv", index=False)
        table = summarize(long, args.output)
        # Guard against concurrent source/input edits before declaring completion.
        for path, checksum in settings["sources"].items():
            if sha(ROOT / path) != checksum:
                raise ValueError("Study source changed during execution")
        for file, checksum in metadata["files"].items():
            if sha(predictions / file) != checksum:
                raise ValueError("Frozen predictions changed during study")
        lines = ["# Calibration-only perturbation-step robustness", "",
                 "256 fixed calibration clips; 13 controls; steps .01/.02/.05 in research coordinates.",
                 "The .02 results were reused; the other steps were rerendered around exactly the same predictions.",
                 "Four repeat-render/roundtrip/inactivity audits passed at each additional step.", "",
                 "## All-clip agreement by control", "", "| Control | rho .01/.02 | rho .02/.05 | p95 log1p difference .02/.05 |",
                 "|---|---:|---:|---:|"]
        for name in NAMES:
            a = table[(table.parameter == name) & (table.group == "all") & (table.first_delta == .01) & (table.second_delta == .02)].iloc[0]
            b = table[(table.parameter == name) & (table.group == "all") & (table.first_delta == .02) & (table.second_delta == .05)].iloc[0]
            lines.append(f"| {name} | {a.spearman:.4f} | {b.spearman:.4f} | {b.p95_abs_log1p_difference:.4f} |")
        lines.extend(["", "Common-interior and boundary-affected groups, group sizes, zero counts and mode switches are in the CSV.",
                      "Correlation measures rank agreement, not magnitude agreement or identifiability. Undefined rank scores are explicit.",
                      "This is a calibration-subset robustness study, not a formal derivative-convergence or perceptual-equivalence proof.",
                      "No pass threshold was invented after observing results. The default .02, calibrators and delivered patches remain unchanged.",
                      "No inverse training, calibration refit, confidence-threshold tuning or test evaluation was performed.", ""])
        (args.output / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
        files = {str(p.relative_to(args.output)).replace("\\", "/"): sha(p) for p in args.output.rglob("*")
                 if p.is_file() and p.name not in ("status.json", "summary.json") and not p.name.endswith(".tmp")}
        result = {"status": "complete", "signature": signature, "count": COUNT, "steps": list(STEPS),
                  "new_cases": completed, "reused_cases": COUNT, "new_audits": 8, "test_evaluated": False,
                  "predictions_unchanged": True, "default_delta_unchanged": .02, "calibrator_refit": False,
                  "files": files, "elapsed_this_invocation_seconds": time.perf_counter()-started}
        write_json(args.output / "summary.json", result)
        status("complete", None, completed)
        print("Completed bounded step-size study; default method and test set unchanged", flush=True)
        return result
    except BaseException:
        status("failed", None, completed, error=traceback.format_exc())
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, default=DEFAULT_PREPARED)
    parser.add_argument("--development", type=Path, default=DEFAULT_DEVELOPMENT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    run(parser.parse_args())
