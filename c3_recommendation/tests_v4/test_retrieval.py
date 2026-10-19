"""Guide test 6 - the pool never contains the target; deterministic tie-break."""

import numpy as np
import pandas as pd
import pytest

from c3.relevance import ParamProxyRelevance
from c3.retrieval import build_pool, pool_from_scores
from c3.splits import LeakageError


@pytest.fixture
def proxy():
    rng = np.random.default_rng(0)
    ids = [f"s_{i:04d}" for i in range(300)]
    params = pd.DataFrame(rng.random((300, 6)), index=ids, columns=list("abcdef"))
    return ParamProxyRelevance(params, seed=11), ids


def test_pool_never_contains_target(proxy):
    relevance, ids = proxy
    for target in ids[:30]:
        bank = [i for i in ids if i != target]
        pool = build_pool(relevance, target, bank, N=50)
        assert target not in set(pool["candidate_id"])
        assert len(pool) == 50 and list(pool["audio_rank"]) == list(range(1, 51))
        assert pool["relevance"].is_monotonic_decreasing


def test_target_in_bank_raises(proxy):
    relevance, ids = proxy
    with pytest.raises(LeakageError):
        build_pool(relevance, ids[0], ids, N=10)


def test_ties_broken_by_candidate_id_including_boundary():
    scores = np.array([0.5, 0.9, 0.5, 0.9, 0.5, 0.1])
    ids = ["e", "d", "c", "b", "a", "f"]
    pool = pool_from_scores(scores, ids, N=3)
    # 0.9 ties -> b, d ; then the 0.5 tie at the boundary -> a (smallest id) wins
    assert pool["candidate_id"].tolist() == ["b", "d", "a"]


def test_invalid_pool_requests():
    with pytest.raises(ValueError):
        pool_from_scores(np.array([0.1, np.nan]), ["a", "b"], N=1)
    with pytest.raises(ValueError):
        pool_from_scores(np.array([0.1, 0.2]), ["a", "b"], N=3)
