"""Data for the offline demo viewer (illustration only, not an evaluation).

For each target: one audio-relevance pool, top-k, and the MMR set at every demo lambda, all
computed with the same tested functions the evaluator uses. Lambda values here are for
illustration; the operating point is chosen on validation data in Phase 7.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

from .metrics import PoolArrays, metrics_from_indices
from .param_space import ParamDistance
from .relevance import RelevanceFunction
from .retrieval import pool_from_scores
from .selection import mmr_indices
from .splits import LeakageError

DEMO_LAMBDAS = (1.0, 0.99, 0.98, 0.97, 0.96, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.6, 0.5)
SET_METRICS = ("mean_rel", "min_rel", "mean_pair_dist", "min_pair_dist")


def build_demo_data(
    relevance_fn: RelevanceFunction,
    target_ids: Sequence[str],
    bank_ids: Sequence[str],
    unit_params: pd.DataFrame,
    distance: ParamDistance,
    lambdas: Sequence[float] = DEMO_LAMBDAS,
    k: int = 5,
    pool_size: int = 100,
    relevance_scaling: str = "none",
) -> dict:
    """Return ``{"targets": [...], "clips": [...]}``; ``clips`` lists every sample ID to export.

    Each target holds its parameters and, per lambda, the selected candidates (ID, relevance,
    audio rank, parameters) plus set metrics. ``lambdas`` must include 1.0 (= top-k).
    """
    if 1.0 not in lambdas:
        raise ValueError("lambdas must include 1.0 so the plain top-k set is shown")
    bank_ids = np.asarray(list(bank_ids), dtype=object)
    if set(target_ids) & set(bank_ids):
        raise LeakageError("demo targets overlap the candidate bank")
    bank_position = {cid: i for i, cid in enumerate(bank_ids)}
    bank_vectors = unit_params.loc[bank_ids].to_numpy(np.float64)
    relevance_fn.fit(list(bank_ids))

    targets, clips = [], []
    for target in target_ids:
        pool = pool_from_scores(relevance_fn.score_bank(target), bank_ids, pool_size)
        vectors = bank_vectors[[bank_position[c] for c in pool["candidate_id"]]]
        arrays = PoolArrays(pool["candidate_id"].to_numpy(), pool["relevance"].to_numpy(np.float64),
                            pool["audio_rank"].to_numpy(), distance.cdist(vectors, vectors))
        top = list(range(k))
        sets = {}
        for lam in lambdas:
            selected = mmr_indices(arrays.relevance, arrays.similarity, k, lam, relevance_scaling)
            metrics = metrics_from_indices(selected, arrays, (), top)
            sets[f"{lam:g}"] = {
                "items": [{"id": str(arrays.candidate_ids[i]), "relevance": float(arrays.relevance[i]),
                           "audio_rank": int(arrays.audio_rank[i]),
                           "params": [round(float(v), 4) for v in vectors[i]],
                           "in_topk": i in top} for i in selected],
                **{m: float(metrics[m]) for m in SET_METRICS},
                "overlap_with_topk": float(metrics["overlap_with_topk"]),
            }
            clips.extend(item["id"] for item in sets[f"{lam:g}"]["items"])
        if [item["audio_rank"] for item in sets["1"]["items"]] != list(range(1, k + 1)):
            raise AssertionError("lambda = 1 did not return the plain top-k")
        targets.append({"id": target, "params": [round(float(v), 4) for v in unit_params.loc[target]],
                        "sets": sets})
        clips.append(target)
    return {"targets": targets, "clips": sorted(set(clips)), "lambdas": [f"{lam:g}" for lam in lambdas],
            "k": k, "pool_size": pool_size, "parameter_names": list(unit_params.columns)}
