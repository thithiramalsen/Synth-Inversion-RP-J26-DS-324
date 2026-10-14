"""Set-level metrics for one selected set S of size k and its target.

Pairwise metrics are NaN when k < 2. Relevance-retained (MMR minus top-k) is computed per
target later in ``stats.py``.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

from .param_space import ParamDistance


def dup_rate_key(epsilon: float) -> str:
    return f"dup_rate@{epsilon:g}"


def dup_rate(pair_distances: np.ndarray, epsilon: float) -> float:
    """Fraction of pairs closer than ``epsilon`` in parameter space."""
    return float(np.mean(pair_distances < epsilon)) if len(pair_distances) else float("nan")


def _cosine_pair_distances(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    unit = vectors / np.where(norms == 0, 1.0, norms)
    rows, cols = np.triu_indices(len(vectors), k=1)
    return 1.0 - np.sum(unit[rows] * unit[cols], axis=1)


def set_metrics(
    selected_ids: Sequence[str],
    pool: pd.DataFrame,
    param_vectors: pd.DataFrame,
    distance: ParamDistance,
    epsilon_grid: Sequence[float],
    topk_ids: Sequence[str],
    target_vector: np.ndarray | None = None,
    audio_vectors: pd.DataFrame | None = None,
) -> dict[str, float]:
    """Compute all set-level metrics.

    ``target_vector`` (unit-scale params of an in-dataset target) enables the diagnostic
    target-distance metrics; ``audio_vectors`` (Phase 6+) enables ``mean_pair_audio_dist``
    (cosine distance between feature vectors).
    """
    selected_ids = list(selected_ids)
    k = len(selected_ids)
    by_id = pool.set_index("candidate_id")
    missing = [s for s in selected_ids if s not in by_id.index]
    if missing:
        raise ValueError(f"selected IDs not in pool: {missing}")
    if len(set(selected_ids)) != k:
        raise ValueError("selected set contains duplicates")

    relevance = by_id.loc[selected_ids, "relevance"].to_numpy(dtype=np.float64)
    ranks = by_id.loc[selected_ids, "audio_rank"].to_numpy()
    vectors = param_vectors.loc[selected_ids].to_numpy(dtype=np.float64)
    pairs = distance.pdist(vectors)
    nan = float("nan")

    out: dict[str, float] = {
        "k": k,
        "mean_rel": float(relevance.mean()),
        "min_rel": float(relevance.min()),
        "mean_pair_dist": float(pairs.mean()) if len(pairs) else nan,
        "min_pair_dist": float(pairs.min()) if len(pairs) else nan,
        "max_audio_rank": int(ranks.max()),
        "mean_audio_rank": float(ranks.mean()),
        "overlap_with_topk": len(set(selected_ids) & set(topk_ids)) / k,
    }
    for epsilon in epsilon_grid:
        out[dup_rate_key(epsilon)] = dup_rate(pairs, epsilon)
    if audio_vectors is not None:
        audio_pairs = _cosine_pair_distances(audio_vectors.loc[selected_ids].to_numpy(dtype=np.float64))
        out["mean_pair_audio_dist"] = float(audio_pairs.mean()) if len(audio_pairs) else nan
    if target_vector is not None:
        to_target = distance.cdist(np.asarray(target_vector, dtype=np.float64), vectors)[0]
        out["target_param_dist_min"] = float(to_target.min())
        out["target_param_dist_mean"] = float(to_target.mean())
    return out
