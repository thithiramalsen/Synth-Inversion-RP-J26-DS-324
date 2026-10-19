"""Guide test 1 - parameter distance properties and hand-computed values."""

import numpy as np
import pytest

from c3.param_space import EUCLID, GOWER, ParamDistance, pairwise_param_distance, param_similarity, resolve_method


@pytest.mark.parametrize("method,mask", [(EUCLID, None), (GOWER, [False, False, True, False])])
def test_distance_symmetric_zero_on_identity_and_bounded(method, mask):
    rng = np.random.default_rng(1)
    X = rng.random((40, 4))
    if mask is not None:
        X[:, 2] = rng.integers(0, 3, size=40)  # categorical codes
    metric = ParamDistance(4, method=method, categorical_mask=mask)
    D = metric.cdist(X, X)
    assert np.allclose(D, D.T, atol=0)
    assert np.all(np.diag(D) == 0.0)
    assert D.min() >= 0.0 and D.max() <= 1.0


def test_identical_vectors_give_exact_zero():
    a = np.array([[0.123456789, 0.987654321, 0.5]])
    assert pairwise_param_distance(a, a.copy())[0, 0] == 0.0


def test_euclid_sqrt_d_hand_computed():
    assert pairwise_param_distance([0, 0, 0, 0], [1, 1, 1, 1])[0, 0] == pytest.approx(1.0)
    assert pairwise_param_distance([0, 0], [0.3, 0.4])[0, 0] == pytest.approx(0.5 / np.sqrt(2))
    assert param_similarity([0, 0], [0.3, 0.4])[0, 0] == pytest.approx(1 - 0.5 / np.sqrt(2))


def test_euclid_weights_hand_computed():
    # sqrt(4 * 0.5^2 + 0 * 1^2) / sqrt(4 + 0) = 0.5
    d = pairwise_param_distance([0, 0], [0.5, 1.0], weights=[4, 0])
    assert d[0, 0] == pytest.approx(0.5)


def test_gower_hand_computed():
    # continuous |0.2 - 0.6| = 0.4, categorical 1 != 2 -> 1; mean = 0.7
    d = pairwise_param_distance([0.2, 1], [0.6, 2], method=GOWER, categorical_mask=[False, True])
    assert d[0, 0] == pytest.approx(0.7)
    same_cat = pairwise_param_distance([0.2, 1], [0.6, 1], method=GOWER, categorical_mask=[False, True])
    assert same_cat[0, 0] == pytest.approx(0.2)


def test_auto_method_resolution():
    assert resolve_method("auto", categorical_mask=[False, False]) == EUCLID
    assert resolve_method("auto", categorical_mask=[False, True]) == GOWER
    with pytest.raises(ValueError):
        resolve_method("euclid_sqrt_d", categorical_mask=[True])
    with pytest.raises(ValueError):
        resolve_method("cosine")


def test_pdist_matches_cdist_upper_triangle():
    X = np.random.default_rng(2).random((7, 5))
    metric = ParamDistance(5)
    rows, cols = np.triu_indices(7, k=1)
    assert np.allclose(metric.pdist(X), metric.cdist(X, X)[rows, cols])
    assert metric.pdist(X[:1]).size == 0


def test_iter_cdist_chunks_match_full_matrix():
    rng = np.random.default_rng(3)
    A, B = rng.random((53, 6)), rng.random((200, 6))
    metric = ParamDistance(6)
    blocks = list(metric.iter_cdist(A, B, max_cells=1000))
    assert len(blocks) > 1
    assert np.array_equal(np.vstack([b for _, b in blocks]), metric.cdist(A, B))


def test_dimension_mismatch_raises():
    with pytest.raises(ValueError):
        ParamDistance(3).cdist(np.zeros((2, 3)), np.zeros((2, 4)))
