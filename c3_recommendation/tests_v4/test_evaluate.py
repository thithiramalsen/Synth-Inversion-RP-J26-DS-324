"""Evaluator and statistics on a small synthetic bank."""

import numpy as np
import pandas as pd
import pytest

from c3.evaluate import MMR, RANDOM, TOPK, EvalSpec, evaluate
from c3.metrics import PoolArrays, metrics_from_indices
from c3.param_space import ParamDistance
from c3.relevance import ParamProxyRelevance
from c3.retrieval import pool_from_scores
from c3.splits import LeakageError
from c3.stats import add_paired_deltas, bootstrap_mean_ci, bootstrap_indices, summarize

SPEC = EvalSpec(pool_sizes=(20, 30), k_values=(3, 5), lambda_grid=(1.0, 0.7, 0.4),
                epsilon_grid=(0.1, 0.2), random_draws=10, seed=5)


@pytest.fixture(scope="module")
def setup():
    rng = np.random.default_rng(0)
    ids = [f"s_{i:04d}" for i in range(300)]
    params = pd.DataFrame(rng.random((300, 8)), index=ids, columns=[f"p{i}" for i in range(8)])
    bank, targets = ids[:250], ids[250:262]
    metric = ParamDistance(8)
    result = evaluate(ParamProxyRelevance(params, seed=3), targets, bank, params, metric, SPEC)
    return params, bank, targets, metric, result


def test_row_counts_and_policies(setup):
    _, _, targets, _, result = setup
    per_config = 1 + len(SPEC.lambda_grid) + 1
    assert len(result.per_target) == len(targets) * 2 * 2 * per_config
    assert set(result.per_target["policy"]) == {TOPK, MMR, RANDOM}
    assert (result.per_target.loc[result.per_target.policy == RANDOM, "random_draws"] == 10).all()


def test_lambda_one_equals_topk(setup):
    *_, result = setup
    assert result.lambda_one_mismatches == 0
    recs = result.recommendations
    keys = ["target_id", "N", "k", "rank"]
    top = recs[recs.policy == TOPK].set_index(keys)["candidate_id"].sort_index()
    lam1 = recs[(recs.policy == MMR) & (recs.lam == 1.0)].set_index(keys)["candidate_id"].sort_index()
    assert top.equals(lam1)


def test_no_self_matches_and_bank_only(setup):
    _, bank, _, _, result = setup
    recs = result.recommendations
    assert not (recs["candidate_id"] == recs["target_id"]).any()
    assert set(recs["candidate_id"]) <= set(bank)


def test_smaller_pool_is_prefix_of_larger(setup):
    *_, result = setup
    recs = result.recommendations.query("policy == 'topk' and k == 5")
    small = recs[recs.N == 20].set_index(["target_id", "rank"])["candidate_id"]
    large = recs[recs.N == 30].set_index(["target_id", "rank"])["candidate_id"]
    assert small.sort_index().equals(large.sort_index())


def test_deterministic(setup):
    params, bank, targets, metric, result = setup
    again = evaluate(ParamProxyRelevance(params, seed=3), targets, bank, params, metric, SPEC)
    pd.testing.assert_frame_equal(result.per_target, again.per_target)
    pd.testing.assert_frame_equal(result.recommendations, again.recommendations)


def test_targets_in_bank_refused(setup):
    params, bank, _, metric, _ = setup
    with pytest.raises(LeakageError):
        evaluate(ParamProxyRelevance(params, seed=3), bank[:2], bank, params, metric, SPEC)


def test_pool_head_matches_rebuilt_pool():
    rng = np.random.default_rng(1)
    ids = [f"c{i}" for i in range(40)]
    params = pd.DataFrame(rng.random((40, 4)), index=ids)
    pool = pool_from_scores(rng.random(40), ids, 40)
    metric = ParamDistance(4)
    target = rng.random(4)
    full = PoolArrays.from_pool(pool, params, metric, target_vector=target)
    direct = PoolArrays.from_pool(pool.iloc[:15], params, metric, target_vector=target)
    head = full.head(15)
    assert np.array_equal(head.pair_dist, direct.pair_dist)
    assert np.array_equal(head.target_dist, direct.target_dist)
    assert metrics_from_indices([0, 3, 7], head, [0.2], [0, 1, 2])["mean_pair_dist"] == \
        metrics_from_indices([0, 3, 7], direct, [0.2], [0, 1, 2])["mean_pair_dist"]


def test_paired_deltas_and_summary(setup):
    *_, result = setup
    per_target = add_paired_deltas(result.per_target)
    topk_rows = per_target[per_target.policy == TOPK]
    assert (topk_rows["rel_loss_vs_topk"] == 0).all()
    assert (topk_rows["delta_mean_pair_dist_vs_topk"] == 0).all()
    summary = summarize(per_target, ["policy", "lam", "N", "k"], ["mean_rel", "rel_loss_vs_topk"],
                        resamples=500, seed=1)
    assert len(summary) == 2 * 2 * (1 + len(SPEC.lambda_grid) + 1)
    assert (summary["n_targets"] == 12).all()
    assert (summary["mean_rel_ci_low"] <= summary["mean_rel_mean"]).all()
    assert (summary["mean_rel_mean"] <= summary["mean_rel_ci_high"]).all()
    assert summary.equals(summarize(per_target, ["policy", "lam", "N", "k"], ["mean_rel", "rel_loss_vs_topk"],
                                    resamples=500, seed=1))


def test_bootstrap_ci_hand_case():
    values = np.array([1.0, 1.0, 1.0, np.nan])
    mean, low, high = bootstrap_mean_ci(values, bootstrap_indices(4, 200, 0))
    assert mean == low == high == 1.0
