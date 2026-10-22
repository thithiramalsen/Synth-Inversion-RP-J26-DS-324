"""Demo viewer data builder."""

import numpy as np
import pandas as pd
import pytest

from c3.demo import build_demo_data
from c3.param_space import ParamDistance
from c3.relevance import ParamProxyRelevance
from c3.splits import LeakageError


@pytest.fixture
def toy():
    rng = np.random.default_rng(0)
    ids = [f"s_{i:03d}" for i in range(120)]
    params = pd.DataFrame(rng.random((120, 6)), index=ids, columns=[f"p{i}" for i in range(6)])
    return params, ids[:100], ids[100:103]


def test_demo_data_structure_and_lambda_one(toy):
    params, bank, targets = toy
    data = build_demo_data(ParamProxyRelevance(params, seed=2), targets, bank, params, ParamDistance(6),
                           lambdas=(1.0, 0.8, 0.5), k=4, pool_size=20)
    assert [t["id"] for t in data["targets"]] == targets
    for target in data["targets"]:
        top = target["sets"]["1"]["items"]
        assert [item["audio_rank"] for item in top] == [1, 2, 3, 4]
        assert all(item["in_topk"] for item in top)
        for lam in data["lambdas"]:
            chosen = target["sets"][lam]
            assert len(chosen["items"]) == 4 and len({i["id"] for i in chosen["items"]}) == 4
            assert all(i["id"] not in targets for i in chosen["items"])
            assert chosen["items"][0]["audio_rank"] == 1  # MMR always starts from the closest sound
    expected_clips = {t["id"] for t in data["targets"]} | {
        i["id"] for t in data["targets"] for s in t["sets"].values() for i in s["items"]}
    assert set(data["clips"]) == expected_clips


def test_demo_requires_lambda_one_and_no_leakage(toy):
    params, bank, targets = toy
    with pytest.raises(ValueError):
        build_demo_data(ParamProxyRelevance(params, seed=2), targets, bank, params, ParamDistance(6), lambdas=(0.8,))
    with pytest.raises(LeakageError):
        build_demo_data(ParamProxyRelevance(params, seed=2), bank[:2], bank, params, ParamDistance(6))
