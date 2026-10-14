"""Relevance interface: smoke-test proxy determinism and the C4 placeholder."""

import numpy as np
import pandas as pd
import pytest

from c3.relevance import C4Relevance, ParamProxyRelevance


@pytest.fixture
def params():
    rng = np.random.default_rng(5)
    ids = [f"s_{i:03d}" for i in range(100)]
    return pd.DataFrame(rng.random((100, 8)), index=ids, columns=[f"p{i}" for i in range(8)])


def test_proxy_is_marked_smoke_test(params):
    proxy = ParamProxyRelevance(params, seed=1)
    assert proxy.name == "SMOKE_TEST_PROXY"
    assert len(proxy.subset_columns) == 4
    assert proxy.describe()["subset_columns"] == ParamProxyRelevance(params, seed=1).subset_columns


def test_proxy_scores_independent_of_candidate_order_and_set(params):
    proxy = ParamProxyRelevance(params, seed=1)
    ids = list(params.index[1:])
    full = pd.Series(proxy.score_ids("s_000", ids), index=ids)
    subset = ids[::-3]
    assert np.array_equal(proxy.score_ids("s_000", subset), full.loc[subset].to_numpy())


def test_proxy_correlates_with_subset_distance(params):
    proxy = ParamProxyRelevance(params, seed=1, noise_sigma=0.0)
    score = proxy.score_ids("s_000", ["s_000"])[0]
    assert score == pytest.approx(1.0)
    with pytest.raises(NotImplementedError):
        proxy.score_audio(np.zeros(10), 44100, ["s_001"])


def test_c4_placeholder_raises():
    with pytest.raises(NotImplementedError, match="C4"):
        C4Relevance()
