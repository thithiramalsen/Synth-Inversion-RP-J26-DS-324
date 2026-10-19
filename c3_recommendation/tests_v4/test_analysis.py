"""Phase 3 parameter-structure helpers."""

import numpy as np
import pytest

from c3.analysis import knn_distances, leave_one_out_nn1, propose_epsilon_grid, random_pair_distances
from c3.param_space import ParamDistance


def test_knn_excludes_self_hand_computed():
    bank = np.array([[0.0], [0.1], [0.3], [0.7]])
    d = knn_distances(bank, bank, ParamDistance(1), k_max=2, query_bank_positions=[0, 1, 2, 3])
    assert np.allclose(d[:, 0], [0.1, 0.1, 0.2, 0.4])
    assert np.allclose(d[:, 1], [0.3, 0.2, 0.3, 0.6])


def test_knn_blocks_match_brute_force():
    rng = np.random.default_rng(0)
    bank, query = rng.random((500, 4)), rng.random((37, 4))
    metric = ParamDistance(4)
    expected = np.sort(metric.cdist(query, bank), axis=1)[:, :5]
    assert np.allclose(knn_distances(query, bank, metric, 5, max_cells=900), expected)


def test_knn_rejects_bad_k():
    with pytest.raises(ValueError):
        knn_distances(np.zeros((2, 1)), np.zeros((2, 1)), ParamDistance(1), k_max=2, query_bank_positions=[0, 1])


def test_random_pairs_distinct_and_seeded():
    X = np.arange(10, dtype=float).reshape(-1, 1) / 10
    metric = ParamDistance(1)
    first = random_pair_distances(X, 300, metric, np.random.default_rng(3))
    assert np.all(first > 0)  # rows are distinct, so a zero would mean a self-pair
    assert np.array_equal(first, random_pair_distances(X, 300, metric, np.random.default_rng(3)))


def test_epsilon_grid_sorted_deduplicated_with_sources():
    nn1 = np.linspace(0, 0.2, 1001)  # p25 = 0.05 coincides with a round value
    grid = propose_epsilon_grid(nn1, percentiles=(5, 25), round_values=(0.05, 0.10))
    values = [g["epsilon"] for g in grid]
    assert values == sorted(values) == [0.01, 0.05, 0.1]
    assert grid[1]["source"] == "p25 of bank 1-NN distance + round value"
    assert grid[0]["share_of_nn1_below"] == pytest.approx(0.05, abs=1e-3)


def test_leave_one_out_hand_computed():
    # dim 1 is constant: dropping it removes the 1/sqrt(2) shrink; dropping dim 0 leaves only ties.
    bank = np.column_stack([np.array([0.0, 0.2, 0.6, 1.0]), np.full(4, 0.5)])
    rows = leave_one_out_nn1(bank, bank, ["a", "b"], query_bank_positions=[0, 1, 2, 3])
    full, drop_a, drop_b = rows
    assert full["dropped"] is None
    assert full["median_nn1"] == pytest.approx(0.3 / np.sqrt(2))
    assert drop_a["median_nn1"] == 0.0
    assert drop_b["median_nn1"] == pytest.approx(0.3)
