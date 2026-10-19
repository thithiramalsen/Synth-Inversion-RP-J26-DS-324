"""Run selection policies over a list of targets.

For every target: score the bank once, build the largest pool once (smaller pools are prefixes
of the same ranking), compute the pool's parameter distances once, then evaluate top-k, MMR
for every lambda, and the random-from-pool baseline on that same pool (guide §8.2).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np
import pandas as pd

from .metrics import PoolArrays, metrics_from_indices
from .param_space import ParamDistance
from .relevance import RelevanceFunction
from .retrieval import pool_from_scores
from .selection import mmr_indices
from .splits import LeakageError

TOPK, MMR, RANDOM = "topk", "mmr", "random"


@dataclass(frozen=True)
class EvalSpec:
    pool_sizes: Sequence[int]
    k_values: Sequence[int]
    lambda_grid: Sequence[float]
    epsilon_grid: Sequence[float]
    relevance_scaling: str = "none"
    random_draws: int = 200
    seed: int = 0

    def __post_init__(self):
        if max(self.k_values) > min(self.pool_sizes):
            raise ValueError("every k must fit in the smallest pool")

    @classmethod
    def from_config(cls, cfg, epsilon_grid: Sequence[float] | None = None) -> "EvalSpec":
        grid = epsilon_grid if epsilon_grid is not None else cfg["near_duplicate.epsilon_grid"]
        if isinstance(grid, str):
            raise ValueError(f"near_duplicate.epsilon_grid is not set ({grid!r}); run Phase 3 first")
        return cls(tuple(int(n) for n in cfg["retrieval.pool_sizes"]), tuple(int(k) for k in cfg["selection.k_values"]),
                   tuple(float(x) for x in cfg["selection.lambda_grid"]), tuple(float(e) for e in grid),
                   cfg["selection.relevance_scaling"], int(cfg["selection.random_baseline_draws"]), cfg.seed)


@dataclass
class EvalResult:
    per_target: pd.DataFrame
    recommendations: pd.DataFrame
    seconds_per_target: float
    lambda_one_mismatches: int = 0
    checks: dict = field(default_factory=dict)


def evaluate(
    relevance_fn: RelevanceFunction,
    target_ids: Sequence[str],
    bank_ids: Sequence[str],
    unit_params: pd.DataFrame,
    distance: ParamDistance,
    spec: EvalSpec,
    progress: Callable[[int, int], None] | None = None,
) -> EvalResult:
    bank_ids = np.asarray(list(bank_ids), dtype=object)
    target_ids = list(target_ids)
    if set(target_ids) & set(bank_ids):
        raise LeakageError("evaluation targets overlap the candidate bank")
    bank_position = {cid: i for i, cid in enumerate(bank_ids)}
    bank_vectors = unit_params.loc[bank_ids].to_numpy(np.float64)
    target_vectors = unit_params.loc[target_ids].to_numpy(np.float64)
    target_seed_index = unit_params.index.get_indexer(target_ids)  # stable per-target seed component
    relevance_fn.fit(list(bank_ids))
    n_max = max(spec.pool_sizes)

    rows, recs, lambda_one_mismatches = [], [], 0
    started = time.perf_counter()
    for t, target in enumerate(target_ids):
        scores = relevance_fn.score_bank(target)
        if len(scores) != len(bank_ids):
            raise ValueError("score_bank returned the wrong number of scores")
        pool = pool_from_scores(scores, bank_ids, n_max)
        positions = np.array([bank_position[cid] for cid in pool["candidate_id"]])
        vectors = bank_vectors[positions]
        full = PoolArrays(pool["candidate_id"].to_numpy(), pool["relevance"].to_numpy(np.float64),
                          pool["audio_rank"].to_numpy(), distance.cdist(vectors, vectors),
                          distance.cdist(target_vectors[t], vectors)[0])
        if target in set(full.candidate_ids):
            raise LeakageError(f"self-match for {target}")

        for N in spec.pool_sizes:
            arrays = full.head(N)
            similarity = arrays.similarity
            for k in spec.k_values:
                top = list(range(k))
                base = {"target_id": target, "N": N, "k": k}

                def record(policy, lam, selected, extra=None):
                    metrics = metrics_from_indices(selected, arrays, spec.epsilon_grid, top)
                    rows.append({**base, "policy": policy, "lam": lam, **metrics, **(extra or {})})
                    for rank, i in enumerate(selected, start=1):
                        recs.append({**base, "policy": policy, "lam": lam, "rank": rank,
                                     "candidate_id": arrays.candidate_ids[i],
                                     "relevance": float(arrays.relevance[i]),
                                     "audio_rank": int(arrays.audio_rank[i])})

                record(TOPK, np.nan, top)
                for lam in spec.lambda_grid:
                    selected = mmr_indices(arrays.relevance, similarity, k, lam, spec.relevance_scaling)
                    if lam == 1.0 and selected != top:
                        lambda_one_mismatches += 1
                    record(MMR, lam, selected)

                rng = np.random.default_rng([spec.seed, int(target_seed_index[t]), N, k])
                draws = [metrics_from_indices(rng.choice(N, size=k, replace=False), arrays, spec.epsilon_grid, top)
                         for _ in range(spec.random_draws)]
                averaged = {key: float(np.mean([d[key] for d in draws])) for key in draws[0]}
                rows.append({**base, "policy": RANDOM, "lam": np.nan, **averaged, "k": k,
                             "random_draws": spec.random_draws})
        if progress:
            progress(t + 1, len(target_ids))

    seconds = (time.perf_counter() - started) / max(1, len(target_ids))
    per_target = pd.DataFrame(rows)
    recommendations = pd.DataFrame(recs)
    return EvalResult(per_target, recommendations, seconds, lambda_one_mismatches)
