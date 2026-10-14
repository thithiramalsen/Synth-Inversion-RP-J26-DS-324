"""Set-level metrics for one selected set S of size k and its target.

Pairwise metrics are NaN when k < 2. Relevance-retained (MMR minus top-k) is computed per
target later in ``stats.py``.

:class:`PoolArrays` holds one pool's arrays (relevance, ranks, pairwise parameter distances);
:func:`metrics_from_indices` computes every metric from positions in that pool. The evaluator
calls it directly; :func:`set_metrics` is the ID-based wrapper.
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class PoolArrays:
    """One pool in ``audio_rank`` order, as arrays."""

    candidate_ids: np.ndarray
    relevance: np.ndarray
    audio_rank: np.ndarray
    pair_dist: np.ndarray                    # (N, N) parameter distances within the pool
    target_dist: np.ndarray | None = None    # (N,) distance from the target's parameters

    @classmethod
    def from_pool(cls, pool: pd.DataFrame, param_vectors: pd.DataFrame, distance: ParamDistance,
                  target_vector: np.ndarray | None = None) -> "PoolArrays":
        ids = pool["candidate_id"].to_numpy()
        vectors = param_vectors.loc[ids].to_numpy(dtype=np.float64)
        target_dist = None
        if target_vector is not None:
            target_dist = distance.cdist(np.asarray(target_vector, dtype=np.float64), vectors)[0]
        return cls(ids, pool["relevance"].to_numpy(dtype=np.float64), pool["audio_rank"].to_numpy(),
                   distance.cdist(vectors, vectors), target_dist)

    def head(self, n: int) -> "PoolArrays":
        """The top-``n`` sub-pool (pools of different N are prefixes of one ranking)."""
        return PoolArrays(self.candidate_ids[:n], self.relevance[:n], self.audio_rank[:n],
                          self.pair_dist[:n, :n], None if self.target_dist is None else self.target_dist[:n])

    @property
    def similarity(self) -> np.ndarray:
        return 1.0 - self.pair_dist


def metrics_from_indices(selected: Sequence[int], arrays: PoolArrays, epsilon_grid: Sequence[float],
                         topk_positions: Sequence[int]) -> dict[str, float]:
    sel = np.asarray(selected, dtype=int)
    k = len(sel)
    if k == 0 or len(np.unique(sel)) != k:
        raise ValueError("selected set must be non-empty without duplicates")
    rows, cols = np.triu_indices(k, k=1)
    pairs = arrays.pair_dist[sel[rows], sel[cols]]
    relevance, ranks = arrays.relevance[sel], arrays.audio_rank[sel]
    nan = float("nan")
    out: dict[str, float] = {
        "k": k,
        "mean_rel": float(relevance.mean()),
        "min_rel": float(relevance.min()),
        "mean_pair_dist": float(pairs.mean()) if len(pairs) else nan,
        "min_pair_dist": float(pairs.min()) if len(pairs) else nan,
        "max_audio_rank": int(ranks.max()),
        "mean_audio_rank": float(ranks.mean()),
        "overlap_with_topk": len(set(sel.tolist()) & set(np.asarray(topk_positions).tolist())) / k,
    }
    for epsilon in epsilon_grid:
        out[dup_rate_key(epsilon)] = dup_rate(pairs, epsilon)
    if arrays.target_dist is not None:
        out["target_param_dist_min"] = float(arrays.target_dist[sel].min())
        out["target_param_dist_mean"] = float(arrays.target_dist[sel].mean())
    return out


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
    """Compute all set-level metrics for selected candidate IDs.

    ``target_vector`` (unit-scale params of an in-dataset target) enables the diagnostic
    target-distance metrics; ``audio_vectors`` (Phase 6+) enables ``mean_pair_audio_dist``
    (cosine distance between feature vectors).
    """
    selected_ids = list(selected_ids)
    position = {cid: i for i, cid in enumerate(pool["candidate_id"])}
    missing = [s for s in selected_ids if s not in position]
    if missing:
        raise ValueError(f"selected IDs not in pool: {missing}")
    if len(set(selected_ids)) != len(selected_ids):
        raise ValueError("selected set contains duplicates")
    arrays = PoolArrays.from_pool(pool, param_vectors, distance, target_vector)
    out = metrics_from_indices([position[s] for s in selected_ids], arrays, epsilon_grid,
                               [position[t] for t in topk_ids if t in position])
    if audio_vectors is not None:
        audio_pairs = _cosine_pair_distances(audio_vectors.loc[selected_ids].to_numpy(dtype=np.float64))
        out["mean_pair_audio_dist"] = float(audio_pairs.mean()) if len(audio_pairs) else float("nan")
    return out
