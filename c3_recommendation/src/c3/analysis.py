"""Parameter-space structure analysis (Phase 3).

Audio-vs-parameter divergence analysis (Phase 9) is added here later.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from .param_space import DEFAULT_MAX_CELLS, ParamDistance


def knn_distances(
    query: np.ndarray,
    bank: np.ndarray,
    metric: ParamDistance,
    k_max: int = 10,
    query_bank_positions: Sequence[int] | None = None,
    max_cells: int = DEFAULT_MAX_CELLS,
) -> np.ndarray:
    """Sorted distances from each query row to its ``k_max`` nearest bank rows.

    ``query_bank_positions[i]`` is the bank row of query ``i`` (when queries are bank
    members); that self-match is excluded. Computed in row blocks to bound memory.
    """
    query, bank = np.asarray(query, np.float64), np.asarray(bank, np.float64)
    if query_bank_positions is not None and len(query_bank_positions) != len(query):
        raise ValueError("query_bank_positions must align with query rows")
    available = len(bank) - (0 if query_bank_positions is None else 1)
    if not 1 <= k_max <= available:
        raise ValueError(f"k_max must be in [1, {available}]")
    out = np.empty((len(query), k_max))
    for start, block in metric.iter_cdist(query, bank, max_cells=max_cells):
        if query_bank_positions is not None:
            rows = np.arange(len(block))
            block[rows, np.asarray(query_bank_positions[start : start + len(block)])] = np.inf
        nearest = np.partition(block, k_max - 1, axis=1)[:, :k_max]
        out[start : start + len(block)] = np.sort(nearest, axis=1)
    return out


def random_pair_distances(X: np.ndarray, n_pairs: int, metric: ParamDistance, rng: np.random.Generator) -> np.ndarray:
    """Distances between ``n_pairs`` random pairs of distinct rows of ``X``."""
    X = np.asarray(X, np.float64)
    a = rng.integers(0, len(X), size=n_pairs)
    b = (a + rng.integers(1, len(X), size=n_pairs)) % len(X)  # never equal to a
    diffs = [metric.cdist(X[i], X[j])[0, 0] for i, j in zip(a, b)]
    return np.asarray(diffs)


def propose_epsilon_grid(
    nn1: np.ndarray,
    percentiles: Sequence[float] = (1, 5, 10, 25),
    round_values: Sequence[float] = (0.05, 0.10, 0.15),
    decimals: int = 4,
) -> list[dict]:
    """Candidate near-duplicate thresholds: 1-NN percentiles plus round values.

    Returns one entry per unique value (sorted) with where it came from.
    """
    candidates: dict[float, list[str]] = {}
    for p in percentiles:
        value = round(float(np.percentile(nn1, p)), decimals)
        candidates.setdefault(value, []).append(f"p{p:g} of bank 1-NN distance")
    for value in round_values:
        candidates.setdefault(round(float(value), decimals), []).append("round value")
    return [{"epsilon": eps, "source": " + ".join(src),
             "share_of_nn1_below": float(np.mean(nn1 < eps))}
            for eps, src in sorted(candidates.items())]


def leave_one_out_nn1(
    query: np.ndarray,
    bank: np.ndarray,
    names: Sequence[str],
    query_bank_positions: Sequence[int] | None = None,
    max_cells: int = DEFAULT_MAX_CELLS,
) -> list[dict]:
    """1-NN distance with each parameter dropped in turn (``euclid_sqrt_d`` over d-1 dims).

    A parameter whose removal lowers the 1-NN distance the most contributes most to
    separating near neighbours under equal weighting.
    """
    query, bank = np.asarray(query, np.float64), np.asarray(bank, np.float64)
    full = knn_distances(query, bank, ParamDistance(len(names)), 1, query_bank_positions, max_cells)[:, 0]
    rows = []
    for j, name in enumerate(names):
        keep = [i for i in range(len(names)) if i != j]
        nn1 = knn_distances(query[:, keep], bank[:, keep], ParamDistance(len(keep)), 1,
                            query_bank_positions, max_cells)[:, 0]
        rows.append({"dropped": name, "median_nn1": float(np.median(nn1)),
                     "mean_nn1": float(nn1.mean()),
                     "median_change_vs_full": float(np.median(nn1) - np.median(full))})
    rows.insert(0, {"dropped": None, "median_nn1": float(np.median(full)), "mean_nn1": float(full.mean()),
                    "median_change_vs_full": 0.0})
    return rows
