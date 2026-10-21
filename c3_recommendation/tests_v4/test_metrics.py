"""Guide test 11 - set metrics on a hand-built set."""

import numpy as np
import pandas as pd
import pytest

from c3.metrics import set_metrics
from c3.param_space import ParamDistance

METRIC = ParamDistance(1)


@pytest.fixture
def hand_set():
    # 1-D unit params so distances are |a - b|: pairs (a,b)=0.05 (a,c)=0.5 (b,c)=0.45
    params = pd.DataFrame({"p": [0.0, 0.05, 0.5, 0.9]}, index=["a", "b", "c", "d"])
    pool = pd.DataFrame({"candidate_id": ["a", "b", "c", "d"],
                         "relevance": [0.9, 0.8, 0.7, 0.6],
                         "audio_rank": [1, 2, 3, 4]})
    return pool, params


def test_set_metrics_hand_computed(hand_set):
    pool, params = hand_set
    m = set_metrics(["a", "c", "b"], pool, params, METRIC, epsilon_grid=[0.01, 0.1, 0.46],
                    topk_ids=["a", "b", "d"], target_vector=np.array([0.2]))
    assert m["k"] == 3
    assert m["mean_rel"] == pytest.approx(0.8) and m["min_rel"] == pytest.approx(0.7)
    assert m["mean_pair_dist"] == pytest.approx((0.05 + 0.5 + 0.45) / 3)
    assert m["min_pair_dist"] == pytest.approx(0.05)
    assert m["dup_rate@0.01"] == 0.0
    assert m["dup_rate@0.1"] == pytest.approx(1 / 3)
    assert m["dup_rate@0.46"] == pytest.approx(2 / 3)
    assert m["max_audio_rank"] == 3 and m["mean_audio_rank"] == pytest.approx(2.0)
    assert m["overlap_with_topk"] == pytest.approx(2 / 3)
    assert m["target_param_dist_min"] == pytest.approx(0.15)
    assert m["target_param_dist_mean"] == pytest.approx((0.2 + 0.3 + 0.15) / 3)


def test_audio_pair_distance_and_single_item(hand_set):
    pool, params = hand_set
    audio = pd.DataFrame([[1, 0], [0, 1], [1, 1], [2, 0]], index=["a", "b", "c", "d"], dtype=float)
    m = set_metrics(["a", "d"], pool, params, METRIC, [0.1], ["a", "b"], audio_vectors=audio)
    assert m["mean_pair_audio_dist"] == pytest.approx(0.0)  # same direction
    single = set_metrics(["a"], pool, params, METRIC, [0.1], ["a"])
    assert np.isnan(single["mean_pair_dist"]) and np.isnan(single["dup_rate@0.1"])


def test_rejects_ids_outside_pool_and_duplicates(hand_set):
    pool, params = hand_set
    with pytest.raises(ValueError):
        set_metrics(["a", "z"], pool, params, METRIC, [0.1], ["a"])
    with pytest.raises(ValueError):
        set_metrics(["a", "a"], pool, params, METRIC, [0.1], ["a"])
