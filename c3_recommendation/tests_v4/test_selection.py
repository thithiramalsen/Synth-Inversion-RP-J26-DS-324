"""Guide tests 7, 8, 9, 10 and 12 - selection policies."""

import numpy as np
import pandas as pd
import pytest

from c3.metrics import set_metrics
from c3.param_space import ParamDistance
from c3.retrieval import pool_from_scores
from c3.selection import dpp_greedy, mmr, random_from_pool, topk

D = 5
METRIC = ParamDistance(D)


def random_pool(seed: int, n: int = 30, ties: bool = False):
    rng = np.random.default_rng(seed)
    ids = [f"c_{i:03d}" for i in range(n)]
    scores = rng.random(n)
    if ties:
        scores = np.round(scores, 1)  # many exact ties
    params = pd.DataFrame(rng.random((n, D)), index=ids)
    return pool_from_scores(scores, ids, N=n), params


@pytest.mark.parametrize("seed", range(200))
def test_mmr_lambda_one_equals_topk(seed):
    pool, params = random_pool(seed, ties=seed % 2 == 0)
    for k in (1, 3, 5, 10):
        for scaling in ("none", "pool_minmax"):
            assert mmr(pool, params, k, 1.0, METRIC, scaling) == topk(pool, k)


@pytest.mark.parametrize("lam", [0.0, 0.3, 0.5, 0.75, 0.95])
def test_mmr_first_pick_is_top_relevance(lam):
    for seed in range(50):
        pool, params = random_pool(seed)
        assert mmr(pool, params, 5, lam, METRIC)[0] == pool["candidate_id"].iloc[0]


def test_mmr_diversifies_near_duplicates():
    rng = np.random.default_rng(0)
    base = rng.random(D)
    dupes = base + rng.normal(0, 1e-3, (5, D))            # 5 near-identical, high relevance
    spread = rng.random((5, D))                           # 5 spread-out, lower relevance
    ids = [f"dup_{i}" for i in range(5)] + [f"spr_{i}" for i in range(5)]
    params = pd.DataFrame(np.clip(np.vstack([dupes, spread]), 0, 1), index=ids)
    scores = np.r_[np.linspace(0.95, 0.91, 5), np.linspace(0.85, 0.81, 5)]
    pool = pool_from_scores(scores, ids, N=10)

    base_ids, mmr_ids = topk(pool, 5), mmr(pool, params, 5, 0.5, METRIC)
    args = dict(pool=pool, param_vectors=params, distance=METRIC, epsilon_grid=[0.05], topk_ids=base_ids)
    assert set_metrics(mmr_ids, **args)["mean_pair_dist"] > set_metrics(base_ids, **args)["mean_pair_dist"]
    assert set_metrics(base_ids, **args)["dup_rate@0.05"] == 1.0


def test_policies_deterministic_including_ties():
    for seed in range(20):
        pool_a, params = random_pool(seed, ties=True)
        pool_b, _ = random_pool(seed, ties=True)
        assert pool_a.equals(pool_b)
        for lam in (0.4, 0.75):
            assert mmr(pool_a, params, 5, lam, METRIC) == mmr(pool_b, params, 5, lam, METRIC)


def test_mmr_handles_identical_candidates_by_audio_rank():
    ids = ["a", "b", "c"]
    params = pd.DataFrame(np.full((3, D), 0.5), index=ids)
    pool = pool_from_scores(np.array([0.8, 0.8, 0.8]), ids, N=3)
    assert mmr(pool, params, 3, 0.5, METRIC) == ["a", "b", "c"]


def test_random_from_pool_respects_seed():
    pool, _ = random_pool(0)
    draw = lambda s: random_from_pool(pool, 5, np.random.default_rng(s))
    assert draw(42) == draw(42)
    assert draw(42) != draw(43)
    assert len(set(draw(42))) == 5 and set(draw(42)) <= set(pool["candidate_id"])


def test_invalid_selection_requests():
    pool, params = random_pool(0, n=4)
    with pytest.raises(ValueError):
        topk(pool, 5)
    with pytest.raises(ValueError):
        mmr(pool, params, 5, 0.5, METRIC)
    with pytest.raises(ValueError):
        mmr(pool, params, 2, 1.5, METRIC)
    with pytest.raises(NotImplementedError):
        dpp_greedy(pool, params, 2)
