"""Compare two baseline runs on identical inverse-validation IDs and labels."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from c2_estimation.v4.baseline import regression_metrics
from c2_estimation.v4.data import NAMES, sha, write_json


def compare(development: Path, full: Path):
    configs = [json.loads((p / "run_config.json").read_text(encoding="utf-8")) for p in (development, full)]
    if configs[0]["protocol_sha256"] != configs[1]["protocol_sha256"]:
        raise ValueError("Runs use different frozen partitions")
    frames = []
    for path in (development, full):
        summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
        if summary["predictions_sha256"] != sha(path / "validation_predictions.csv"):
            raise ValueError("Delivered predictions changed")
        frame = pd.read_csv(path / "validation_predictions.csv").set_index("sample_id")
        if frame.index.duplicated().any() or not ((frame.split == "validation") & (frame.validation_role == "inverse")).all():
            raise ValueError("Comparison must contain only unique inverse-validation IDs")
        frames.append(frame)
    small, large = frames
    if not small.index.isin(large.index).all():
        raise ValueError("Full run is missing development validation IDs")
    matched = large.loc[small.index]
    truth_columns = [n + "_true_z" for n in NAMES]
    if not np.array_equal(small[truth_columns].to_numpy(), matched[truth_columns].to_numpy()):
        raise ValueError("Matched labels differ")
    predicted_columns = [n + "_predicted_z" for n in NAMES]
    truth = small[truth_columns].to_numpy()
    lower, upper = np.array(configs[0]["lower"]), np.array(configs[0]["upper"])
    first = regression_metrics(small[predicted_columns].to_numpy(), truth, lower, upper)
    second = regression_metrics(matched[predicted_columns].to_numpy(), truth, lower, upper)
    rows = []
    for a, b in zip(first, second, strict=True):
        rows.append({"parameter": a["parameter"], "coordinate": a["coordinate"], "matched_clips": len(truth),
                     "development_mae": a["mae"], "full_mae": b["mae"],
                     "mae_change_full_minus_development": b["mae"] - a["mae"],
                     "development_rmse": a["rmse"], "full_rmse": b["rmse"],
                     "development_r_squared": a["r_squared"], "full_r_squared": b["r_squared"]})
    pd.DataFrame(rows).to_csv(full / "matched_development_comparison.csv", index=False)
    z_rows = [r for r in rows if r["coordinate"] == "research_z"]
    result = {"comparison": "same inverse-validation clips, descriptive development comparison",
              "matched_clips": len(truth), "development_macro_z_mae": float(np.mean([r["development_mae"] for r in z_rows])),
              "full_macro_z_mae": float(np.mean([r["full_mae"] for r in z_rows])),
              "controls_with_lower_mae": sum(r["full_mae"] < r["development_mae"] for r in z_rows),
              "test_evaluated": False}
    write_json(full / "matched_development_comparison.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--full", type=Path, required=True)
    args = parser.parse_args()
    compare(args.development, args.full)
