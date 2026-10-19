"""Set-selection policies. All take the same pool and return an ordered list of k IDs.

The pool is the DataFrame from :mod:`c3.retrieval` (rows in ``audio_rank`` order).
Policies see only relevance values and parameter vectors - never how relevance was made.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .param_space import ParamDistance

RELEVANCE_SCALINGS = ("none", "pool_minmax")


def _check_pool(pool: pd.DataFrame, k: int) -> None:
    if k < 1:
        raise ValueError("k must be at least 1")
    if k > len(pool):
        raise ValueError(f"k={k} exceeds pool size {len(pool)}")
    if not pool["audio_rank"].is_monotonic_increasing:
        raise ValueError("pool must be ordered by audio_rank")


def topk(pool: pd.DataFrame, k: int) -> list[str]:
    """Similarity-only baseline: the first k candidates by relevance."""
    _check_pool(pool, k)
    return pool["candidate_id"].iloc[:k].tolist()


def scale_relevance(relevance: np.ndarray, relevance_scaling: str) -> np.ndarray:
    if relevance_scaling == "none":
        return relevance
    if relevance_scaling == "pool_minmax":
        span = relevance.max() - relevance.min()
        return np.zeros_like(relevance) if span == 0 else (relevance - relevance.min()) / span
    raise ValueError(f"relevance_scaling must be one of {RELEVANCE_SCALINGS}")


def mmr(
    pool: pd.DataFrame,
    param_vectors: pd.DataFrame,
    k: int,
    lam: float,
    distance: ParamDistance,
    relevance_scaling: str = "none",
) -> list[str]:
    """Maximal marginal relevance with the redundancy penalty in parameter space.

    ``score(c) = lam * rel(c) - (1 - lam) * max_{s in S} param_similarity(c, s)``;
    ties go to the lower ``audio_rank`` (unique within a pool). ``lam == 1`` equals top-k.
    """
    _check_pool(pool, k)
    ids = pool["candidate_id"].tolist()
    vectors = param_vectors.loc[ids].to_numpy(dtype=np.float64)
    similarity = 1.0 - distance.cdist(vectors, vectors)
    selected = mmr_indices(pool["relevance"].to_numpy(dtype=np.float64), similarity, k, lam, relevance_scaling)
    return [ids[i] for i in selected]


def mmr_indices(
    relevance: np.ndarray,
    similarity: np.ndarray,
    k: int,
    lam: float,
    relevance_scaling: str = "none",
) -> list[int]:
    """MMR on precomputed arrays; positions refer to a pool in ``audio_rank`` order.

    ``similarity`` is the pool's parameter-similarity matrix. Used by the evaluator so
    every lambda reuses one matrix per pool.
    """
    if not 0.0 <= lam <= 1.0:
        raise ValueError("lam must lie in [0, 1]")
    if k < 1 or k > len(relevance):
        raise ValueError(f"k={k} must be in [1, {len(relevance)}]")
    relevance = scale_relevance(np.asarray(relevance, dtype=np.float64), relevance_scaling)
    penalty = np.zeros(len(relevance))
    available = np.ones(len(relevance), dtype=bool)
    selected: list[int] = []
    for _ in range(k):
        score = lam * relevance - (1.0 - lam) * penalty
        score[~available] = -np.inf
        best = int(np.flatnonzero(score == score.max())[0])  # first = lowest audio_rank
        selected.append(best)
        available[best] = False
        penalty = np.maximum(penalty, similarity[best])
    return selected


def random_from_pool(pool: pd.DataFrame, k: int, rng: np.random.Generator) -> list[str]:
    """Contextual baseline: k distinct candidates drawn uniformly from the same pool."""
    _check_pool(pool, k)
    picks = rng.choice(len(pool), size=k, replace=False)
    return pool["candidate_id"].iloc[picks].tolist()


def dpp_greedy(*args, **kwargs) -> list[str]:
    """Optional comparator - do not implement until the user asks (after Phase 8).

    Greedy MAP inference for a DPP (Chen et al., NeurIPS 2018) with quality-diversity kernel
    ``L = diag(q) · K_theta · diag(q)``, where ``K_theta`` is the parameter-similarity matrix
    of the pool and ``q`` is derived from relevance.
    """
    raise NotImplementedError("dpp_greedy is an optional extension, not implemented yet")
