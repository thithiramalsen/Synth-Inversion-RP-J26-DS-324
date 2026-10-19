"""Statistics over per-target evaluation rows.

Phase 4 scope: paired per-target differences against top-k and seeded bootstrap confidence
intervals for summaries. Hypothesis tests (Wilcoxon, effect sizes, Holm) arrive in Phase 8.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

PAIR_KEYS = ("target_id", "N", "k")


def add_paired_deltas(per_target: pd.DataFrame) -> pd.DataFrame:
    """Add per-target differences against the top-k row with the same (target, N, k).

    * ``rel_loss_vs_topk``  = (topk mean_rel - mean_rel) / topk mean_rel  (relative loss; NaN if topk <= 0)
    * ``delta_mean_pair_dist_vs_topk`` / ``delta_min_pair_dist_vs_topk`` = policy - topk
    """
    base = per_target.loc[per_target["policy"] == "topk", [*PAIR_KEYS, "mean_rel", "mean_pair_dist", "min_pair_dist"]]
    if base.duplicated(list(PAIR_KEYS)).any():
        raise ValueError("more than one top-k row per (target, N, k)")
    base = base.rename(columns={"mean_rel": "_t_rel", "mean_pair_dist": "_t_mean", "min_pair_dist": "_t_min"})
    out = per_target.merge(base, on=list(PAIR_KEYS), how="left", validate="many_to_one")
    if out["_t_rel"].isna().any():
        raise ValueError("some rows have no matching top-k row")
    denominator = out["_t_rel"].where(out["_t_rel"] > 0)
    out["rel_loss_vs_topk"] = (out["_t_rel"] - out["mean_rel"]) / denominator
    out["delta_mean_pair_dist_vs_topk"] = out["mean_pair_dist"] - out["_t_mean"]
    out["delta_min_pair_dist_vs_topk"] = out["min_pair_dist"] - out["_t_min"]
    return out.drop(columns=["_t_rel", "_t_mean", "_t_min"])


def bootstrap_indices(n: int, resamples: int, seed: int) -> np.ndarray:
    """Resampling index matrix ``(resamples, n)``; reused across groups of the same targets."""
    return np.random.default_rng([seed, n]).integers(0, n, size=(resamples, n))


def bootstrap_mean_ci(values: np.ndarray, indices: np.ndarray, alpha: float = 0.05) -> tuple[float, float, float]:
    """Mean and percentile bootstrap CI; NaNs are ignored."""
    values = np.asarray(values, dtype=np.float64)
    if np.all(np.isnan(values)):
        return float("nan"), float("nan"), float("nan")
    with np.errstate(invalid="ignore"):
        means = np.nanmean(values[indices], axis=1)
    low, high = np.nanpercentile(means, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(np.nanmean(values)), float(low), float(high)


def summarize(
    per_target: pd.DataFrame,
    group_cols: Sequence[str],
    metric_cols: Sequence[str],
    resamples: int,
    seed: int,
    alpha: float = 0.05,
) -> pd.DataFrame:
    """Per group: n_targets and, per metric, mean / median / bootstrap CI of the mean.

    Rows inside each group are ordered by target_id so the same seed gives the same CI.
    """
    rows, cache = [], {}
    grouped = per_target.groupby(list(group_cols), dropna=False, sort=True)
    for key, group in grouped:
        group = group.sort_values("target_id", kind="stable")
        n = len(group)
        if n not in cache:
            cache[n] = bootstrap_indices(n, resamples, seed)
        row = dict(zip(group_cols, key if isinstance(key, tuple) else (key,)))
        row["n_targets"] = n
        for metric in metric_cols:
            values = group[metric].to_numpy(dtype=np.float64)
            mean, low, high = bootstrap_mean_ci(values, cache[n], alpha)
            row[f"{metric}_mean"] = mean
            row[f"{metric}_median"] = float(np.nanmedian(values)) if not np.all(np.isnan(values)) else float("nan")
            row[f"{metric}_ci_low"] = low
            row[f"{metric}_ci_high"] = high
        rows.append(row)
    return pd.DataFrame(rows)
