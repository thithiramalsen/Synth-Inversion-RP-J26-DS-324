"""Phase 7 selection rules, applied to validation results only (rules fixed in D-017).

* Operating point: among MMR rows for the primary k, a (N, lambda) is eligible when the upper
  95% bootstrap CI of the per-target relative relevance loss is <= tau. Choose the eligible row
  with the highest mean pairwise parameter distance; ties go to the smaller N, then larger lambda.
  If no lambda < 1 is eligible the result is "no diversity gain within tolerance".
* Near-duplicate threshold: the smallest epsilon at which at least 10% of validation targets have
  a near-duplicate pair in their plain top-k set (depends on top-k only, never on the MMR effect).
  If no epsilon qualifies, the largest epsilon is used and dup_rate is flagged as uninformative.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

from .metrics import dup_rate_key
from .stats import bootstrap_indices, bootstrap_mean_ci

EPSILON_MIN_TOPK_SHARE = 0.10


def select_operating_point(summary: pd.DataFrame, tau: float, k: int) -> dict:
    """Apply the lambda/N rule to a ``stats.summarize`` table grouped by policy, lam, N, k."""
    rows = summary[(summary["policy"] == "mmr") & (summary["k"] == k)].copy()
    if rows.empty:
        raise ValueError(f"no MMR rows for k={k}")
    rows["eligible"] = rows["rel_loss_vs_topk_ci_high"] <= tau
    candidates = rows[rows["eligible"]].sort_values(
        ["mean_pair_dist_mean", "N", "lam"], ascending=[False, True, False], kind="stable")
    table = rows[["N", "lam", "mean_rel_mean", "rel_loss_vs_topk_mean", "rel_loss_vs_topk_ci_high",
                  "mean_pair_dist_mean", "min_pair_dist_mean", "eligible"]].sort_values(["N", "lam"], ascending=[True, False])
    if candidates.empty:
        raise ValueError("lambda = 1 should always be eligible (zero loss); check the summary")
    best = candidates.iloc[0]
    diversity_gain = bool(best["lam"] < 1.0)
    return {
        "k": int(k), "tau": float(tau),
        "chosen": {"N": int(best["N"]), "lam": float(best["lam"]),
                   "mean_pair_dist": float(best["mean_pair_dist_mean"]),
                   "rel_loss_mean": float(best["rel_loss_vs_topk_mean"]),
                   "rel_loss_ci_high": float(best["rel_loss_vs_topk_ci_high"])},
        "outcome": "diversity gain within tolerance" if diversity_gain else "no diversity gain within tolerance",
        "per_N_best": {int(n): float(g.sort_values(["mean_pair_dist_mean", "lam"], ascending=[False, False]).iloc[0]["lam"])
                       for n, g in candidates.groupby("N")},
        "table": table.to_dict(orient="records"),
    }


def epsilon_sensitivity(per_target: pd.DataFrame, N: int, k: int, lam: float, epsilon_grid: Sequence[float],
                        resamples: int, seed: int, alpha: float = 0.05) -> pd.DataFrame:
    """Top-k vs MMR near-duplicate rates for every epsilon, paired by target, with bootstrap CIs."""
    base = per_target[(per_target["N"] == N) & (per_target["k"] == k)]
    top = base[base["policy"] == "topk"].set_index("target_id").sort_index()
    mmr = base[(base["policy"] == "mmr") & np.isclose(base["lam"], lam)].set_index("target_id").sort_index()
    if not top.index.equals(mmr.index) or top.empty:
        raise ValueError("top-k and MMR rows do not pair by target")
    idx = bootstrap_indices(len(top), resamples, seed)
    rows = []
    for eps in epsilon_grid:
        key = dup_rate_key(eps)
        diff = mmr[key].to_numpy() - top[key].to_numpy()
        mean, low, high = bootstrap_mean_ci(diff, idx, alpha)
        rows.append({"epsilon": float(eps), "topk_dup_rate_mean": float(top[key].mean()),
                     "mmr_dup_rate_mean": float(mmr[key].mean()), "mmr_minus_topk_mean": mean,
                     "ci_low": low, "ci_high": high,
                     "share_targets_topk_has_near_duplicate": float((top[key] > 0).mean()),
                     "share_targets_topk_already_diverse": float((top[key] == 0).mean())})
    return pd.DataFrame(rows)


def choose_epsilon(sensitivity: pd.DataFrame, min_share: float = EPSILON_MIN_TOPK_SHARE) -> dict:
    """Smallest epsilon where >= ``min_share`` of targets have a near-duplicate in top-k."""
    ordered = sensitivity.sort_values("epsilon")
    qualifying = ordered[ordered["share_targets_topk_has_near_duplicate"] >= min_share]
    if qualifying.empty:
        return {"epsilon": float(ordered["epsilon"].max()), "informative": False,
                "rule": f"no epsilon has >= {min_share:.0%} of targets with a top-k near-duplicate; largest used"}
    return {"epsilon": float(qualifying["epsilon"].iloc[0]), "informative": True,
            "rule": f"smallest epsilon with >= {min_share:.0%} of targets having a top-k near-duplicate"}
