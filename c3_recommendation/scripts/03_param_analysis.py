"""Phase 3 - parameter-space structure of the bank; proposes the near-duplicate epsilon grid.

For a seeded sample of bank IDs: distances to the 1st/5th/10th nearest bank neighbours,
a random-pair baseline, a leave-one-parameter-out 1-NN check, and candidate epsilon
values. Writes to ``<outputs_dir>/analysis/`` and the grid into the config
(``near_duplicate.epsilon_grid``). Epsilon is FINALISED on validation data in Phase 7.

Usage (repo root):
    python c3_recommendation/scripts/03_param_analysis.py [--n-queries 2000] [--no-write-config]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from c3.analysis import knn_distances, leave_one_out_nn1, propose_epsilon_grid, random_pair_distances  # noqa: E402
from c3.config import load_config  # noqa: E402
from c3.data_sources import make_source  # noqa: E402
from c3.param_space import ParamDistance  # noqa: E402
from c3.splits import BANK, load_manifest  # noqa: E402

PERCENTILES = (1, 5, 10, 25, 50, 75, 90, 95, 99)
EPSILON_PERCENTILES = (1, 5, 10, 25)
ROUND_EPSILONS = (0.05, 0.10, 0.15)
K_MAX = 10


def describe(values: np.ndarray) -> dict:
    return {"n": int(len(values)), "mean": float(values.mean()), "std": float(values.std(ddof=1)),
            "min": float(values.min()), "max": float(values.max()),
            **{f"p{p}": float(np.percentile(values, p)) for p in PERCENTILES}}


def write_epsilon_grid(config_path: Path, grid: list[float]) -> None:
    text = config_path.read_text(encoding="utf-8")
    pattern = re.compile(r"^(\s*)epsilon_grid:.*$", re.MULTILINE)
    if len(pattern.findall(text)) != 1:
        raise SystemExit("could not find exactly one epsilon_grid line in the config")
    values = ", ".join(f"{v:g}" for v in grid)
    line = rf"\g<1>epsilon_grid: [{values}]   # proposed in Phase 3 (D-011); finalised on validation in Phase 7"
    config_path.write_text(pattern.sub(line, text), encoding="utf-8")


def save_plots(out_dir: Path, nn: np.ndarray, random_pairs: np.ndarray, grid: list[float]) -> list[str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed - plots skipped (pip install matplotlib, then re-run).")
        return []

    def histogram(values, title, xlabel, path, lines=()):
        fig, ax = plt.subplots(figsize=(7, 3.6), dpi=150)
        counts, _, _ = ax.hist(values, bins=60, color="#5a5a5a", edgecolor="white", linewidth=0.6)
        if lines:
            ax.set_ylim(0, counts.max() * 1.45)  # headroom so epsilon labels never sit on bars
        for eps in lines:
            ax.axvline(eps, color="#1a1a1a", linewidth=1, linestyle=(0, (3, 2)))
            ax.annotate(f"{eps:g}", (eps, 1), xycoords=("data", "axes fraction"), xytext=(2, -2),
                        textcoords="offset points", rotation=90, va="top", fontsize=7, color="#333333")
        ax.set_title(title, fontsize=10, loc="left")
        ax.set_xlabel(xlabel, fontsize=9)
        ax.set_ylabel("count", fontsize=9)
        ax.tick_params(labelsize=8, colors="#444444")
        ax.grid(axis="y", color="#e6e6e6", linewidth=0.6)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)
        return path.name

    return [
        histogram(nn[:, 0], f"Bank 1-NN parameter distance (n={len(nn)}), dashed = epsilon candidates",
                  "euclid_sqrt_d distance (unit scale)", out_dir / "nn1_hist.png", grid),
        histogram(random_pairs, f"Random bank pair parameter distance (n={len(random_pairs)})",
                  "euclid_sqrt_d distance (unit scale)", out_dir / "random_pair_hist.png"),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None)
    parser.add_argument("--n-queries", type=int, default=2000)
    parser.add_argument("--n-random-pairs", type=int, default=2000)
    parser.add_argument("--no-write-config", action="store_true")
    args = parser.parse_args()
    started = time.time()

    cfg = load_config(args.config)
    out_dir = cfg.path("outputs_dir") / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)
    source = make_source(cfg)
    unit = source.params_unit()
    manifest = load_manifest(cfg.path("outputs_dir") / "splits")
    bank_ids = manifest.loc[manifest["split"] == BANK, "sample_id"]
    bank = unit.loc[bank_ids]
    bank_values = bank.to_numpy(np.float64)
    metric = ParamDistance.from_schema(source.schema, method=cfg["param_distance.method"],
                                       weights=cfg.get("param_distance.weights"))

    rng = np.random.default_rng(cfg.seed)
    query_pos = np.sort(rng.choice(len(bank), size=args.n_queries, replace=False))
    query_values = bank_values[query_pos]

    nn = knn_distances(query_values, bank_values, metric, K_MAX, query_pos)
    random_pairs = random_pair_distances(bank_values, args.n_random_pairs, metric, rng)
    grid_entries = propose_epsilon_grid(nn[:, 0], EPSILON_PERCENTILES, ROUND_EPSILONS)
    for entry in grid_entries:
        entry["share_of_random_pairs_below"] = float(np.mean(random_pairs < entry["epsilon"]))
        entry["share_of_nn5_below"] = float(np.mean(nn[:, 4] < entry["epsilon"]))
    grid = [entry["epsilon"] for entry in grid_entries]
    loo = pd.DataFrame(leave_one_out_nn1(query_values, bank_values, source.schema.names, query_pos))

    pd.DataFrame({"sample_id": bank.index[query_pos], "nn1": nn[:, 0], "nn5": nn[:, 4], "nn10": nn[:, 9]}) \
        .to_csv(out_dir / "nn_distances.csv", index=False, float_format="%.6f")
    pd.DataFrame({"distance": random_pairs}).to_csv(out_dir / "random_pair_distances.csv", index=False,
                                                     float_format="%.6f")
    loo.to_csv(out_dir / "leave_one_out_nn1.csv", index=False, float_format="%.6f")
    plots = save_plots(out_dir, nn, random_pairs, grid)

    result = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "data_source": cfg["data.source"], "seed": cfg.seed, "distance": metric.describe(),
        "bank_size": int(len(bank)), "n_queries": int(args.n_queries), "n_random_pairs": int(args.n_random_pairs),
        "nn1": describe(nn[:, 0]), "nn5": describe(nn[:, 4]), "nn10": describe(nn[:, 9]),
        "random_pairs": describe(random_pairs),
        "epsilon_candidates": grid_entries,
        "leave_one_out_nn1": loo.to_dict(orient="records"),
        "plots": plots,
        "note": "Epsilon is finalised on validation data in Phase 7; this grid is a proposal only.",
        "runtime_seconds": round(time.time() - started, 1),
    }
    (out_dir / "param_structure.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    if not args.no_write_config:
        write_epsilon_grid(cfg.source_path, grid)

    print(f"Bank {len(bank)}  queries {args.n_queries}  random pairs {args.n_random_pairs}  "
          f"metric {metric.method}  ({result['runtime_seconds']} s)")
    for key in ("nn1", "nn5", "nn10", "random_pairs"):
        d = result[key]
        print(f"  {key:12s} p1={d['p1']:.4f} p5={d['p5']:.4f} p25={d['p25']:.4f} "
              f"median={d['p50']:.4f} p95={d['p95']:.4f} mean={d['mean']:.4f}")
    print("Epsilon candidates (share of 1-NN / 5-NN / random pairs below):")
    for e in grid_entries:
        print(f"  {e['epsilon']:<7g} {e['share_of_nn1_below']:6.3f} {e['share_of_nn5_below']:6.3f} "
              f"{e['share_of_random_pairs_below']:6.3f}   {e['source']}")
    print("Leave-one-out median 1-NN (change vs all 13):")
    for row in loo.itertuples():
        label = row.dropped if isinstance(row.dropped, str) else "(none - all 13)"
        print(f"  {label:20s} {row.median_nn1:.4f}  ({row.median_change_vs_full:+.4f})")
    print(f"Config epsilon_grid {'NOT written' if args.no_write_config else 'written'}: {grid}")
    print("NOTE: epsilon is FINALISED on validation data in Phase 7; Phase 3 only proposes the grid.")


if __name__ == "__main__":
    main()
