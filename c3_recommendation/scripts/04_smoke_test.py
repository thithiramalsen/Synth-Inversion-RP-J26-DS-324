"""Phase 4 - end-to-end smoke test with the PARAMETER PROXY relevance.

SMOKE TEST ONLY. ParamProxyRelevance is not an audio relevance measure; nothing written here
may appear in the thesis as a finding. It proves split -> pool -> policies -> metrics -> stats
-> reports runs correctly and deterministically before audio features exist.

Writes to ``<outputs_dir>/smoke/`` (tables carry relevance_function = SMOKE_TEST_PROXY,
run_config.json carries relevance = SMOKE_TEST_PROXY):
  run_config.json, per_target.parquet, recommendations.parquet, summary.csv, lambda_sweep.csv

Checks: lambda = 1 equals top-k, no self-matches, candidates only from the bank, an in-process
re-run gives identical frames, and artefact bytes equal the previous run's (if one exists).

Usage (repo root):
    python c3_recommendation/scripts/04_smoke_test.py [--n-targets 200]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from c3.config import REPO_ROOT, load_config  # noqa: E402
from c3.data_sources import make_source  # noqa: E402
from c3.evaluate import MMR, EvalSpec, evaluate  # noqa: E402
from c3.metrics import dup_rate_key  # noqa: E402
from c3.param_space import ParamDistance  # noqa: E402
from c3.relevance import ParamProxyRelevance  # noqa: E402
from c3.splits import BANK, VAL, Splits, load_manifest  # noqa: E402
from c3.stats import add_paired_deltas, summarize  # noqa: E402

LABEL = "SMOKE_TEST_PROXY"
GROUP_COLS = ["policy", "lam", "N", "k"]
ARTEFACTS = ("per_target.parquet", "recommendations.parquet", "summary.csv", "lambda_sweep.csv")
PACKAGES = ("numpy", "pandas", "pyarrow", "scipy", "pyyaml", "soundfile", "matplotlib")


def git_state() -> dict:
    def run(*args):
        return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
    try:
        return {"commit": run("rev-parse", "HEAD"),
                "c3_uncommitted_changes": bool(run("status", "--porcelain", "--", "c3_recommendation"))}
    except OSError:
        return {"commit": None, "c3_uncommitted_changes": None}


def package_versions() -> dict:
    out = {"python": platform.python_version()}
    for name in PACKAGES:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = None
    return out


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None)
    parser.add_argument("--n-targets", type=int, default=200)
    args = parser.parse_args()
    started = time.time()

    cfg = load_config(args.config)
    out_dir = cfg.path("outputs_dir") / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    source = make_source(cfg)
    unit = source.params_unit()
    splits = Splits.from_config(cfg, load_manifest(cfg.path("outputs_dir") / "splits"))
    bank_ids = splits.ids(BANK)
    targets = splits.get_targets(VAL, args.n_targets, cfg.seed)
    distance = ParamDistance.from_schema(source.schema, method=cfg["param_distance.method"],
                                         weights=cfg.get("param_distance.weights"))
    spec = EvalSpec.from_config(cfg)

    def run():
        relevance = ParamProxyRelevance(unit, seed=cfg.seed)
        return relevance, evaluate(relevance, targets, bank_ids, unit, distance, spec)

    relevance, result = run()
    _, again = run()
    same_frames = result.per_target.equals(again.per_target) and result.recommendations.equals(again.recommendations)

    per_target = add_paired_deltas(result.per_target)
    recs = result.recommendations
    bank_set = set(bank_ids)
    checks = {
        "lambda_one_equals_topk": result.lambda_one_mismatches == 0,
        "lambda_one_mismatches": result.lambda_one_mismatches,
        "self_matches": int((recs["candidate_id"] == recs["target_id"]).sum()),
        "candidates_outside_bank": int((~recs["candidate_id"].isin(bank_set)).sum()),
        "targets_in_bank": int(sum(t in bank_set for t in targets)),
        "in_process_rerun_identical": bool(same_frames),
    }

    metric_cols = ["mean_rel", "min_rel", "mean_pair_dist", "min_pair_dist",
                   *[dup_rate_key(e) for e in spec.epsilon_grid], "max_audio_rank", "mean_audio_rank",
                   "overlap_with_topk", "target_param_dist_min", "target_param_dist_mean",
                   "rel_loss_vs_topk", "delta_mean_pair_dist_vs_topk", "delta_min_pair_dist_vs_topk"]
    summary = summarize(per_target, GROUP_COLS, metric_cols, int(cfg["stats.bootstrap_resamples"]), cfg.seed,
                        float(cfg["stats.alpha"]))
    sweep_cols = [c for c in summary.columns
                  if c in GROUP_COLS or c == "n_targets"
                  or any(c.startswith(m) for m in ("mean_rel_", "mean_pair_dist_", "min_pair_dist_",
                                                   "rel_loss_vs_topk_", "dup_rate@"))]
    sweep = summary[sweep_cols].sort_values(["N", "k", "policy", "lam"], ascending=[True, True, True, False],
                                            na_position="first")

    previous = {}
    hashes_path = out_dir / "artefact_hashes.json"
    if hashes_path.exists():
        previous = json.loads(hashes_path.read_text(encoding="utf-8"))
    for frame in (per_target, recs, summary, sweep):
        frame.insert(0, "relevance_function", LABEL)
    per_target.to_parquet(out_dir / "per_target.parquet", index=False)
    recs.to_parquet(out_dir / "recommendations.parquet", index=False)
    summary.to_csv(out_dir / "summary.csv", index=False, float_format="%.10g")
    sweep.to_csv(out_dir / "lambda_sweep.csv", index=False, float_format="%.10g")
    hashes = {name: sha256(out_dir / name) for name in ARTEFACTS}
    checks["artefacts_identical_to_previous_run"] = (hashes == previous) if previous else "no previous run"
    hashes_path.write_text(json.dumps(hashes, indent=2), encoding="utf-8")

    run_config = {
        "relevance": LABEL,
        "warning": "SMOKE TEST ONLY - parameter proxy relevance; never report these numbers as findings.",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "config": cfg.as_dict(),
        "git": git_state(),
        "packages": package_versions(),
        "data_source": cfg["data.source"],
        "relevance_function": relevance.describe(),
        "distance": distance.describe(),
        "eval_spec": {k: (list(v) if isinstance(v, tuple) else v) for k, v in spec.__dict__.items()},
        "n_targets": len(targets), "target_split": VAL, "bank_size": len(bank_ids),
        "seconds_per_target": round(result.seconds_per_target, 4),
        "total_runtime_seconds": round(time.time() - started, 1),
        "checks": checks,
        "artefact_sha256": hashes,
    }
    (out_dir / "run_config.json").write_text(json.dumps(run_config, indent=2, default=str), encoding="utf-8")

    print(f"*** {LABEL}: pipeline check only - not results ***")
    print(f"Targets {len(targets)} (val)  bank {len(bank_ids)}  proxy columns {relevance.subset_columns}")
    print(f"Per target {result.seconds_per_target * 1000:.1f} ms   total {run_config['total_runtime_seconds']} s")
    for name, value in checks.items():
        print(f"  check {name}: {value}")
    view = sweep[(sweep["N"] == max(spec.pool_sizes)) & (sweep["k"] == max(spec.k_values))]
    print(f"Trade-off at N={max(spec.pool_sizes)}, k={max(spec.k_values)} (means over targets):")
    print(f"  {'policy':7s} {'lam':>5s} {'mean_rel':>9s} {'rel_loss':>9s} {'mean_pair':>10s} {'min_pair':>9s}")
    for r in view.itertuples(index=False):
        d = r._asdict()
        lam = "" if pd.isna(d["lam"]) else f"{d['lam']:.2f}"
        print(f"  {d['policy']:7s} {lam:>5s} {d['mean_rel_mean']:9.4f} {d['rel_loss_vs_topk_mean']:9.4f} "
              f"{d['mean_pair_dist_mean']:10.4f} {d['min_pair_dist_mean']:9.4f}")
    print(f"Saved to {out_dir}: run_config.json, {', '.join(ARTEFACTS)}")
    failed = [k for k in ("lambda_one_equals_topk", "in_process_rerun_identical") if not checks[k]] + \
             [k for k in ("self_matches", "candidates_outside_bank", "targets_in_bank") if checks[k]]
    if failed:
        raise SystemExit(f"SMOKE TEST FAILED checks: {failed}")


if __name__ == "__main__":
    main()
