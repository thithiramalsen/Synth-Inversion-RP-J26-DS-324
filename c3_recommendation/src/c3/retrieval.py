"""Top-N candidate pool construction.

Relevance alone decides pool membership; parameters never influence who enters the pool
(guide §8.1). Every policy then selects from this same pool (guide §8.2).
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

from .relevance import RelevanceFunction
from .splits import LeakageError

POOL_COLUMNS = ["candidate_id", "relevance", "audio_rank"]


def pool_from_scores(scores: np.ndarray, candidate_ids: Sequence[str], N: int) -> pd.DataFrame:
    """Top ``N`` by relevance desc, ties broken by candidate_id asc; ``audio_rank`` is 1-based."""
    scores = np.asarray(scores, dtype=np.float64)
    ids = np.asarray(candidate_ids, dtype=object)
    if scores.shape != (len(ids),):
        raise ValueError("scores and candidate_ids must have the same length")
    if np.isnan(scores).any():
        raise ValueError("relevance scores contain NaN")
    if N < 1 or N > len(ids):
        raise ValueError(f"pool size N={N} must be in [1, {len(ids)}]")
    # Keep everything tied with the N-th best score so the tie-break is exact at the boundary.
    if N < len(ids):
        threshold = np.partition(scores, len(ids) - N)[len(ids) - N]
        keep = np.flatnonzero(scores >= threshold)
    else:
        keep = np.arange(len(ids))
    order = keep[np.lexsort((ids[keep].astype(str), -scores[keep]))][:N]
    return pd.DataFrame({
        "candidate_id": ids[order].astype(str),
        "relevance": scores[order],
        "audio_rank": np.arange(1, len(order) + 1),
    })


def build_pool(relevance_fn: RelevanceFunction, target_id: str, bank_ids: Sequence[str], N: int) -> pd.DataFrame:
    """Pool for an in-dataset target. The target must not be in the searchable bank (R7)."""
    bank_ids = list(bank_ids)
    if target_id in set(bank_ids):
        raise LeakageError(f"target {target_id} is present in the candidate bank")
    pool = pool_from_scores(relevance_fn.score_ids(target_id, bank_ids), bank_ids, N)
    assert target_id not in set(pool["candidate_id"]), "self-match in pool"
    return pool


def build_pool_for_audio(relevance_fn: RelevanceFunction, audio: np.ndarray, sr: int,
                         bank_ids: Sequence[str], N: int) -> pd.DataFrame:
    """Pool for an external audio query."""
    bank_ids = list(bank_ids)
    return pool_from_scores(relevance_fn.score_audio(audio, sr, bank_ids), bank_ids, N)
