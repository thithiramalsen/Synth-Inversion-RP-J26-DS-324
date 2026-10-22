"""Phase 7 selection rules on hand-built tables."""

import numpy as np
import pandas as pd
import pytest

from c3.tuning import choose_epsilon, epsilon_sensitivity, select_operating_point


def summary_rows(rows):
    return pd.DataFrame([{"policy": "mmr", "k": 5, "mean_rel_mean": 0.9, "rel_loss_vs_topk_mean": r[2] / 2,
                          "min_pair_dist_mean": 0.2, "N": r[0], "lam": r[1], "rel_loss_vs_topk_ci_high": r[2],
                          "mean_pair_dist_mean": r[3]} for r in rows])


def test_highest_diversity_within_tolerance_is_chosen():
    s = summary_rows([(50, 1.0, 0.0, 0.30), (50, 0.9, 0.010, 0.35), (50, 0.8, 0.030, 0.40),
                      (100, 1.0, 0.0, 0.30), (100, 0.9, 0.015, 0.37)])
    result = select_operating_point(s, tau=0.02, k=5)
    assert result["chosen"]["N"] == 100 and result["chosen"]["lam"] == 0.9
    assert result["outcome"] == "diversity gain within tolerance"
    assert result["per_N_best"] == {50: 0.9, 100: 0.9}


def test_ties_prefer_smaller_n_then_larger_lambda():
    s = summary_rows([(50, 1.0, 0.0, 0.30), (50, 0.9, 0.01, 0.36), (100, 0.9, 0.01, 0.36), (50, 0.85, 0.01, 0.36)])
    chosen = select_operating_point(s, tau=0.02, k=5)["chosen"]
    assert (chosen["N"], chosen["lam"]) == (50, 0.9)


def test_negative_result_when_only_lambda_one_is_eligible():
    s = summary_rows([(50, 1.0, 0.0, 0.30), (50, 0.9, 0.05, 0.40)])
    result = select_operating_point(s, tau=0.02, k=5)
    assert result["chosen"]["lam"] == 1.0 and result["outcome"] == "no diversity gain within tolerance"


def per_target_fixture():
    rows = []
    for t in range(10):
        top_dup = 0.2 if t < 3 else 0.0  # 30% of targets have a near-duplicate at eps 0.15 only
        for policy, lam, dup in (("topk", np.nan, top_dup), ("mmr", 0.9, 0.0)):
            rows.append({"target_id": f"t{t}", "N": 50, "k": 5, "policy": policy, "lam": lam,
                         "dup_rate@0.05": 0.0, "dup_rate@0.15": dup})
    return pd.DataFrame(rows)


def test_epsilon_sensitivity_and_choice():
    table = epsilon_sensitivity(per_target_fixture(), N=50, k=5, lam=0.9, epsilon_grid=[0.05, 0.15],
                                resamples=200, seed=1)
    row = table.set_index("epsilon").loc[0.15]
    assert row["topk_dup_rate_mean"] == pytest.approx(0.06)
    assert row["mmr_minus_topk_mean"] == pytest.approx(-0.06)
    assert row["share_targets_topk_has_near_duplicate"] == pytest.approx(0.3)
    choice = choose_epsilon(table)
    assert choice == {"epsilon": 0.15, "informative": True,
                      "rule": "smallest epsilon with >= 10% of targets having a top-k near-duplicate"}
    assert choose_epsilon(table[table.epsilon == 0.05])["informative"] is False
